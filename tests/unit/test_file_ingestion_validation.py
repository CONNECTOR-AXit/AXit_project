"""Regression contracts for document upload validation.

These tests intentionally exercise the same G0 media inspection policy that the
durable upload service must call before it writes an original blob or database
row.  Keeping validation pure makes the byte boundary and spoofing behavior
cheap to test without a parser process.
"""

from __future__ import annotations

import sys
import io
import hashlib
import json
import os
import zipfile
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest


INGESTION_ROOT = Path(__file__).resolve().parents[2] / "spikes" / "document-ingestion" / "src"
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))

from axit_ingestion_spike.media import inspect_input  # noqa: E402
from axit_ingestion_spike.models import (  # noqa: E402
    ErrorCode,
    ExtractionException,
    ExtractionPolicy,
    MediaType,
)


def _docx_bytes(document_xml: bytes) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("word/document.xml", document_xml)
    return target.getvalue()


MAX_UPLOAD_BYTES = 200 * 1024 * 1024


def test_host_profile_pins_match_recaptured_g0_browser_fixtures() -> None:
    """A policy change must not leave the host rejecting valid G0 output."""

    from app.file_extraction_worker import _PROFILE_BY_MEDIA

    fixture_root = (
        Path(__file__).resolve().parents[2]
        / "spikes"
        / "document-ingestion"
        / "viewer"
        / "fixtures"
    )
    fixture_by_media = {
        "application/pdf": "pdf-text-korean.json",
        "image/png": "image-korean-clean-png.json",
        "image/jpeg": "image-korean-clean-jpeg.json",
        "application/x-hwp": "hwp-simple.json",
        "application/x-hwpx": "hwpx-simple.json",
    }

    captured = {
        media_type: json.loads((fixture_root / filename).read_text(encoding="utf-8"))[
            "result"
        ]["config_profile_hash"]
        for media_type, filename in fixture_by_media.items()
    }

    assert {
        media_type: _PROFILE_BY_MEDIA[media_type] for media_type in fixture_by_media
    } == captured


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    (
        ("agenda.pdf", b"%PDF-1.7\nfixture", MediaType.PDF),
        ("scan.jpg", b"\xff\xd8\xfffixture\xff\xd9", MediaType.JPEG),
        (
            "scan.png",
            b"\x89PNG\r\n\x1a\nfixture\x00\x00\x00\x00IEND\xaeB`\x82",
            MediaType.PNG,
        ),
        ("minutes.hwp", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1fixture", MediaType.HWP),
        ("minutes.hwpx", b"PK\x03\x04fixture", MediaType.HWPX),
        ("slides.pptx", b"PK\x03\x04fixture", MediaType.PPTX),
        ("workbook.xlsx", b"PK\x03\x04fixture", MediaType.XLSX),
    ),
)
def test_supported_extension_and_magic_pair_is_accepted(
    filename: str,
    content: bytes,
    expected: MediaType,
) -> None:
    inspected = inspect_input(content, filename, ExtractionPolicy())

    assert inspected.media_type is expected


@pytest.mark.parametrize("filename", ("사람1_RAG_img.jpg", "사람1_RAG_img.jpeg"))
def test_jpeg_labelled_png_is_canonicalized_to_the_png_parser(filename: str) -> None:
    from app.file_submission_service import _declared_file_type, _effective_file_type

    content = b"\x89PNG\r\n\x1a\nfixture"
    declared = _declared_file_type(filename, "image/jpeg")

    effective = _effective_file_type(declared, content)

    assert effective.extension == ".png"
    assert effective.media_type == "image/png"
    assert effective.parser.name == "pillow+tesseract-cli"


def test_docx_zip_is_disambiguated_from_hwpx_by_extension() -> None:
    inspected = inspect_input(_docx_bytes(b"<document/>"), "agenda.docx", ExtractionPolicy())
    assert inspected.media_type is MediaType.DOCX


@pytest.mark.parametrize(
    ("filename", "mime_type", "parser_name"),
    (
        (
            "slides.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "libreoffice+pypdfium2+tesseract-cli",
        ),
        (
            "slides.pptx",
            "application/haansoftpptx",
            "libreoffice+pypdfium2+tesseract-cli",
        ),
        (
            "workbook.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "stdlib-xlsx",
        ),
        (
            "workbook.xlsx",
            "application/haansoftxlsx",
            "stdlib-xlsx",
        ),
    ),
)
def test_office_upload_types_are_pinned_to_sandbox_parsers(
    filename: str, mime_type: str, parser_name: str
) -> None:
    from app.file_submission_service import _declared_file_type, _require_magic

    file_type = _declared_file_type(filename, mime_type)
    assert file_type.parser.name == parser_name
    _require_magic(file_type, b"PK\x03\x04package")


