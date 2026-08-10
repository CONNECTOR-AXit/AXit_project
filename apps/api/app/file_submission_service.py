"""Secure local-blob file submissions for the approved Phase 4 ingestion lane."""

from __future__ import annotations

import hashlib
import os
import unicodedata
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Final
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from app.activity_policy import build_event_key
from app.activity_service import ActivityService
from app.queue_repository import PostgresJobQueue
from app.sandbox_ipc import ParserIdentity
from app.text_submission_service import SubmissionView, _validated_title


MAX_FILE_BYTES: Final = 200 * 1024 * 1024
READ_CHUNK_BYTES: Final = 64 * 1024


class FileSubmissionError(ValueError):
    """Base class for a safe file-submission contract failure."""


class FileSubmissionValidationError(FileSubmissionError):
    """The upload metadata, length, or content signature is invalid."""


class FileSubmissionAccessError(PermissionError):
    """The actor cannot access the requested session or revision."""


class FileSubmissionStateError(FileSubmissionError):
    """A file can only be submitted while the talk session is open."""


class FileSubmissionLimitError(FileSubmissionValidationError):
    """The session already contains twenty current revisions."""


@dataclass(frozen=True, slots=True)
class FileType:
    extension: str
    media_type: str
    parser: ParserIdentity


_PREVIEW_MAX_BLOCKS: Final = 20
_PREVIEW_MAX_CHARS: Final = 4_000
_PNG_MAGIC: Final = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC: Final = b"\xff\xd8\xff"


@dataclass(frozen=True, slots=True)
class ExtractedPreview:
    text: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class OriginalDownload:
    filename: str
    mime_type: str
    byte_size: int
    _blob_store: LocalBlobStore
    _storage_key: str
    _sha256: str

    @contextmanager
    def open(self) -> Iterator[BinaryIO]:
        with self._blob_store.open_regular(
            self._storage_key,
            expected_size=self.byte_size,
            expected_sha256=self._sha256,
        ) as source:
            yield source


_FILE_TYPES: Final = {
    ".pdf": FileType(".pdf", "application/pdf", ParserIdentity("pypdfium2", "5.12.1")),
    ".png": FileType(
        ".png", "image/png", ParserIdentity("pillow+tesseract-cli", "12.3.0+5.3.0")
    ),
    ".jpg": FileType(
        ".jpg", "image/jpeg", ParserIdentity("pillow+tesseract-cli", "12.3.0+5.3.0")
    ),
    ".jpeg": FileType(
        ".jpeg", "image/jpeg", ParserIdentity("pillow+tesseract-cli", "12.3.0+5.3.0")
    ),
    ".hwp": FileType(".hwp", "application/x-hwp", ParserIdentity("pyhwp", "0.1b15")),
    ".hwpx": FileType(".hwpx", "application/x-hwpx", ParserIdentity("hwpxlib", "1.0.9")),
    ".txt": FileType(
        ".txt", "text/plain", ParserIdentity("builtin-utf8-text", "1.0.0")
    ),
    ".docx": FileType(
        ".docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ParserIdentity("stdlib-docx", "1.0.0"),
    ),
    ".pptx": FileType(
        ".pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ParserIdentity("libreoffice+pypdfium2+tesseract-cli", "1.0.0"),
    ),
    ".xlsx": FileType(
        ".xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ParserIdentity("stdlib-xlsx", "1.0.0"),
    ),
}

