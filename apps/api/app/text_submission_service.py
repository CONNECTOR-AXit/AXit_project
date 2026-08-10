"""Atomic text-only submission and inline-extraction service for Phase 3.

Text submissions deliberately bypass the Phase 4 file/parser path, but they
still create the same provenance chain: submission -> immutable revision ->
successful extraction run -> canonical G0-compatible source anchors.  Close
and submit serialize on the same ``talk_sessions`` parent row lock.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from app.activity_policy import build_event_key
from app.activity_service import ActivityService
from psycopg.types.json import Jsonb

from app.auth_service import UserRecord


ANCHOR_SCHEMA_VERSION: Final = "1"
INLINE_TEXT_PARSER_NAME: Final = "inline-text"
INLINE_TEXT_PARSER_VERSION: Final = "1"
INLINE_TEXT_NEWLINE_POLICY: Final = "lf"
INLINE_TEXT_UNICODE_NORMALIZATION: Final = "nfc"
MAX_CURRENT_REVISIONS_PER_SESSION: Final = 20
MAX_TEXT_CHARACTERS: Final = 100_000
MAX_SUBMISSION_TITLE_CHARACTERS: Final = 500


class TextSubmissionError(ValueError):
    """Base class for a text-submission contract failure."""


class TextSubmissionAccessError(PermissionError):
    """Current room membership was absent before submission details were read."""


class TextSubmissionOwnerError(PermissionError):
    """A room member attempted to replace another participant's submission."""


class TextSubmissionStateError(TextSubmissionError):
    """A create/replace operation requires an open relay session."""


class TextSubmissionLimitError(TextSubmissionError):
    """The session already has its allowed number of current revisions."""


class TextViewerUnavailableError(TextSubmissionError):
    """The requested revision is not an inline text source with a visible anchor."""


@dataclass(frozen=True, slots=True)
class SubmissionView:
    id: UUID
    session_id: UUID
    author_id: UUID
    kind: Literal["text", "file"]
    title: str
    current_revision_id: UUID
    processing_state: Literal["uploaded", "queued", "extracting", "ready", "failed"]


@dataclass(frozen=True, slots=True)
class SubmissionMetadataView:
    id: UUID
    session_id: UUID
    author_id: UUID
    kind: Literal["text", "file"]
    title: str
    current_revision_id: UUID
    processing_state: Literal["uploaded", "queued", "extracting", "ready", "failed"]
    filename: str
    mime_type: str
    byte_size: int
    author: UserRecord
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SourceRevisionView:
    """Internal viewer projection; raw source text is omitted from ``repr``."""

    id: UUID
    submission_id: UUID
    filename: str
    mime_type: str
    byte_size: int
    processing_state: Literal["uploaded", "queued", "extracting", "ready", "failed"]
    source_text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class TextAnchorView:
    """Server-issued anchor UUID plus canonical payload and exact source span."""

    id: UUID
    revision_id: UUID
    canonical_payload: dict[str, object] = field(repr=False)
    exact_quote: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class TextViewerView:
    revision: SourceRevisionView
    highlighted_anchor: TextAnchorView | None


def normalize_text(value: str) -> str:
    """Apply the exact G0 NFC/LF profile without trimming source content."""

    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def _canonicalize_json(value: object) -> object:
    """The G0 canonical JSON profile used by text-anchor identities."""

    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON numbers must be finite")
        rounded = round(value, 6)
        if rounded == 0:
            return 0
        if rounded.is_integer():
            return int(rounded)
        return rounded
    if isinstance(value, str):
        return normalize_text(value)
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("canonical JSON object keys must be strings")
            normalized_key = normalize_text(key)
            if normalized_key in normalized:
                raise ValueError("canonical JSON contains colliding normalized keys")
            normalized[normalized_key] = _canonicalize_json(child)
        return normalized
    if isinstance(value, Sequence) and not isinstance(
        value, (bytes, bytearray, memoryview)
    ):
        return [_canonicalize_json(child) for child in value]
    raise ValueError(f"unsupported canonical JSON value type: {type(value).__name__}")