def test_docx_extracts_paragraph_table_and_toc_anchors() -> None:
    from axit_ingestion_spike.pipeline import extract_document

    xml = b'''<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
      <w:p><w:pPr><w:pStyle w:val="TOC1"/></w:pPr><w:r><w:t>1. Agenda</w:t></w:r></w:p>
      <w:p><w:r><w:t>Decision paragraph</w:t></w:r></w:p>
      <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Owner: Alice</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
    </w:body></w:document>'''
    envelope = extract_document(_docx_bytes(xml), filename="agenda.docx")

    assert envelope.ok is True
    assert envelope.result is not None
    assert [block.block_type for block in envelope.result.blocks] == [
        "toc_entry", "docx_paragraph", "table_cell"
    ]
    assert [block.anchor.to_dict()["kind"] for block in envelope.result.blocks] == [
        "docx_paragraph", "docx_paragraph", "docx_paragraph"
    ]


def test_docx_rejects_dtd_before_xml_parsing() -> None:
    from axit_ingestion_spike.pipeline import extract_document

    envelope = extract_document(
        _docx_bytes(b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x/>'),
        filename="malicious.docx",
    )
    assert envelope.ok is False
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.XML_DTD_FORBIDDEN


def test_exactly_two_hundred_mebibytes_is_accepted() -> None:
    content = b"%PDF-" + (b"x" * (MAX_UPLOAD_BYTES - len(b"%PDF-")))

    inspected = inspect_input(content, "limit.pdf", ExtractionPolicy())

    assert inspected.media_type is MediaType.PDF


def test_two_hundred_mebibytes_plus_one_is_rejected() -> None:
    content = b"%PDF-" + (b"x" * (MAX_UPLOAD_BYTES + 1 - len(b"%PDF-")))

    with pytest.raises(ExtractionException) as raised:
        inspect_input(content, "too-large.pdf", ExtractionPolicy())

    assert raised.value.error.code is ErrorCode.INPUT_TOO_LARGE


class _ReadForbiddenStream(BytesIO):
    def read(self, size: int = -1) -> bytes:
        raise AssertionError(f"oversized stream must be rejected before reading (size={size})")


def test_declared_oversize_stream_is_rejected_before_it_is_read(tmp_path: Path) -> None:
    from app.file_submission_service import (
        FileSubmissionLimitError,
        FileSubmissionService,
        LocalBlobStore,
    )

    service = FileSubmissionService(blob_store=LocalBlobStore(tmp_path))
    with pytest.raises(FileSubmissionLimitError):
        service.submit(
            object(),  # the content-length gate must precede all database access
            session_id=object(),
            actor_id=object(),
            filename="too-large.pdf",
            declared_mime_type="application/pdf",
            stream=_ReadForbiddenStream(),
            content_length=MAX_UPLOAD_BYTES + 1,
        )


def test_extension_magic_mismatch_is_rejected() -> None:
    with pytest.raises(ExtractionException) as raised:
        inspect_input(b"%PDF-1.7\nfixture", "disguised.png", ExtractionPolicy())

    assert raised.value.error.code is ErrorCode.TYPE_MISMATCH


def test_upload_magic_mismatch_leaves_no_staged_blob(tmp_path: Path) -> None:
    from app.file_submission_service import (
        FileSubmissionService,
        FileSubmissionValidationError,
        LocalBlobStore,
    )

    content = b"%PDF-1.7\nnot really an image"
    service = FileSubmissionService(blob_store=LocalBlobStore(tmp_path))
    with pytest.raises(FileSubmissionValidationError):
        service.submit(
            object(),  # magic validation must precede all database access
            session_id=object(),
            actor_id=object(),
            filename="disguised.png",
            declared_mime_type="image/png",
            stream=BytesIO(content),
            content_length=len(content),
        )

    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_plain_text_upload_accepts_utf8_without_binary_nul(tmp_path: Path) -> None:
    from app.file_submission_service import _declared_file_type, _require_magic

    file_type = _declared_file_type("회의록.txt", "text/plain")

    assert file_type.media_type == "text/plain"
    assert file_type.parser.name == "builtin-utf8-text"
    _require_magic(file_type, "안건 1\n결정 사항".encode("utf-8")[:16])


def test_plain_text_upload_rejects_binary_nul_prefix() -> None:
    from app.file_submission_service import (
        FileSubmissionValidationError,
        _declared_file_type,
        _require_magic,
    )

    file_type = _declared_file_type("disguised.txt", "application/octet-stream")
    with pytest.raises(FileSubmissionValidationError):
        _require_magic(file_type, b"not-text\x00binary")


@pytest.mark.parametrize(
    "filename",
    ("../agenda.pdf", "folder/agenda.pdf", "folder\\agenda.pdf", "/absolute/agenda.pdf"),
)
def test_upload_filename_with_path_components_is_rejected_before_storage(
    filename: str,
    tmp_path: Path,
) -> None:
    from app.file_submission_service import (
        FileSubmissionService,
        FileSubmissionValidationError,
        LocalBlobStore,
    )

    service = FileSubmissionService(blob_store=LocalBlobStore(tmp_path))
    with pytest.raises(FileSubmissionValidationError):
        service.submit(
            object(),  # basename validation must precede all database access
            session_id=object(),
            actor_id=object(),
            filename=filename,
            declared_mime_type="application/pdf",
            stream=BytesIO(b"%PDF-1.7\nfixture"),
            content_length=len(b"%PDF-1.7\nfixture"),
        )

    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_blob_commit_fsyncs_replaced_file_then_parent_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.file_submission_service import LocalBlobStore

    store = LocalBlobStore(tmp_path)
    temporary = store.temporary_path()
    temporary.write_bytes(b"durable original")
    events: list[tuple[str, object]] = []
    real_replace = os.replace
    descriptors: dict[int, Path] = {}

    def tracked_replace(source: Path, destination: Path) -> None:
        events.append(("replace", destination))
        real_replace(source, destination)

    def tracked_open(path: object, flags: int) -> int:
        opened_path = Path(path)  # type: ignore[arg-type]
        descriptor = 100 + len(descriptors)
        descriptors[descriptor] = opened_path
        events.append(("open", opened_path))
        return descriptor

    def tracked_fsync(descriptor: int) -> None:
        events.append(("fsync", descriptors[descriptor]))

    def tracked_close(descriptor: int) -> None:
        events.append(("close", descriptors[descriptor]))
        descriptors.pop(descriptor, None)

    monkeypatch.setattr(os, "replace", tracked_replace)
    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "fsync", tracked_fsync)
    monkeypatch.setattr(os, "close", tracked_close)

    key = store.commit(temporary, revision_id=uuid4())
    destination = store.path_for(key)

    assert events == [
        ("replace", destination),
        ("open", destination),
        ("fsync", destination),
        ("close", destination),
        ("open", tmp_path.resolve()),
        ("fsync", tmp_path.resolve()),
        ("close", tmp_path.resolve()),
    ]


