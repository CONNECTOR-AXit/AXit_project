"""Merge the independently generated common and HWP fixture lane metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_COMMON = Path(__file__).parent / "common" / "metadata.v1.json"
DEFAULT_HWP = Path(__file__).parent / "hwp" / "generated-fixtures.json"
DEFAULT_FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "document-ingestion"
DEFAULT_OUTPUT = DEFAULT_FIXTURE_ROOT / "manifest.v1.json"
PROVENANCE = {
    "content_license": "CC0-1.0",
    "copyrighted_source_document": False,
    "generated_by_repository": True,
    "redistributable": True,
}


def _object(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object with string keys")
    return value


def _array(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be an array")
    return value


def _normalized_text(lines: object) -> str:
    values = _array(lines, "expected_nfc_text")
    if not values or any(not isinstance(value, str) or not value for value in values):
        raise ValueError("expected_nfc_text must contain non-empty strings")
    text = "\n".join(values)
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    if normalized != text:
        raise ValueError("HWP expected text must already use NFC and LF normalization")
    return text


def _hwp_entry(raw_value: object) -> dict[str, Any]:
    raw = _object(raw_value, "HWP fixture")
    path = raw.get("path")
    classification = raw.get("classification")
    if not isinstance(path, str) or classification not in {"golden", "malicious"}:
        raise ValueError("HWP fixture path/classification is invalid")
    expected: dict[str, Any]
    if classification == "golden":
        text = _normalized_text(raw.get("expected_nfc_text"))
        expected = {
            "anchor_kind": raw.get("anchor_kind"),
            "normalization_profile": "nfc-lf-v1",
            "text_nfc": text,
            "text_nfc_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        if path in {"hwp/table-footnote.hwp", "hwpx/table-footnote.hwpx"}:
            expected["required_block_types"] = [
                "hwp_paragraph",
                "hwp_table_cell",
                "hwp_footnote",
            ]
            expected["requires_complete_structural_paths"] = True
    else:
        expected_error = raw.get("expected_error")
        if not isinstance(expected_error, str) or not expected_error:
            raise ValueError("malicious HWP fixture requires expected_error")
        expected = {"error_code": expected_error}
    media_type = raw.get("media_type")
    if media_type not in {"application/x-hwp", "application/x-hwpx"}:
        raise ValueError("HWP lane media type must use the approved shared value")
    return {
        "classification": classification,
        "expected": expected,
        "generation_command": "pwsh -NoProfile -File "
        "spikes/document-ingestion/fixture_sources/hwp/generate.ps1",
        "media_type": media_type,
        "path": path,
        "provenance": dict(PROVENANCE),
        "sha256": raw.get("sha256"),
        "size_bytes": raw.get("bytes"),
    }


def build_manifest(
    *,
    common_metadata: Path,
    hwp_metadata: Path,
    fixture_root: Path,
) -> dict[str, Any]:
    common = _object(json.loads(common_metadata.read_text(encoding="utf-8")), "common metadata")
    hwp = _object(json.loads(hwp_metadata.read_text(encoding="utf-8")), "HWP metadata")
    if common.get("schema_version") != 1:
        raise ValueError("unsupported common metadata schema")
    if hwp.get("schema_version") != "axit.hwp-fixture-lane.v1":
        raise ValueError("unsupported HWP metadata schema")

    fixtures: list[dict[str, Any]] = []
    for value in _array(common.get("fixtures"), "common fixtures"):
        fixtures.append(dict(_object(value, "common fixture")))
    fixtures.extend(
        _hwp_entry(value) for value in _array(hwp.get("fixtures"), "HWP fixtures")
    )
    fixtures.sort(key=lambda entry: (entry["classification"] != "golden", entry["path"]))

    seen: set[str] = set()
    for entry in fixtures:
        path = entry.get("path")
        digest = entry.get("sha256")
        size = entry.get("size_bytes")
        if not isinstance(path, str) or path in seen:
            raise ValueError("fixture paths must be unique strings")
        seen.add(path)
        fixture = fixture_root / path
        data = fixture.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest or len(data) != size:
            raise ValueError(f"fixture bytes do not match lane metadata: {path}")

    return {
        "schema_version": 1,
        "content_license": "CC0-1.0",
        "fixtures": fixtures,
        "source_metadata": {
            "common": {
                "font": common.get("font"),
                "generator": common.get("generator"),
                "metadata_path": common_metadata.relative_to(REPOSITORY_ROOT).as_posix(),
            },
            "hwp": {
                "generator": hwp.get("generator"),
                "metadata_path": hwp_metadata.relative_to(REPOSITORY_ROOT).as_posix(),
            },
        },
    }


def write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
    ) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(serialized)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            Path(temporary_name).unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--common", type=Path, default=DEFAULT_COMMON)
    parser.add_argument("--hwp", type=Path, default=DEFAULT_HWP)
    parser.add_argument("--fixture-root", type=Path, default=DEFAULT_FIXTURE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    manifest = build_manifest(
        common_metadata=arguments.common.resolve(),
        hwp_metadata=arguments.hwp.resolve(),
        fixture_root=arguments.fixture_root.resolve(),
    )
    write_atomic(arguments.output.resolve(), manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