def canonical_json(value: object) -> str:
    """Serialize the limited inline-anchor payload identically on every host."""

    return json.dumps(
        _canonicalize_json(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_sha256(value: object) -> str:
    """Hash canonical JSON identities, never server UUID envelopes."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


INLINE_TEXT_EXTRACTION_PROFILE_HASH: Final = canonical_sha256(
    {
        "anchor_schema_version": 1,
        "newline_policy": INLINE_TEXT_NEWLINE_POLICY,
        "parser": INLINE_TEXT_PARSER_NAME,
        "parser_version": INLINE_TEXT_PARSER_VERSION,
        "unicode_normalization": INLINE_TEXT_UNICODE_NORMALIZATION,
    }
)


def text_line_anchor_payload(
    *,
    source_sha256: str,
    line: int,
    exact_quote: str,
) -> dict[str, object]:
    """Build one G0-compatible typed ``text_line`` payload.

    The source has already been NFC/LF normalized, so Python string indexes
    are Unicode code-point offsets exactly as the G0 anchor schema requires.
    """

    if not exact_quote:
        raise TextSubmissionError("text line anchor quote must not be empty")
    return {
        "schema_version": 1,
        "kind": "text_line",
        "source_sha256": source_sha256,
        "extraction_profile_hash": INLINE_TEXT_EXTRACTION_PROFILE_HASH,
        "locator": {"line": line, "start": 0, "end": len(exact_quote)},
        "text_fingerprint": hashlib.sha256(exact_quote.encode("utf-8")).hexdigest(),
    }


class TextSubmissionService:
    """Persist text source revisions and their immediate deterministic anchors."""

    def __init__(self, *, max_current_revisions: int = MAX_CURRENT_REVISIONS_PER_SESSION,
                 activity_service: ActivityService | None = None) -> None:
        if max_current_revisions < 1:
            raise ValueError("max_current_revisions must be positive")
        self._max_current_revisions = max_current_revisions
        self._activities = activity_service or ActivityService()

    def submit(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
        text: str,
        title: str = "공유 자료",
    ) -> SubmissionView:
        """Create a new text submission under the session aggregate lock."""

        normalized = _validated_normalized_text(text)
        normalized_title = _validated_title(title)
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                room_id = _require_open_member_session(cursor, session_id, actor_id)
                current_count = _current_revision_count(cursor, session_id)
                if current_count >= self._max_current_revisions:
                    raise TextSubmissionLimitError("session current-revision limit reached")
                submission_id = uuid4()
                cursor.execute(
                    """
                    INSERT INTO submissions (id, session_id, author_id, kind, title)
                    VALUES (%s, %s, %s, 'text', %s)
                    """,
                    (submission_id, session_id, actor_id, normalized_title),
                )
                revision_id = _insert_ready_text_revision(
                    cursor,
                    submission_id=submission_id,
                    revision_no=1,
                    text=normalized,
                )
                self._activities.record(
                    cursor,
                    event_key=build_event_key(
                        "submission.created", submission_id=submission_id, revision_no=1,
                    ),
                    event_type="submission.created", actor_id=actor_id,
                    scope_type="session", room_id=room_id, session_id=session_id,
                    entity_type="submission", entity_id=submission_id,
                    metadata={"kind": "text", "revision_no": 1},
                )
        return SubmissionView(
            id=submission_id,
            session_id=session_id,
            author_id=actor_id,
            kind="text",
            title=normalized_title,
            current_revision_id=revision_id,
            processing_state="ready",
        )

    def replace(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        submission_id: UUID,
        actor_id: UUID,
        text: str,
    ) -> SubmissionView:
        """Append a new immutable current revision only for its own author."""

        normalized = _validated_normalized_text(text)
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                submission = _locked_member_submission(cursor, submission_id, actor_id)
                if submission is None:
                    raise TextSubmissionAccessError("submission is unavailable")
                if submission["author_id"] != actor_id:
                    raise TextSubmissionOwnerError("only the submission author may replace it")
                if submission["kind"] != "text":
                    raise TextSubmissionError("only text submissions can be replaced in phase 3")
                state = _session_state(submission["session_state"])
                if state != "open":
                    raise TextSubmissionStateError("talk session must be open")

                cursor.execute(
                    """
                    SELECT COALESCE(MAX(revision_no), 0) AS latest_revision_no
                    FROM source_revisions
                    WHERE submission_id = %s
                    """,
                    (submission_id,),
                )
                revision_row = _require_row(cursor.fetchone(), "latest revision")
                latest_revision_no = revision_row["latest_revision_no"]
                if isinstance(latest_revision_no, bool) or not isinstance(latest_revision_no, int):
                    raise RuntimeError("persisted revision number must be an integer")
                cursor.execute(
                    """
                    UPDATE source_revisions
                    SET is_current = FALSE
                    WHERE submission_id = %s AND is_current
                    """,
                    (submission_id,),
                )
                revision_id = _insert_ready_text_revision(
                    cursor,
                    submission_id=submission_id,
                    revision_no=latest_revision_no + 1,
                    text=normalized,
                )
                session_id = _uuid(submission["session_id"], "submission session id")
                room_id = _uuid(submission["room_id"], "submission room id")
                author_id = _uuid(submission["author_id"], "submission author id")
                title = _text(submission["title"], "submission title")
                revision_no = latest_revision_no + 1
                self._activities.record(
                    cursor,
                    event_key=build_event_key(
                        "submission.revised", submission_id=submission_id,
                        revision_no=revision_no,
                    ),
                    event_type="submission.revised", actor_id=actor_id,
                    scope_type="session", room_id=room_id, session_id=session_id,
                    entity_type="submission", entity_id=submission_id,
                    metadata={"kind": "text", "revision_no": revision_no},
                )
        return SubmissionView(
            id=submission_id,
            session_id=session_id,
            author_id=author_id,
            kind="text",
            title=title,
            current_revision_id=revision_id,
            processing_state="ready",
        )

    def delete(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        submission_id: UUID,
        actor_id: UUID,
    ) -> None:
        """Soft-delete a submission (any kind) so it drops out of the document list.

        A tombstone (``deleted_at``), not a row DELETE — ``source_revisions``,
        anchors, and activity already reference this submission, and a real
        upload the author never fixed shouldn't erase that provenance.
        Deleting twice is a no-op, not an error, so a doubled click is safe.
        """

        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                submission = _locked_member_submission(cursor, submission_id, actor_id)
                if submission is None:
                    raise TextSubmissionAccessError("submission is unavailable")
                if submission["author_id"] != actor_id:
                    raise TextSubmissionOwnerError("only the submission author may delete it")
                if submission["deleted_at"] is not None:
                    return
                state = _session_state(submission["session_state"])
                if state != "open":
                    raise TextSubmissionStateError("talk session must be open")
                cursor.execute(
                    "UPDATE submissions SET deleted_at = clock_timestamp() WHERE id = %s",
                    (submission_id,),
                )
                session_id = _uuid(submission["session_id"], "submission session id")
                room_id = _uuid(submission["room_id"], "submission room id")
                self._activities.record(
                    cursor,
                    event_key=build_event_key(
                        "submission.deleted", submission_id=submission_id,
                    ),
                    event_type="submission.deleted", actor_id=actor_id,
                    scope_type="session", room_id=room_id, session_id=session_id,
                    entity_type="submission", entity_id=submission_id,
                    metadata={"kind": str(submission["kind"])},
                )

    def list_current(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
    ) -> list[SubmissionMetadataView]:
        """List current revision metadata after a membership-first session read."""

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT submission.id, submission.session_id, submission.author_id,
                       submission.kind, submission.title, submission.created_at,
                       revision.id AS current_revision_id,
                       revision.processing_state, revision.filename,
                       revision.mime_type, revision.byte_size,
                       author.email AS author_email,
                       author.display_name AS author_display_name
                FROM room_memberships AS membership
                JOIN talk_sessions AS session_row
                  ON session_row.room_id = membership.room_id
                 AND session_row.id = %s
                LEFT JOIN submissions AS submission
                  ON submission.session_id = session_row.id
                 AND submission.deleted_at IS NULL
                LEFT JOIN source_revisions AS revision
                  ON revision.submission_id = submission.id
                 AND revision.is_current
                LEFT JOIN users AS author ON author.id = submission.author_id
                WHERE membership.user_id = %s
                  AND membership.left_at IS NULL
                ORDER BY submission.created_at, submission.id
                """,
                (session_id, actor_id),
            )
            rows = cursor.fetchall()
        if not rows:
            raise TextSubmissionAccessError("talk session is unavailable")
        return [
            _submission_metadata_from_row(row)
            for row in rows
            if row["id"] is not None
        ]

    def get_viewer(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        actor_id: UUID,
        revision_id: UUID,
        anchor_id: UUID | None = None,
    ) -> TextViewerView:
        """Load a text revision/optional anchor only after membership joins it."""

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT revision.id, revision.submission_id, revision.filename,
                       revision.mime_type, revision.byte_size, revision.processing_state,
                       revision.source_text
                FROM source_revisions AS revision
                JOIN submissions AS submission ON submission.id = revision.submission_id
                JOIN talk_sessions AS session_row ON session_row.id = submission.session_id
                JOIN room_memberships AS membership
                  ON membership.room_id = session_row.room_id
                 AND membership.user_id = %s
                 AND membership.left_at IS NULL
                WHERE revision.id = %s
                """,
                (actor_id, revision_id),
            )
            revision_row = cursor.fetchone()
            if revision_row is None:
                raise TextSubmissionAccessError("source revision is unavailable")
            revision = _revision_from_row(revision_row)
            if revision.mime_type != "text/plain":
                raise TextViewerUnavailableError("text viewer only supports text/plain")
            highlighted_anchor: TextAnchorView | None = None
            if anchor_id is not None:
                cursor.execute(
                    """
                    SELECT id, source_revision_id, anchor_json, text
                    FROM source_anchors
                    WHERE id = %s AND source_revision_id = %s
                    """,
                    (anchor_id, revision_id),
                )
                anchor_row = cursor.fetchone()
                if anchor_row is None:
                    raise TextViewerUnavailableError("source anchor is unavailable")
                highlighted_anchor = _anchor_from_row(anchor_row)
        return TextViewerView(revision=revision, highlighted_anchor=highlighted_anchor)


def _insert_ready_text_revision(
    cursor: psycopg.Cursor[dict[str, Any]],
    *,
    submission_id: UUID,
    revision_no: int,
    text: str,
) -> UUID:
    """Write revision, extraction run, anchors, and approved-ready link atomically."""

    revision_id = uuid4()
    extraction_run_id = uuid4()
    source_bytes = text.encode("utf-8")
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    filename = f"text-submission-{submission_id}.txt"
    cursor.execute(
        """
        INSERT INTO source_revisions (
            id, submission_id, revision_no, filename, mime_type, byte_size,
            sha256, source_text, processing_state, is_current
        ) VALUES (%s, %s, %s, %s, 'text/plain', %s, %s, %s, 'queued', TRUE)
        """,
        (
            revision_id,
            submission_id,
            revision_no,
            filename,
            len(source_bytes),
            source_sha256,
            text,
        ),
    )
    cursor.execute(
        """
        INSERT INTO extraction_runs (
            id, source_revision_id, parser_name, parser_version, newline_policy,
            unicode_normalization_profile, config_hash, anchor_schema_version,
            attempt_no, status, completed_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, 'succeeded', clock_timestamp())
        """,
        (
            extraction_run_id,
            revision_id,
            INLINE_TEXT_PARSER_NAME,
            INLINE_TEXT_PARSER_VERSION,
            INLINE_TEXT_NEWLINE_POLICY,
            INLINE_TEXT_UNICODE_NORMALIZATION,
            INLINE_TEXT_EXTRACTION_PROFILE_HASH,
            ANCHOR_SCHEMA_VERSION,
        ),
    )
    ordinal = 0
    for line_number, line in enumerate(text.split("\n"), start=1):
        if not line:
            continue
        payload = text_line_anchor_payload(
            source_sha256=source_sha256,
            line=line_number,
            exact_quote=line,
        )
        cursor.execute(
            """
            INSERT INTO source_anchors (
                id, extraction_run_id, source_revision_id, ordinal, block_type,
                text, anchor_json, canonical_hash
            ) VALUES (%s, %s, %s, %s, 'text_line', %s, %s, %s)
            """,
            (
                uuid4(),
                extraction_run_id,
                revision_id,
                ordinal,
                line,
                Jsonb(payload),
                canonical_sha256(payload),
            ),
        )
        ordinal += 1
    if ordinal == 0:  # guarded by input validation, retained as a DB invariant.
        raise TextSubmissionError("text submission needs at least one non-empty line")
    cursor.execute(
        """
        UPDATE source_revisions
        SET approved_extraction_run_id = %s,
            processing_state = 'ready'
        WHERE id = %s AND processing_state = 'queued'
        """,
        (extraction_run_id, revision_id),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("inline text revision could not become ready")
    return revision_id


def _require_open_member_session(
    cursor: psycopg.Cursor[dict[str, Any]],
    session_id: UUID,
    actor_id: UUID,
) -> UUID:
    cursor.execute(
        """
        SELECT session_row.state, session_row.room_id
        FROM talk_sessions AS session_row
        JOIN room_memberships AS membership
          ON membership.room_id = session_row.room_id
         AND membership.user_id = %s
         AND membership.left_at IS NULL
        WHERE session_row.id = %s
        FOR UPDATE OF session_row
        """,
        (actor_id, session_id),
    )
    row = cursor.fetchone()
    if row is None:
        raise TextSubmissionAccessError("talk session is unavailable")
    if _session_state(row["state"]) != "open":
        raise TextSubmissionStateError("talk session must be open")
    return _uuid(row["room_id"], "session room id")


def _locked_member_submission(
    cursor: psycopg.Cursor[dict[str, Any]],
    submission_id: UUID,
    actor_id: UUID,
) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT submission.id, submission.session_id, submission.author_id,
               session_row.room_id,
               submission.kind, submission.title, submission.deleted_at,
               session_row.state AS session_state
        FROM submissions AS submission
        JOIN talk_sessions AS session_row ON session_row.id = submission.session_id
        JOIN room_memberships AS membership
          ON membership.room_id = session_row.room_id
         AND membership.user_id = %s
         AND membership.left_at IS NULL
        WHERE submission.id = %s
        FOR UPDATE OF session_row, submission
        """,
        (actor_id, submission_id),
    )
    return cursor.fetchone()


