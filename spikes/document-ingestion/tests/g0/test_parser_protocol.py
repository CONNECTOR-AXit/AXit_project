from __future__ import annotations

from copy import deepcopy

import pytest

from axit_ingestion_spike.anchors import BBox, HwpParagraphAnchor, PdfBlockAnchor
from axit_ingestion_spike.models import (
    ErrorCode,
    ExtractedBlock,
    ExtractionEnvelope,
    ExtractionResult,
    MediaType,
    extraction_failure,
)
from axit_ingestion_spike.normalization import NORMALIZATION_PROFILE
from parser_protocol import ProtocolBounds, validate_parser_payload


SOURCE_HASH = "a" * 64
PROFILE_HASH = "b" * 64
BOUNDS = ProtocolBounds(max_blocks=10, max_block_chars=100, max_total_chars=200)


def _success_payload() -> dict[str, object]:
    text = "AXit 회의 사전 브리핑"
    anchor = PdfBlockAnchor.from_text(
        source_sha256=SOURCE_HASH,
        extraction_profile_hash=PROFILE_HASH,
        page=0,
        block_id="text-0000",
        bbox=BBox(0.1, 0.2, 0.9, 0.3),
        text=text,
    )
    result = ExtractionResult(
        source_sha256=SOURCE_HASH,
        media_type=MediaType.PDF,
        parser_name="pypdfium2",
        parser_version="5.12.1",
        normalization_profile=NORMALIZATION_PROFILE,
        config_profile_hash=PROFILE_HASH,
        blocks=(ExtractedBlock(0, text, "pdf_text", None, anchor),),
    )
    return ExtractionEnvelope.success(result).to_dict()  # type: ignore[return-value]


def _hwp_success_payload() -> dict[str, object]:
    text = "HWP 회의 본문"
    anchor = HwpParagraphAnchor.from_text(
        source_sha256=SOURCE_HASH,
        extraction_profile_hash=PROFILE_HASH,
        parser="hwplib",
        parser_version="1.1.10",
        section=0,
        paragraph=0,
        text=text,
    )
    result = ExtractionResult(
        source_sha256=SOURCE_HASH,
        media_type=MediaType.HWP,
        parser_name="hwplib",
        parser_version="1.1.10",
        normalization_profile=NORMALIZATION_PROFILE,
        config_profile_hash=PROFILE_HASH,
        blocks=(ExtractedBlock(0, text, "hwp_paragraph", None, anchor),),
    )
    return ExtractionEnvelope.success(result).to_dict()  # type: ignore[return-value]


def test_host_revalidates_a_complete_success_envelope() -> None:
    validate_parser_payload(
        _success_payload(),
        expected_source_sha256=SOURCE_HASH,
        expected_media_type=MediaType.PDF.value,
        bounds=BOUNDS,
    )


def test_host_revalidates_a_typed_failure_envelope() -> None:
    failure = ExtractionEnvelope.failure(
        extraction_failure(
            ErrorCode.CORRUPT_DOCUMENT,
            "parser rejected corrupt input",
        ).error
    ).to_dict()

    validate_parser_payload(
        failure,
        expected_source_sha256=SOURCE_HASH,
        expected_media_type=MediaType.PDF.value,
        bounds=BOUNDS,
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["result"].update(source_sha256="c" * 64),
        lambda value: value["result"]["blocks"][0].update(ordinal=1),
        lambda value: value["result"]["blocks"][0]["anchor"]["locator"].update(
            bbox=[0.2, 0.2, 1.1, 0.4]
        ),
        lambda value: value["result"]["blocks"][0].update(anchor_hash="d" * 64),
        lambda value: value["result"].update(anchor_set_hash="e" * 64),
        lambda value: value["result"]["blocks"][0].update(text="tampered"),
        lambda value: value["result"].update(untrusted_extra="smuggled"),
    ],
)
def test_host_rejects_tampered_or_out_of_bounds_parser_output(mutate: object) -> None:
    payload = deepcopy(_success_payload())
    mutate(payload)  # type: ignore[operator]

    with pytest.raises(ValueError):
        validate_parser_payload(
            payload,
            expected_source_sha256=SOURCE_HASH,
            expected_media_type=MediaType.PDF.value,
            bounds=BOUNDS,
        )


def test_host_rejects_unknown_error_codes_and_raw_multiline_messages() -> None:
    for error_patch in (
        {"code": "SOMETHING_NEW"},
        {"message": "line one\nraw parser output"},
        {"retryable": "yes"},
    ):
        payload = ExtractionEnvelope.failure(
            extraction_failure(
                ErrorCode.CORRUPT_DOCUMENT,
                "parser rejected corrupt input",
            ).error
        ).to_dict()
        payload["error"].update(error_patch)  # type: ignore[union-attr]

        with pytest.raises(ValueError):
            validate_parser_payload(
                payload,
                expected_source_sha256=SOURCE_HASH,
                expected_media_type=MediaType.PDF.value,
                bounds=BOUNDS,
            )


def test_host_rejects_non_scalar_unicode_without_crashing() -> None:
    payload = _success_payload()
    payload["result"]["blocks"][0]["text"] = "\ud800"  # type: ignore[index]

    with pytest.raises(ValueError, match="Unicode scalar"):
        validate_parser_payload(
            payload,
            expected_source_sha256=SOURCE_HASH,
            expected_media_type=MediaType.PDF.value,
            bounds=BOUNDS,
        )


def test_host_rejects_media_label_and_anchor_kind_confusion() -> None:
    payload = _success_payload()

    with pytest.raises(ValueError, match="media_type"):
        validate_parser_payload(
            payload,
            expected_source_sha256=SOURCE_HASH,
            expected_media_type=MediaType.HWP.value,
            bounds=BOUNDS,
        )

    confused = deepcopy(payload)
    confused["result"]["blocks"][0]["anchor"]["kind"] = "hwp_paragraph"  # type: ignore[index]
    with pytest.raises(ValueError):
        validate_parser_payload(
            confused,
            expected_source_sha256=SOURCE_HASH,
            expected_media_type=MediaType.PDF.value,
            bounds=BOUNDS,
        )


def test_host_rejects_unpinned_parser_identity() -> None:
    payload = _success_payload()
    payload["result"]["parser"] = {"name": "other-pdf", "version": "9"}  # type: ignore[index]

    with pytest.raises(ValueError, match="approved pinned"):
        validate_parser_payload(
            payload,
            expected_source_sha256=SOURCE_HASH,
            expected_media_type=MediaType.PDF.value,
            bounds=BOUNDS,
        )


def test_host_rejects_hwp_locator_parser_different_from_result_parser() -> None:
    payload = _hwp_success_payload()
    payload["result"]["blocks"][0]["anchor"]["locator"]["parser"] = "other"  # type: ignore[index]

    with pytest.raises(ValueError, match="differs"):
        validate_parser_payload(
            payload,
            expected_source_sha256=SOURCE_HASH,
            expected_media_type=MediaType.HWP.value,
            bounds=BOUNDS,
        )
