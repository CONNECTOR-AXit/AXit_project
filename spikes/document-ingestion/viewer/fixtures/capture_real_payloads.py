"""Capture browser fixtures only through the host-validated G0 sandbox boundary.

This is deliberately a capture command, not a synthetic fixture generator.  Every
committed envelope is the unmodified successful payload returned by a separate
``execute_sandbox`` invocation against a manifest-owned source document.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any


VIEWER_ROOT = Path(__file__).resolve().parents[1]
SPIKE_ROOT = VIEWER_ROOT.parent
REPOSITORY_ROOT = SPIKE_ROOT.parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "document-ingestion"
MANIFEST_PATH = SOURCE_ROOT / "manifest.v1.json"
POLICY_PATH = SPIKE_ROOT / "policy.v1.json"

# sandbox_runner.py is intentionally outside the import package because it is the
# host boundary under test.  Add only the two approved local roots required to
# import that boundary and its parser model.
sys.path[:0] = [str(SPIKE_ROOT), str(SPIKE_ROOT / "src")]

from axit_ingestion_spike.normalization import canonical_json  # noqa: E402
from parser_protocol import ProtocolBounds, validate_parser_payload  # noqa: E402
from sandbox_runner import (  # noqa: E402
    SandboxPolicy,
    SandboxRequest,
    execute_sandbox,
)


CAPTURES = (
    ("hwp/simple.hwp", "hwp-simple.json", "hwp-simple"),
    (
        "hwp/table-footnote.hwp",
        "hwp-table-footnote-run-a.json",
        "hwp-table-footnote-run-a",
    ),
    (
        "hwp/table-footnote.hwp",
        "hwp-table-footnote-run-b.json",
        "hwp-table-footnote-run-b",
    ),
    ("hwpx/simple.hwpx", "hwpx-simple.json", "hwpx-simple"),
    (
        "hwpx/table-footnote.hwpx",
        "hwpx-table-footnote.json",
        "hwpx-table-footnote",
    ),
    (
        "images/korean-clean.jpg",
        "image-korean-clean-jpeg.json",
        "image-korean-clean-jpeg",
    ),
    (
        "images/korean-clean.png",
        "image-korean-clean-png.json",
        "image-korean-clean-png",
    ),
    (
        "images/rotated-low-confidence.jpg",
        "image-rotated-low-confidence.json",
        "image-rotated-low-confidence",
    ),
    ("pdf/scanned-korean.pdf", "pdf-scanned-korean.json", "pdf-scanned-korean"),
    ("pdf/text-korean.pdf", "pdf-text-korean.json", "pdf-text-korean"),
)

APPROVED_PARSERS = {
    "application/pdf": ("pypdfium2", "5.12.1"),
    "image/png": ("pillow+tesseract-cli", "12.3.0+5.3.0"),
    "image/jpeg": ("pillow+tesseract-cli", "12.3.0+5.3.0"),
    "application/x-hwp": ("pyhwp", "0.1b15"),
    "application/x-hwpx": ("hwpxlib", "1.0.9"),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        "libreoffice+pypdfium2+tesseract-cli", "1.0.0"
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        "stdlib-xlsx", "1.0.0"
    ),
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _resolve_image_id(image: str, docker_binary: str) -> str:
    completed = subprocess.run(
        [docker_binary, "image", "inspect", image, "--format", "{{.Id}}"],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    image_id = completed.stdout.strip()
    if not image_id.startswith("sha256:") or len(image_id) != 71:
        raise RuntimeError("the extraction image did not resolve to a content address")
    return image_id


def _manifest_entries() -> dict[str, dict[str, Any]]:
    manifest = _read_json(MANIFEST_PATH)
    if manifest.get("schema_version") != 1:
        raise ValueError("the canonical manifest schema is not supported")
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        raise ValueError("the canonical manifest has no fixture list")
    entries: dict[str, dict[str, Any]] = {}
    for raw in fixtures:
        if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
            raise ValueError("the canonical manifest contains a malformed fixture")
        entries[raw["path"]] = raw
    expected = {item[0] for item in CAPTURES}
    golden = {
        path
        for path, item in entries.items()
        if item.get("classification") == "golden"
    }
    if golden != expected:
        raise ValueError("capture inventory must cover every and only golden fixture")
    return entries


def _write_json(path: Path, value: object) -> None:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    )
    path.write_text(f"{rendered}\n", encoding="utf-8", newline="\n")


def capture(image: str, docker_binary: str) -> None:
    entries = _manifest_entries()
    policy = SandboxPolicy.from_json(POLICY_PATH)
    bounds = ProtocolBounds(
        max_blocks=policy.max_blocks,
        max_block_chars=policy.max_block_chars,
        max_total_chars=policy.max_total_chars,
    )
    image_id = _resolve_image_id(image, docker_binary)
    captured_payloads: dict[str, dict[str, Any]] = {}
    provenance_captures: list[dict[str, Any]] = []

    for relative_path, payload_file, invocation_id in CAPTURES:
        manifest_entry = entries[relative_path]
        source_path = SOURCE_ROOT / PurePosixPath(relative_path)
        manifest_sha256 = manifest_entry.get("sha256")
        media_type = manifest_entry.get("media_type")
        if manifest_entry.get("classification") != "golden":
            raise ValueError(f"{relative_path} is not a golden fixture")
        source_bytes = source_path.read_bytes()
        if (
            not isinstance(manifest_sha256, str)
            or _sha256_bytes(source_bytes) != manifest_sha256
        ):
            raise ValueError(f"{relative_path} bytes do not match the canonical manifest")
        if media_type not in APPROVED_PARSERS:
            raise ValueError(f"{relative_path} has no approved parser identity")

        container_name = f"axit-g0-viewer-{invocation_id}"
        execution = execute_sandbox(
            SandboxRequest(
                image=image,
                input_bytes=source_bytes,
                original_filename=source_path.name,
                container_name=container_name,
            ),
            policy,
            docker_binary=docker_binary,
        )
        if not execution.ok or execution.payload is None:
            raise RuntimeError(
                f"real sandbox capture failed for {relative_path}: "
                f"{execution.error_code or 'missing payload'}"
            )
        payload = dict(execution.payload)
        validate_parser_payload(
            payload,
            expected_source_sha256=manifest_sha256,
            expected_media_type=media_type,
            bounds=bounds,
        )
        result = payload["result"]
        parser = result["parser"]
        if (parser["name"], parser["version"]) != APPROVED_PARSERS[media_type]:
            raise RuntimeError(f"{relative_path} used an unapproved parser")

        captured_payloads[payload_file] = payload
        payload_canonical = canonical_json(payload).encode("utf-8")
        metrics = asdict(execution)
        # The exact payload is recorded separately; do not duplicate it inside the
        # provenance index.
        metrics.pop("payload", None)
        provenance_captures.append(
            {
                "anchor_set_hash": result["anchor_set_hash"],
                "container_name": container_name,
                "execution": metrics,
                "invocation_id": invocation_id,
                "manifest_path": relative_path,
                "manifest_sha256": manifest_sha256,
                "media_type": media_type,
                "payload_file": payload_file,
                "payload_sha256": _sha256_bytes(payload_canonical),
            }
        )

    repeat_a = captured_payloads["hwp-table-footnote-run-a.json"]
    repeat_b = captured_payloads["hwp-table-footnote-run-b.json"]
    if canonical_json(repeat_a) != canonical_json(repeat_b):
        raise RuntimeError("independent table/footnote sandbox runs were not deterministic")
    if _resolve_image_id(image, docker_binary) != image_id:
        raise RuntimeError("the extraction image changed during capture")

    for payload_file, payload in captured_payloads.items():
        _write_json(Path(__file__).resolve().parent / payload_file, payload)
    provenance = {
        "capture_method": "sandbox_runner.execute_sandbox",
        "captures": provenance_captures,
        "image": {"id": image_id, "reference": image},
        "manifest_path": "tests/fixtures/document-ingestion/manifest.v1.json",
        "manifest_sha256": _sha256_file(MANIFEST_PATH),
        "policy_path": "spikes/document-ingestion/policy.v1.json",
        "policy_sha256": _sha256_file(POLICY_PATH),
        "schema_version": 1,
    }
    _write_json(Path(__file__).resolve().parent / "provenance.v1.json", provenance)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="axit-ingestion-g0:local")
    parser.add_argument("--docker-binary", default="docker")
    arguments = parser.parse_args()
    capture(arguments.image, arguments.docker_binary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