def _current_revision_count(
    cursor: psycopg.Cursor[dict[str, Any]],
    session_id: UUID,
) -> int:
    cursor.execute(
        """
        SELECT count(*) AS current_revision_count
        FROM source_revisions AS revision
        JOIN submissions AS submission ON submission.id = revision.submission_id
        WHERE submission.session_id = %s AND revision.is_current
        """,
        (session_id,),
    )
    row = _require_row(cursor.fetchone(), "current revision count")
    count = row["current_revision_count"]
    if isinstance(count, bool) or not isinstance(count, int):
        raise RuntimeError("current revision count must be integer")
    return count


def _validated_normalized_text(value: str) -> str:
    if not isinstance(value, str):
        raise TextSubmissionError("text submission must be text")
    if not 1 <= len(value) <= MAX_TEXT_CHARACTERS:
        raise TextSubmissionError("text submission length is invalid")
    if "\x00" in value:
        raise TextSubmissionError("text submission must not contain NUL")
    normalized = normalize_text(value)
    if not normalized.strip():
        raise TextSubmissionError("text submission must contain visible text")
    try:
        encoded = normalized.encode("utf-8")
    except UnicodeEncodeError as error:
        raise TextSubmissionError("text submission must be valid UTF-8 text") from error
    if len(encoded) > 20 * 1024 * 1024:
        raise TextSubmissionError("text submission is too large")
    return normalized


