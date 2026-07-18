from __future__ import annotations

import json
from pathlib import Path


SPIKE_ROOT = Path(__file__).resolve().parents[2]


def test_every_required_parser_ocr_model_font_and_viewer_component_is_pinned() -> None:
    inventory = json.loads(
        (SPIKE_ROOT / "licenses.lock.json").read_text(encoding="utf-8")
    )
    assert inventory["schema_version"] == 1
    assert inventory["engineering_screening_only"] is True
    components = {item["name"]: item for item in inventory["components"]}
    required = {
        "pypdfium2",
        "Pillow",
        "Tesseract OCR",
        "Leptonica",
        "tessdata_best Korean",
        "hwplib",
        "hwpxlib",
        "Eclipse Temurin OpenJDK",
        "Noto Sans KR fixture subset",
        "Playwright Test",
    }
    assert required <= components.keys()

    for name in required:
        item = components[name]
        assert item["version"]
        assert item["spdx"]
        assert item["source_url"].startswith("https://")
        assert item["redistributable"] is True
        assert item["notice"]


def test_content_addressed_model_and_font_hashes_are_exact() -> None:
    inventory = json.loads(
        (SPIKE_ROOT / "licenses.lock.json").read_text(encoding="utf-8")
    )
    components = {item["name"]: item for item in inventory["components"]}

    assert components["tessdata_best Korean"]["sha256"] == (
        "f888d4038348a0c3d25151e7f452bda0d74ca275b18cab146798bcbb94084fff"
    )
    assert components["Noto Sans KR fixture subset"]["sha256"] == (
        "a2c4986eabb2296fe733b90c4a6c8911c1c7bf7dd6d2b47675139e1afa0eb1bb"
    )
