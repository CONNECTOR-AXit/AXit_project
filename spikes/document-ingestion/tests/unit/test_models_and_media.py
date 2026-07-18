from __future__ import annotations

import json

import pytest

from axit_ingestion_spike.anchors import BBox, PdfBlockAnchor
from axit_ingestion_spike.media import MediaType, inspect_input
from axit_ingestion_spike.models import (
    ErrorCode,
    ExtractedBlock,
    ExtractionEnvelope,
    ExtractionError,
    ExtractionException,
    ExtractionPolicy,
    ExtractionResult,
)


def _result(*, text: str = "회의 안건") -> ExtractionResult:
    block = ExtractedBlock(
        ordinal=0,
        text=text,
        block_type="pdf_text",
        confidence=None,
        anchor=PdfBlockAnchor.from_text(
            source_sha256="a" * 64,
            extraction_profile_hash="b" * 64,
            page=0,
            block_id="text-0000",
            bbox=BBox(0, 0, 1, 1),
            text=text,
        ),
    )
    return ExtractionResult(
        source_sha256="a" * 64,
        media_type=MediaType.PDF,
        parser_name="pypdfium2",
        parser_version="5.11.0",
        normalization_profile="nfc-lf-v1",
        config_profile_hash="b" * 64,
        blocks=(block,),
    )


def test_success_envelope_serializes_result_and_anchor_hash() -> None:
    envelope = ExtractionEnvelope.success(_result())
    payload = json.loads(envelope.to_json(max_bytes=4096))

    assert payload["ok"] is True
    assert payload["result"]["blocks"][0]["anchor_hash"]
    assert len(payload["result"]["anchor_set_hash"]) == 64
    assert payload["result"]["blocks"][0]["anchor"]["kind"] == "pdf_block"
    assert "error" not in payload


def test_failure_envelope_is_typed_and_bounds_safe_message() -> None:
    envelope = ExtractionEnvelope.failure(
        ExtractionError(
            code=ErrorCode.INPUT_TOO_LARGE,
            message="input exceeds configured byte limit",
            retryable=False,
        )
    )
    payload = envelope.to_dict()

    assert payload == {
        "schema_version": 1,
        "ok": False,
        "error": {
            "code": "INPUT_TOO_LARGE",
            "message": "input exceeds configured byte limit",
            "retryable": False,
        },
    }
    with pytest.raises(ValueError, match="512"):
        ExtractionError(ErrorCode.INTERNAL_ERROR, "x" * 513)


def test_envelope_refuses_to_exceed_stdout_bound() -> None:
    with pytest.raises(ExtractionException) as caught:
        ExtractionEnvelope.success(_result(text="가" * 200)).to_json(max_bytes=64)

    assert caught.value.error.code is ErrorCode.OUTPUT_TOO_LARGE


def test_policy_and_result_enforce_block_and_character_bounds() -> None:
    with pytest.raises(ValueError, match="max_input_bytes"):
        ExtractionPolicy(max_input_bytes=0)
    with pytest.raises(ExtractionException) as caught:
        _result(text="가" * 5).validate_bounds(
            ExtractionPolicy(max_block_chars=4, max_total_chars=4)
        )
    assert caught.value.error.code is ErrorCode.OUTPUT_TOO_LARGE


def test_result_rejects_foreign_anchor_identity() -> None:
    anchor = PdfBlockAnchor.from_text(
        source_sha256="c" * 64,
        extraction_profile_hash="b" * 64,
        page=0,
        block_id="text-0000",
        bbox=BBox(0, 0, 1, 1),
        text="회의 안건",
    )
    block = ExtractedBlock(0, "회의 안건", "pdf_text", None, anchor)
    with pytest.raises(ValueError, match="different source"):
        ExtractionResult(
            source_sha256="a" * 64,
            media_type=MediaType.PDF,
            parser_name="pypdfium2",
            parser_version="5.11.0",
            normalization_profile="nfc-lf-v1",
            config_profile_hash="b" * 64,
            blocks=(block,),
        )


@pytest.mark.parametrize(
    ("data", "filename", "expected"),
    [
        (b"%PDF-1.7\n", "brief.pdf", MediaType.PDF),
        (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00IEND\xaeB`\x82",
            "scan.png",
            MediaType.PNG,
        ),
        (b"\xff\xd8\xff\xe0rest\xff\xd9", "photo.jpeg", MediaType.JPEG),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest", "legacy.hwp", MediaType.HWP),
        (b"PK\x03\x04rest", "package.hwpx", MediaType.HWPX),
    ],
)
def test_inspect_input_uses_magic_and_extension(
    data: bytes, filename: str, expected: MediaType
) -> None:
    assert inspect_input(data, filename, ExtractionPolicy()).media_type is expected


def test_inspect_input_rejects_spoofed_extension_unknown_and_oversize() -> None:
    with pytest.raises(ExtractionException) as mismatch:
        inspect_input(b"%PDF-1.7\n", "photo.png", ExtractionPolicy())
    assert mismatch.value.error.code is ErrorCode.TYPE_MISMATCH

    with pytest.raises(ExtractionException) as unsupported:
        inspect_input(b"plain text", "notes.txt", ExtractionPolicy())
    assert unsupported.value.error.code is ErrorCode.UNSUPPORTED_MEDIA_TYPE

    with pytest.raises(ExtractionException) as oversized:
        inspect_input(
            b"%PDF-1.7" + b"x" * 10, "brief.pdf", ExtractionPolicy(max_input_bytes=10)
        )
    assert oversized.value.error.code is ErrorCode.INPUT_TOO_LARGE


def test_image_containers_reject_trailing_polyglot_or_missing_end_markers() -> None:
    policy = ExtractionPolicy()
    valid_png_shell = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00IEND\xaeB`\x82"
    valid_jpeg_shell = b"\xff\xd8\xff\xe0stub\xff\xd9"

    assert inspect_input(valid_png_shell, "clean.png", policy).media_type is MediaType.PNG
    assert inspect_input(valid_jpeg_shell, "clean.jpg", policy).media_type is MediaType.JPEG

    for payload, filename in (
        (valid_png_shell + b"PK\x03\x04", "polyglot.png"),
        (valid_jpeg_shell + b"PK\x03\x04", "polyglot.jpg"),
        (b"\x89PNG\r\n\x1a\ntruncated", "truncated.png"),
        (b"\xff\xd8\xfftruncated", "truncated.jpg"),
    ):
        with pytest.raises(ExtractionException) as failure:
            inspect_input(payload, filename, policy)
        assert failure.value.error.code is ErrorCode.CORRUPT_DOCUMENT