def _revision_from_row(row: dict[str, Any]) -> SourceRevisionView:
    source_text = row["source_text"]
    if not isinstance(source_text, str):
        raise TextViewerUnavailableError("text source is unavailable")
    byte_size = row["byte_size"]
    if isinstance(byte_size, bool) or not isinstance(byte_size, int):
        raise RuntimeError("persisted source byte size must be integer")
    return SourceRevisionView(
        id=_uuid(row["id"], "source revision id"),
        submission_id=_uuid(row["submission_id"], "submission id"),
        filename=_text(row["filename"], "source filename"),
        mime_type=_text(row["mime_type"], "source MIME type"),
        byte_size=byte_size,
        processing_state=_processing_state(row["processing_state"]),
        source_text=source_text,
    )


def _submission_metadata_from_row(row: dict[str, Any]) -> SubmissionMetadataView:
    byte_size = row["byte_size"]
    if isinstance(byte_size, bool) or not isinstance(byte_size, int):
        raise RuntimeError("persisted source byte size must be integer")
    return SubmissionMetadataView(
        id=_uuid(row["id"], "submission id"),
        session_id=_uuid(row["session_id"], "submission session id"),
        author_id=_uuid(row["author_id"], "submission author id"),
        kind=_submission_kind(row["kind"]),
        title=_text(row["title"], "submission title"),
        current_revision_id=_uuid(row["current_revision_id"], "current revision id"),
        processing_state=_processing_state(row["processing_state"]),
        filename=_text(row["filename"], "source filename"),
        mime_type=_text(row["mime_type"], "source MIME type"),
        byte_size=byte_size,
        author=UserRecord(
            id=_uuid(row["author_id"], "submission author id"),
            email=_text(row["author_email"], "submission author email"),
            display_name=_text(
                row["author_display_name"], "submission author display name"
            ),
        ),
        created_at=_datetime(row["created_at"], "submission created_at"),
    )