_DECLARED_MEDIA_TYPES: Final = {
    ".pdf": frozenset({"application/pdf", "application/octet-stream"}),
    ".png": frozenset({"image/png", "application/octet-stream"}),
    ".jpg": frozenset({"image/jpeg", "application/octet-stream"}),
    ".jpeg": frozenset({"image/jpeg", "application/octet-stream"}),
    ".hwp": frozenset(
        {
            "application/x-hwp",
            "application/haansofthwp",
            "application/vnd.hancom.hwp",
            "application/octet-stream",
        }
    ),
    ".hwpx": frozenset(
        {
            "application/x-hwpx",
            "application/haansofthwpx",
            "application/vnd.hancom.hwpx",
            "application/octet-stream",
        }
    ),
    ".txt": frozenset(
        {"text/plain", "text/markdown", "application/octet-stream"}
    ),
    ".docx": frozenset(
        {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/haansoftdocx",
            "application/zip",
            "application/octet-stream",
        }
    ),
    ".pptx": frozenset(
        {
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            # Windows/Hancom file associations commonly report PPTX files
            # with this vendor MIME even though the package is standard OOXML.
            "application/haansoftpptx",
            "application/vnd.ms-powerpoint",
            "application/zip",
            "application/octet-stream",
        }
    ),
    ".xlsx": frozenset(
        {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            # Windows/Hancom file associations report XLSX files with this
            # vendor MIME even though the package is standard OOXML.
            "application/haansoftxlsx",
            "application/vnd.ms-excel",
            "application/zip",
            "application/octet-stream",
        }
    ),
}


