from __future__ import annotations

import json
import math

import pytest

from axit_ingestion_spike.anchors import (
    BBox,
    HwpParagraphAnchor,
    ImageBBoxAnchor,
    PdfBlockAnchor,
    TextLineAnchor,
    canonical_anchor_set_hash,
)
from axit_ingestion_spike.normalization import (
    canonical_json,
    config_profile_hash,
    normalize_text,
    text_fingerprint,
)


SOURCE_HASH = "a" * 64
PROFILE_HASH = "b" * 64


def test_text_normalization_is_nfc_and_lf_without_trimming_content() -> None:
    assert normalize_text(" A\r\n한글\rB ") == " A\n한글\nB "
    assert text_fingerprint("한글\r\n") == text_fingerprint("한글\n")


def test_canonical_json_sorts_keys_and_normalizes_finite_numbers() -> None:
    left = {"z": -0.0, "bbox": [0.12345674, 1.0, 0.5, 0.99999999], "a": 1}
    right = {"a": 1, "bbox": [0.1234567, 1, 0.50000001, 1.0], "z": 0}

    assert canonical_json(left) == canonical_json(right)
    assert canonical_json(left) == '{"a":1,"bbox":[0.123457,1,0.5,1],"z":0}'
    assert config_profile_hash(left) == config_profile_hash(right)
    assert json.loads(canonical_json(left))["bbox"][0] == 0.123457


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_canonical_json_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        canonical_json({"value": value})


def test_bbox_is_top_left_normalized_and_has_positive_area() -> None:
    assert BBox(0.0, 0.25, 1.0, 0.75).to_list() == [0, 0.25, 1, 0.75]

    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        BBox(-0.1, 0.0, 1.0, 1.0)
    with pytest.raises(ValueError, match="positive area"):
        BBox(0.5, 0.0, 0.5, 1.0)


def test_text_line_anchor_uses_one_based_line_and_code_point_offsets() -> None:
    anchor = TextLineAnchor.from_line(
        source_sha256=SOURCE_HASH,
        extraction_profile_hash=PROFILE_HASH,
        line=2,
        start=1,
        end=3,
        source_line="가나다라",
    )

    assert anchor.to_dict() == {
        "schema_version": 1,
        "kind": "text_line",
        "source_sha256": SOURCE_HASH,
        "extraction_profile_hash": PROFILE_HASH,
        "locator": {"line": 2, "start": 1, "end": 3},
        "text_fingerprint": text_fingerprint("나다"),
    }
    assert len(anchor.anchor_hash) == 64
    with pytest.raises(ValueError, match="1-based"):
        TextLineAnchor.from_line(
            source_sha256=SOURCE_HASH,
            extraction_profile_hash=PROFILE_HASH,
            line=0,
            start=0,
            end=1,
            source_line="가",
        )
    with pytest.raises(ValueError, match="code-point"):
        TextLineAnchor.from_line(
            source_sha256=SOURCE_HASH,
            extraction_profile_hash=PROFILE_HASH,
            line=1,
            start=0,
            end=2,
            source_line="가",
        )


def test_required_anchor_kinds_have_stable_versioned_payloads() -> None:
    bbox = BBox(0.1, 0.2, 0.9, 0.8)
    pdf = PdfBlockAnchor.from_text(
        source_sha256=SOURCE_HASH,
        extraction_profile_hash=PROFILE_HASH,
        page=0,
        block_id="text-0000",
        bbox=bbox,
        text="안건",
    )
    image = ImageBBoxAnchor.from_ocr(
        source_sha256=SOURCE_HASH,
        extraction_profile_hash=PROFILE_HASH,
        image_id="image-0000",
        bbox=bbox,
        text="의견",
    )
    hwp = HwpParagraphAnchor.from_text(
        source_sha256=SOURCE_HASH,
        extraction_profile_hash=PROFILE_HASH,
        parser="hwplib",
        parser_version="1.1.10",
        section=0,
        paragraph=2,
        table=0,
        table_block=0,
        table_row=1,
        cell=3,
        cell_paragraph=0,
        text="표 셀",
    )

    assert pdf.to_dict()["locator"] == {
        "page": 0,
        "block_id": "text-0000",
        "bbox": [0.1, 0.2, 0.9, 0.8],
    }
    assert "ocr_text" not in image.to_dict()
    assert "confidence" not in image.to_dict()
    hwp_locator = hwp.to_dict()["locator"]
    assert isinstance(hwp_locator, dict)
    assert hwp_locator["parser_version"] == "1.1.10"
    assert hwp_locator["table"] == {
        "index": 0,
        "block": 0,
        "row": 1,
        "cell": 3,
        "paragraph": 0,
    }
    assert (
        pdf.anchor_hash
        == PdfBlockAnchor.from_text(
            source_sha256=SOURCE_HASH,
            extraction_profile_hash=PROFILE_HASH,
            page=0,
            block_id="text-0000",
            bbox=BBox(0.10000001, 0.2, 0.9, 0.8),
            text="안건",
        ).anchor_hash
    )
    assert (
        pdf.anchor_hash
        != PdfBlockAnchor.from_text(
            source_sha256="c" * 64,
            extraction_profile_hash=PROFILE_HASH,
            page=0,
            block_id="text-0000",
            bbox=bbox,
            text="안건",
        ).anchor_hash
    )

    footnote = HwpParagraphAnchor.from_text(
        source_sha256=SOURCE_HASH,
        extraction_profile_hash=PROFILE_HASH,
        parser="hwplib",
        parser_version="1.1.10",
        section=0,
        paragraph=5,
        footnote=0,
        footnote_paragraph=1,
        text="각주",
    )
    footnote_locator = footnote.to_dict()["locator"]
    assert isinstance(footnote_locator, dict)
    assert footnote_locator["footnote"] == {"index": 0, "paragraph": 1}


def test_hwp_anchor_rejects_invented_partial_table_paths() -> None:
    with pytest.raises(ValueError, match="complete HWP table"):
        HwpParagraphAnchor.from_text(
            source_sha256=SOURCE_HASH,
            extraction_profile_hash=PROFILE_HASH,
            parser="hwplib",
            parser_version="1.1.10",
            section=0,
            paragraph=0,
            table=0,
            text="불완전 경로",
        )


def test_anchor_set_hash_preserves_canonical_block_order() -> None:
    first = PdfBlockAnchor.from_text(
        source_sha256=SOURCE_HASH,
        extraction_profile_hash=PROFILE_HASH,
        page=0,
        block_id="first",
        bbox=BBox(0, 0, 1, 0.4),
        text="첫 번째",
    )
    second = PdfBlockAnchor.from_text(
        source_sha256=SOURCE_HASH,
        extraction_profile_hash=PROFILE_HASH,
        page=0,
        block_id="second",
        bbox=BBox(0, 0.6, 1, 1),
        text="두 번째",
    )

    assert canonical_anchor_set_hash((first, second)) != canonical_anchor_set_hash(
        (second, first)
    )


@pytest.mark.parametrize("page", [-1, True])
def test_pdf_page_is_a_non_boolean_zero_based_integer(page: int) -> None:
    with pytest.raises(ValueError, match="zero-based"):
        PdfBlockAnchor.from_text(
            source_sha256=SOURCE_HASH,
            extraction_profile_hash=PROFILE_HASH,
            page=page,
            block_id="block",
            bbox=BBox(0, 0, 1, 1),
            text="text",
        )
