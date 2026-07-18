from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "document-ingestion"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.v1.json"

REQUIRED_GOLDEN = {
    "pdf/text-korean.pdf": "pdf_block",
    "pdf/scanned-korean.pdf": "pdf_block",
    "hwp/simple.hwp": "hwp_paragraph",
    "hwp/table-footnote.hwp": "hwp_paragraph",
    "hwpx/simple.hwpx": "hwp_paragraph",
    "hwpx/table-footnote.hwpx": "hwp_paragraph",
    "images/korean-clean.png": "image_bbox",
    "images/korean-clean.jpg": "image_bbox",
    "images/rotated-low-confidence.jpg": "image_bbox",
}

REQUIRED_MALICIOUS = {
    "malicious/corrupt.hwp": "CORRUPT_DOCUMENT",
    "malicious/corrupt.pdf": "CORRUPT_DOCUMENT",
    "malicious/corrupt-image.png": "CORRUPT_DOCUMENT",
    "malicious/encrypted.pdf": "ENCRYPTED_DOCUMENT",
    "malicious/oversized-page.pdf": "IMAGE_PIXEL_LIMIT",
    "malicious/path-traversal.hwpx": "CORRUPT_DOCUMENT",
    "malicious/polyglot-image.jpg": "CORRUPT_DOCUMENT",
    "malicious/zip-bomb.hwpx": "ZIP_EXPANSION_LIMIT",
    "malicious/xxe.hwpx": "XML_DTD_FORBIDDEN",
}


def _load_manifest() -> dict[str, Any]:
    assert MANIFEST_PATH.is_file(), f"missing fixture manifest: {MANIFEST_PATH}"
    parsed = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def test_manifest_is_versioned_project_owned_and_complete() -> None:
    manifest = _load_manifest()
    assert manifest["schema_version"] == 1
    assert manifest["content_license"] == "CC0-1.0"

    fixtures = {entry["path"]: entry for entry in manifest["fixtures"]}
    assert REQUIRED_GOLDEN.keys() <= fixtures.keys()
    assert REQUIRED_MALICIOUS.keys() <= fixtures.keys()

    for relative_path, anchor_kind in REQUIRED_GOLDEN.items():
        entry = fixtures[relative_path]
        assert entry["classification"] == "golden"
        assert entry["expected"]["anchor_kind"] == anchor_kind
        assert entry["expected"]["text_nfc"]
        assert entry["provenance"]["generated_by_repository"] is True
        assert entry["provenance"]["redistributable"] is True

    for relative_path, error_code in REQUIRED_MALICIOUS.items():
        entry = fixtures[relative_path]
        assert entry["classification"] == "malicious"
        assert entry["expected"]["error_code"] == error_code


def test_manifest_hashes_pin_the_exact_fixture_bytes() -> None:
    manifest = _load_manifest()

    for entry in manifest["fixtures"]:
        fixture_path = FIXTURE_ROOT / entry["path"]
        assert fixture_path.is_file(), f"missing fixture: {entry['path']}"
        assert fixture_path.stat().st_size == entry["size_bytes"]
        assert hashlib.sha256(fixture_path.read_bytes()).hexdigest() == entry["sha256"]


def test_manifest_has_blocking_ocr_or_warning_expectations() -> None:
    manifest = _load_manifest()
    fixtures = {entry["path"]: entry for entry in manifest["fixtures"]}

    for relative_path in (
        "pdf/scanned-korean.pdf",
        "images/korean-clean.png",
        "images/korean-clean.jpg",
    ):
        assert fixtures[relative_path]["expected"]["min_ocr_accuracy"] == 0.9

    rotated = fixtures["images/rotated-low-confidence.jpg"]["expected"]
    assert rotated["required_warning"] == "LOW_CONFIDENCE"
    assert "min_ocr_accuracy" not in rotated


def test_hwpx_table_fixture_requires_complete_structural_paths() -> None:
    manifest = _load_manifest()
    expected = {
        entry["path"]: entry["expected"]
        for entry in manifest["fixtures"]
        if entry["classification"] == "golden"
    }["hwpx/table-footnote.hwpx"]

    assert expected["required_block_types"] == [
        "hwp_paragraph",
        "hwp_table_cell",
        "hwp_footnote",
    ]
    assert expected["requires_complete_structural_paths"] is True