class LocalBlobStore:
    """A bounded, traversal-free blob store rooted outside the public web tree."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def temporary_path(self) -> Path:
        path = self.root / f".upload-{uuid4().hex}.tmp"
        if path.parent != self.root:
            raise RuntimeError("blob staging path escaped its root")
        return path

    def commit(self, temporary: Path, *, revision_id: UUID) -> str:
        key = f"{revision_id.hex}.blob"
        destination = self.path_for(key)
        os.replace(temporary, destination)
        _fsync_file_and_parent(destination)
        return key

    def path_for(self, key: str) -> Path:
        if not key or Path(key).name != key or any(c in key for c in ("/", "\\", "\0")):
            raise FileSubmissionError("invalid blob key")
        path = (self.root / key).resolve()
        if path.parent != self.root:
            raise FileSubmissionError("invalid blob key")
        return path

    def read(self, key: str, *, expected_size: int, expected_sha256: str) -> bytes:
        with self.open_regular(
            key,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        ) as source:
            return source.read()

    @contextmanager
    def open_regular(
        self, key: str, *, expected_size: int, expected_sha256: str
    ) -> Iterator[BinaryIO]:
        path = self.path_for(key)
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise FileSubmissionError("stored source is not a regular file")
        source = path.open("rb")
        try:
            opened = os.fstat(source.fileno())
            if opened.st_size != expected_size or opened.st_ino != metadata.st_ino:
                raise FileSubmissionError("stored source integrity check failed")
            digest = hashlib.sha256()
            while chunk := source.read(READ_CHUNK_BYTES):
                digest.update(chunk)
            if digest.hexdigest() != expected_sha256:
                raise FileSubmissionError("stored source integrity check failed")
            source.seek(0)
            yield source
        finally:
            source.close()

    def delete(self, key_or_path: str | Path) -> None:
        path = key_or_path if isinstance(key_or_path, Path) else self.path_for(key_or_path)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Best-effort rollback cleanup; a later local janitor may remove an orphan.
            pass

    def sweep_orphans(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        minimum_age_seconds: int = 24 * 60 * 60,
        now: float | None = None,
    ) -> int:
        """Delete only old, immediate-child blobs absent from durable DB references."""

        if (
            isinstance(minimum_age_seconds, bool)
            or not isinstance(minimum_age_seconds, int)
            or minimum_age_seconds < 24 * 60 * 60
        ):
            raise ValueError("orphan minimum age must be at least 24 hours")
        cutoff = (time.time() if now is None else now) - minimum_age_seconds
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT storage_key FROM source_revisions WHERE storage_key IS NOT NULL"
            )
            referenced = {str(row["storage_key"]) for row in cursor.fetchall()}
        removed = 0
        for candidate in self.root.iterdir():
            name = candidate.name
            if not (
                (name.startswith(".upload-") and name.endswith(".tmp"))
                or name.endswith(".blob")
            ):
                continue
            try:
                metadata = candidate.lstat()
                if (
                    stat.S_ISLNK(metadata.st_mode)
                    or not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_mtime > cutoff
                    or name in referenced
                ):
                    continue
                candidate.unlink()
                removed += 1
            except OSError:
                continue
        return removed


class FileSubmissionService:
    def __init__(
        self,
        *,
        blob_store: LocalBlobStore,
        queue: PostgresJobQueue | None = None,
        activity_service: ActivityService | None = None,
    ) -> None:
        self._blob_store = blob_store
        self._queue = queue or PostgresJobQueue()
        self._activities = activity_service or ActivityService()

    def submit(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
        filename: str,
        declared_mime_type: str,
        stream: BinaryIO,
        content_length: int | None,
        title: str = "공유 자료",
    ) -> SubmissionView:
        safe_name = _safe_filename(filename)
        normalized_title = _validated_title(title)
        file_type = _declared_file_type(safe_name, declared_mime_type)
        temporary = self._blob_store.temporary_path()
        committed_key: str | None = None
        try:
            size, digest, prefix = _stream_to_file(
                stream, temporary, content_length=content_length
            )
            file_type = _effective_file_type(file_type, prefix)
            submission_id = uuid4()
            revision_id = uuid4()
            with connection.transaction():
                with connection.cursor(row_factory=dict_row) as cursor:
                    room_id = _require_open_member_session(cursor, session_id, actor_id)
                    if _current_revision_count(cursor, session_id) >= 20:
                        raise FileSubmissionLimitError("current revision limit reached")
                    committed_key = self._blob_store.commit(
                        temporary, revision_id=revision_id
                    )
                    cursor.execute(
                        """
                        INSERT INTO submissions (id, session_id, author_id, kind, title)
                        VALUES (%s, %s, %s, 'file', %s)
                        """,
                        (submission_id, session_id, actor_id, normalized_title),
                    )
                    cursor.execute(
                        """
                        INSERT INTO source_revisions (
                            id, submission_id, revision_no, filename, mime_type,
                            byte_size, sha256, storage_key, processing_state, is_current
                        ) VALUES (%s, %s, 1, %s, %s, %s, %s, %s, 'queued', TRUE)
                        """,
                        (
                            revision_id,
                            submission_id,
                            safe_name,
                            file_type.media_type,
                            size,
                            digest,
                            committed_key,
                        ),
                    )
                    self._queue.enqueue(
                        connection,
                        logical_key=f"extraction:{revision_id}",
                        kind="extraction",
                        payload={
                            "revision_id": str(revision_id),
                            "media_type": file_type.media_type,
                            "parser": file_type.parser.to_dict(),
                        },
                    )
                    self._activities.record(
                        cursor,
                        event_key=build_event_key(
                            "submission.created", submission_id=submission_id,
                            revision_no=1,
                        ),
                        event_type="submission.created", actor_id=actor_id,
                        scope_type="session", room_id=room_id, session_id=session_id,
                        entity_type="submission", entity_id=submission_id,
                        metadata={"kind": "file", "revision_no": 1,
                                  "media_type": file_type.media_type,
                                  "byte_size": size},
                    )
            return SubmissionView(
                id=submission_id,
                session_id=session_id,
                author_id=actor_id,
                kind="file",
                title=normalized_title,
                current_revision_id=revision_id,
                processing_state="queued",
            )
        except Exception:
            self._blob_store.delete(committed_key or temporary)
            raise

    def download_original(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        revision_id: UUID,
        actor_id: UUID,
    ) -> OriginalDownload:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT revision.filename, revision.mime_type, revision.byte_size,
                       revision.sha256, revision.storage_key
                FROM source_revisions AS revision
                JOIN submissions AS submission ON submission.id = revision.submission_id
                JOIN talk_sessions AS session_row ON session_row.id = submission.session_id
                JOIN room_memberships AS membership
                  ON membership.room_id = session_row.room_id
                 AND membership.user_id = %s
                 AND membership.left_at IS NULL
                WHERE revision.id = %s AND submission.kind = 'file'
                  AND submission.deleted_at IS NULL
                """,
                (actor_id, revision_id),
            )
            row = cursor.fetchone()
        if row is None or not isinstance(row["storage_key"], str):
            raise FileSubmissionAccessError("source revision is unavailable")
        size = int(row["byte_size"])
        return OriginalDownload(
            filename=str(row["filename"]),
            mime_type=str(row["mime_type"]),
            byte_size=size,
            _blob_store=self._blob_store,
            _storage_key=row["storage_key"],
            _sha256=str(row["sha256"]),
        )

    def retry_extraction(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        revision_id: UUID,
        actor_id: UUID,
    ) -> None:
        """Requeue extraction for a revision stuck in a terminal failure.

        The stored bytes never change here — only a genuinely new upload can
        fix a truly corrupt file. This just gives the same file another run
        through the parser sandbox, which is the useful action for the more
        common case (a transient sandbox failure, not a bad file).
        """

        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT revision.processing_state, session_row.room_id, submission.session_id
                    FROM source_revisions AS revision
                    JOIN submissions AS submission ON submission.id = revision.submission_id
                    JOIN talk_sessions AS session_row ON session_row.id = submission.session_id
                    JOIN room_memberships AS membership
                      ON membership.room_id = session_row.room_id
                     AND membership.user_id = %s
                     AND membership.left_at IS NULL
                    WHERE revision.id = %s AND submission.kind = 'file'
                      AND submission.deleted_at IS NULL
                    """,
                    (actor_id, revision_id),
                )
                row = cursor.fetchone()
                if row is None:
                    raise FileSubmissionAccessError("source revision is unavailable")
                if row["processing_state"] != "failed":
                    raise FileSubmissionStateError("only a failed revision can be retried")
                cursor.execute(
                    """
                    UPDATE jobs
                    SET state = 'pending', error_code = NULL, updated_at = clock_timestamp()
                    WHERE logical_key = %s AND state = 'failed_terminal'
                    """,
                    (f"extraction:{revision_id}",),
                )
                if cursor.rowcount == 0:
                    raise FileSubmissionStateError("extraction job is not retryable")
                cursor.execute(
                    """
                    UPDATE source_revisions
                    SET processing_state = 'queued'
                    WHERE id = %s
                    """,
                    (revision_id,),
                )
                self._activities.record(
                    cursor,
                    event_key=build_event_key(
                        "source_revision.retry_requested",
                        revision_id=revision_id,
                        retry_nonce=uuid4(),
                    ),
                    event_type="source_revision.retry_requested", actor_id=actor_id,
                    scope_type="session", room_id=row["room_id"], session_id=row["session_id"],
                    entity_type="source_revision", entity_id=revision_id,
                    metadata={},
                )

    def stream_original(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        download: OriginalDownload,
        revision_id: UUID,
        actor_id: UUID,
    ) -> Iterator[bytes]:
        """Stream an original while bounding membership-revocation exposure.

        Each chunk is authorized against a fresh READ COMMITTED statement.  The
        transaction is committed before bytes are yielded, so a slow download
        never retains a database snapshot or lock for its lifetime.
        """

        with download.open() as source:
            while True:
                self._require_original_access(
                    connection,
                    revision_id=revision_id,
                    actor_id=actor_id,
                )
                connection.commit()
                chunk = source.read(READ_CHUNK_BYTES)
                if not chunk:
                    return
                yield chunk

    @staticmethod
    def _require_original_access(
        connection: psycopg.Connection[dict[str, Any]],
        *,
        revision_id: UUID,
        actor_id: UUID,
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM source_revisions AS revision
                JOIN submissions AS submission ON submission.id = revision.submission_id
                JOIN talk_sessions AS session_row ON session_row.id = submission.session_id
                JOIN room_memberships AS membership
                  ON membership.room_id = session_row.room_id
                 AND membership.user_id = %s
                 AND membership.left_at IS NULL
                WHERE revision.id = %s AND submission.kind = 'file'
                  AND submission.deleted_at IS NULL
                """,
                (actor_id, revision_id),
            )
            if cursor.fetchone() is None:
                raise FileSubmissionAccessError("source revision is unavailable")

    def preview_extracted_text(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        revision_id: UUID,
        actor_id: UUID,
    ) -> "ExtractedPreview":
        """Return the leading extracted blocks for a ready revision.

        Formats without an in-browser renderer (hwp, hwpx, docx, ...) fall
        back to this bounded, already-extracted text instead of nothing —
        it reuses the same blocks the sandbox parser already produced, so no
        extra client-side document parsing is needed.
        """

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT revision.processing_state, revision.approved_extraction_run_id
                FROM source_revisions AS revision
                JOIN submissions AS submission ON submission.id = revision.submission_id
                JOIN talk_sessions AS session_row ON session_row.id = submission.session_id
                JOIN room_memberships AS membership
                  ON membership.room_id = session_row.room_id
                 AND membership.user_id = %s
                 AND membership.left_at IS NULL
                WHERE revision.id = %s AND submission.kind = 'file'
                  AND submission.deleted_at IS NULL
                """,
                (actor_id, revision_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise FileSubmissionAccessError("source revision is unavailable")
            if row["processing_state"] != "ready" or row["approved_extraction_run_id"] is None:
                raise FileSubmissionStateError("preview is not available yet")
            cursor.execute(
                """
                SELECT text FROM source_anchors
                WHERE extraction_run_id = %s
                ORDER BY ordinal
                LIMIT %s
                """,
                (row["approved_extraction_run_id"], _PREVIEW_MAX_BLOCKS),
            )
            blocks = [str(block_row["text"]) for block_row in cursor.fetchall()]
        text = "\n\n".join(blocks)
        truncated = len(text) > _PREVIEW_MAX_CHARS
        return ExtractedPreview(text=text[:_PREVIEW_MAX_CHARS], truncated=truncated)


def _fsync_file_and_parent(path: Path) -> None:
    """Make a replaced blob and its directory entry durable before DB commit."""

    # Windows requires a writable descriptor for ``os.fsync``; POSIX accepts
    # this mode as well for the locally owned immutable blob.
    file_descriptor = os.open(path, os.O_RDWR)
    try:
        os.fsync(file_descriptor)
    finally:
        os.close(file_descriptor)

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        directory_descriptor = os.open(path.parent, directory_flags)
    except OSError:
        if os.name == "nt":
            _flush_windows_directory(path.parent)
            return
        raise
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _flush_windows_directory(path: Path) -> None:
    """Apply the Windows equivalent of fsync to a directory handle."""

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    flush_file_buffers = kernel32.FlushFileBuffers
    flush_file_buffers.argtypes = [wintypes.HANDLE]
    flush_file_buffers.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = create_file(
        str(path),
        0x40000000,  # GENERIC_WRITE is required for FlushFileBuffers.
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        3,  # OPEN_EXISTING
        0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS permits directory handles.
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not flush_file_buffers(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        close_handle(handle)


def _safe_filename(filename: str) -> str:
    normalized = unicodedata.normalize("NFC", filename)
    if (
        not normalized
        or len(normalized.encode("utf-8")) > 255
        or Path(normalized).name != normalized
        or any(c in normalized for c in ("/", "\\", "\0", "\r", "\n"))
        or normalized in {".", ".."}
    ):
        raise FileSubmissionValidationError("filename must be a safe basename")
    return normalized


def _declared_file_type(filename: str, mime_type: str) -> FileType:
    extension = Path(filename).suffix.lower()
    file_type = _FILE_TYPES.get(extension)
    declared = mime_type.strip().lower() or "application/octet-stream"
    if file_type is None or declared not in _DECLARED_MEDIA_TYPES.get(extension, frozenset()):
        raise FileSubmissionValidationError("file extension and media type are unsupported")
    return file_type


def _stream_to_file(
    stream: BinaryIO, path: Path, *, content_length: int | None
) -> tuple[int, str, bytes]:
    if content_length is not None and (
        isinstance(content_length, bool) or content_length < 1 or content_length > MAX_FILE_BYTES
    ):
        if content_length is not None and content_length > MAX_FILE_BYTES:
            raise FileSubmissionLimitError("file exceeds the upload limit")
        raise FileSubmissionValidationError("file size is invalid")
    size = 0
    digest = hashlib.sha256()
    prefix = bytearray()
    with path.open("xb") as target:
        while True:
            chunk = stream.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                raise FileSubmissionValidationError("file stream must yield bytes")
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise FileSubmissionLimitError("file exceeds the upload limit")
            if len(prefix) < 16:
                prefix.extend(chunk[: 16 - len(prefix)])
            digest.update(chunk)
            target.write(chunk)
        target.flush()
        os.fsync(target.fileno())
    if size == 0 or (content_length is not None and size != content_length):
        raise FileSubmissionValidationError("file size does not match the upload")
    return size, digest.hexdigest(), bytes(prefix)


def _require_magic(file_type: FileType, prefix: bytes) -> None:
    valid = {
        "application/pdf": prefix.startswith(b"%PDF-"),
        "image/png": prefix.startswith(_PNG_MAGIC),
        "image/jpeg": prefix.startswith(_JPEG_MAGIC),
        "application/x-hwp": prefix.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        "application/x-hwpx": prefix.startswith((b"PK\x03\x04", b"PK\x05\x06")),
        "text/plain": b"\x00" not in prefix,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": prefix.startswith(
            (b"PK\x03\x04", b"PK\x05\x06")
        ),
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": prefix.startswith(
            (b"PK\x03\x04", b"PK\x05\x06")
        ),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": prefix.startswith(
            (b"PK\x03\x04", b"PK\x05\x06")
        ),
    }[file_type.media_type]
    if not valid:
        raise FileSubmissionValidationError("file content does not match its declared type")


def _effective_file_type(file_type: FileType, prefix: bytes) -> FileType:
    """Resolve the parser from the bytes for the known JPEG-labelled PNG case.

    Some image exporters write PNG bytes while retaining a ``.jpg``/``.jpeg``
    filename.  Keep the upload metadata validation strict for every other
    mismatch, but let this bounded compatibility case use the PNG parser all
    the way through extraction.
    """

    if file_type.media_type == "image/jpeg" and prefix.startswith(_PNG_MAGIC):
        file_type = _FILE_TYPES[".png"]
    _require_magic(file_type, prefix)
    return file_type


def _require_open_member_session(cursor: Any, session_id: UUID, actor_id: UUID) -> UUID:
    cursor.execute(
        """
        SELECT session_row.state, session_row.room_id
        FROM talk_sessions AS session_row
        JOIN room_memberships AS membership
          ON membership.room_id = session_row.room_id
         AND membership.user_id = %s AND membership.left_at IS NULL
        WHERE session_row.id = %s
        FOR UPDATE OF session_row
        """,
        (actor_id, session_id),
    )
    row = cursor.fetchone()
    if row is None:
        raise FileSubmissionAccessError("talk session is unavailable")
    if row["state"] != "open":
        raise FileSubmissionStateError("talk session must be open")
    room_id = row["room_id"]
    if isinstance(room_id, UUID):
        return room_id
    if isinstance(room_id, str):
        return UUID(room_id)
    raise RuntimeError("persisted session room id must be UUID")


def _current_revision_count(cursor: Any, session_id: UUID) -> int:
    cursor.execute(
        """
        SELECT count(*) AS count
        FROM source_revisions AS revision
        JOIN submissions AS submission ON submission.id = revision.submission_id
        WHERE submission.session_id = %s AND revision.is_current
        """,
        (session_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("current revision count is unavailable")
    return int(row["count"])