def _anchor_from_row(row: dict[str, Any]) -> TextAnchorView:
    payload = row["anchor_json"]
    if not isinstance(payload, dict):
        raise RuntimeError("persisted text anchor payload must be an object")
    return TextAnchorView(
        id=_uuid(row["id"], "source anchor id"),
        revision_id=_uuid(row["source_revision_id"], "source anchor revision id"),
        canonical_payload=dict(payload),
        exact_quote=_text(row["text"], "source anchor quote"),
    )


def _require_row(row: dict[str, Any] | None, label: str) -> dict[str, Any]:
    if row is None:
        raise RuntimeError(f"{label} was not returned")
    return row


def _uuid(value: object, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise RuntimeError(f"persisted {label} must be UUID")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"persisted {label} must be non-empty text")
    return value


def _datetime(value: object, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError(f"persisted {label} must be datetime")
    return value


def _validated_title(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > MAX_SUBMISSION_TITLE_CHARACTERS:
        raise TextSubmissionError("submission title must contain 1 to 500 characters")
    return normalized


def _session_state(
    value: object,
) -> Literal["draft", "open", "closed", "processing", "ready", "needs_attention"]:
    if value in {"draft", "open", "closed", "processing", "ready", "needs_attention"}:
        return value
    raise RuntimeError("persisted session state is invalid")


def _processing_state(
    value: object,
) -> Literal["uploaded", "queued", "extracting", "ready", "failed"]:
    if value in {"uploaded", "queued", "extracting", "ready", "failed"}:
        return value
    raise RuntimeError("persisted source processing state is invalid")


def _submission_kind(value: object) -> Literal["text", "file"]:
    if value in {"text", "file"}:
        return value
    raise RuntimeError("persisted submission kind is invalid")