class _AuthorizationCursor:
    def __init__(self, connection: "_AuthorizationConnection") -> None:
        self.connection = connection

    def __enter__(self) -> "_AuthorizationCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, parameters: object) -> None:
        self.connection.queries.append(query)

    def fetchone(self) -> dict[str, int] | None:
        self.connection.checks += 1
        return {"authorized": 1} if self.connection.checks == 1 else None


class _AuthorizationConnection:
    def __init__(self) -> None:
        self.checks = 0
        self.commits = 0
        self.queries: list[str] = []

    def cursor(self) -> _AuthorizationCursor:
        return _AuthorizationCursor(self)

    def commit(self) -> None:
        self.commits += 1


def test_original_stream_rechecks_current_membership_before_every_chunk(
    tmp_path: Path,
) -> None:
    from app.file_submission_service import (
        READ_CHUNK_BYTES,
        FileSubmissionAccessError,
        FileSubmissionService,
        LocalBlobStore,
        OriginalDownload,
    )

    content = b"x" * (READ_CHUNK_BYTES + 1)
    store = LocalBlobStore(tmp_path)
    storage_key = f"{uuid4().hex}.blob"
    store.path_for(storage_key).write_bytes(content)
    download = OriginalDownload(
        filename="large.pdf",
        mime_type="application/pdf",
        byte_size=len(content),
        _blob_store=store,
        _storage_key=storage_key,
        _sha256=hashlib.sha256(content).hexdigest(),
    )
    connection = _AuthorizationConnection()
    chunks = FileSubmissionService(blob_store=store).stream_original(
        connection,  # type: ignore[arg-type]
        download=download,
        revision_id=uuid4(),
        actor_id=uuid4(),
    )

    assert next(chunks) == content[:READ_CHUNK_BYTES]
    with pytest.raises(FileSubmissionAccessError):
        next(chunks)

    assert connection.checks == 2
    assert connection.commits == 1
    assert all("membership.left_at IS NULL" in query for query in connection.queries)
