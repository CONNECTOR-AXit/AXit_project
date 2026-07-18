"""Validate deterministic G0 fixtures and the pinned Korean OCR threshold."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError


HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[3]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "document-ingestion"
METADATA_PATH = HERE / "metadata.v1.json"
OCR_IMAGE = "axit-g0-fixture-ocr-check:tesseract5.3.0-kor4.1.0"
OCR_DOCKERFILE = HERE / "ocr-check.Dockerfile"
LOW_CONFIDENCE_THRESHOLD = 0.8


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalized_ocr_text(value: str) -> str:
    """Apply NFC/LF and ignore empty OCR layout lines for score calculation."""

    normalized = unicodedata.normalize(
        "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
    )
    return "\n".join(line.strip() for line in normalized.split("\n") if line.strip())


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_character in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_character != right_character),
                )
            )
        previous = current
    return previous[-1]


def _character_accuracy(expected: str, actual: str) -> float:
    denominator = max(len(expected), len(actual), 1)
    return 1 - (_edit_distance(expected, actual) / denominator)


def _load_metadata() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or metadata.get("schema_version") != 1:
        raise AssertionError("fixture metadata schema is not version 1")
    raw_entries = metadata.get("fixtures")
    if not isinstance(raw_entries, list):
        raise AssertionError("fixture metadata entries are missing")
    entries = {entry["path"]: entry for entry in raw_entries}
    if len(entries) != len(raw_entries):
        raise AssertionError("fixture metadata contains duplicate paths")
    return metadata, entries


def _validate_metadata_and_bytes(
    metadata: dict[str, Any], entries: dict[str, dict[str, Any]]
) -> None:
    if metadata.get("content_license") != "CC0-1.0":
        raise AssertionError("fixture content license must be CC0-1.0")
    for relative_path, entry in entries.items():
        fixture_path = FIXTURE_ROOT / relative_path
        payload = fixture_path.read_bytes()
        if len(payload) != entry["size_bytes"]:
            raise AssertionError(f"fixture size mismatch: {relative_path}")
        if _sha256(payload) != entry["sha256"]:
            raise AssertionError(f"fixture SHA-256 mismatch: {relative_path}")
        if entry["provenance"] != {
            "content_license": "CC0-1.0",
            "copyrighted_source_document": False,
            "generated_by_repository": True,
            "redistributable": True,
        }:
            raise AssertionError(f"fixture provenance mismatch: {relative_path}")
        expected = entry["expected"]
        expected_text = expected.get("text_nfc")
        if expected_text is not None:
            if unicodedata.normalize("NFC", expected_text) != expected_text:
                raise AssertionError(f"expected text is not NFC: {relative_path}")
            if expected.get("normalization_profile") != "nfc-lf-v1":
                raise AssertionError(f"normalization profile mismatch: {relative_path}")
            if _sha256(expected_text.encode("utf-8")) != expected.get(
                "text_nfc_sha256"
            ):
                raise AssertionError(f"expected text hash mismatch: {relative_path}")

    font = metadata["font"]
    font_path = REPOSITORY_ROOT / font["path"]
    license_path = REPOSITORY_ROOT / font["license_file"]
    if font["license"] != "OFL-1.1":
        raise AssertionError("fixture font must use OFL-1.1")
    if _sha256(font_path.read_bytes()) != font["subset_sha256"]:
        raise AssertionError("fixture font subset hash mismatch")
    if _sha256(license_path.read_bytes()) != font["license_sha256"]:
        raise AssertionError("fixture font license hash mismatch")
    if "SIL OPEN FONT LICENSE Version 1.1" not in license_path.read_text(
        encoding="utf-8"
    ):
        raise AssertionError("fixture font license text is not OFL 1.1")


def _extract_pdf_text(path: Path) -> str:
    document = pdfium.PdfDocument(path)
    try:
        if len(document) != 1:
            raise AssertionError(f"fixture PDF must have one page: {path.name}")
        page = document[0]
        try:
            text_page = page.get_textpage()
            try:
                return text_page.get_text_range().replace("\r\n", "\n")
            finally:
                text_page.close()
        finally:
            page.close()
    finally:
        document.close()


def _validate_media_shapes(entries: dict[str, dict[str, Any]]) -> None:
    text_pdf = FIXTURE_ROOT / "pdf" / "text-korean.pdf"
    scanned_pdf = FIXTURE_ROOT / "pdf" / "scanned-korean.pdf"
    if (
        _extract_pdf_text(text_pdf)
        != entries["pdf/text-korean.pdf"]["expected"]["text_nfc"]
    ):
        raise AssertionError("text PDF does not expose the exact Unicode text layer")
    if _extract_pdf_text(scanned_pdf):
        raise AssertionError("scanned PDF unexpectedly contains a text layer")

    for relative_path in ("images/korean-clean.png", "images/korean-clean.jpg"):
        with Image.open(FIXTURE_ROOT / relative_path) as image:
            image.load()
            if image.size != (1800, 1000):
                raise AssertionError(f"clean image dimensions changed: {relative_path}")
    with Image.open(FIXTURE_ROOT / "images/rotated-low-confidence.jpg") as image:
        if image.size != (480, 960) or image.getexif().get(274) != 6:
            raise AssertionError("rotated JPEG storage or EXIF orientation changed")
        if ImageOps.exif_transpose(image).size != (960, 480):
            raise AssertionError("rotated JPEG display dimensions changed")


def _expect_pdf_failure(path: Path, *, encrypted: bool) -> None:
    try:
        document = pdfium.PdfDocument(path)
        try:
            len(document)
        finally:
            document.close()
    except Exception as error:
        if encrypted and getattr(error, "err_code", None) != 4:
            raise AssertionError(
                "encrypted PDF did not report PDFium password error"
            ) from error
        return
    raise AssertionError(f"malicious PDF unexpectedly opened: {path.name}")


def _validate_malicious_shapes(entries: dict[str, dict[str, Any]]) -> None:
    expected_codes = {
        path: entry["expected"]["error_code"]
        for path, entry in entries.items()
        if entry["classification"] == "malicious"
    }
    required_codes = {
        "malicious/encrypted.pdf": "ENCRYPTED_DOCUMENT",
        "malicious/zip-bomb.hwpx": "ZIP_EXPANSION_LIMIT",
        "malicious/xxe.hwpx": "XML_DTD_FORBIDDEN",
        "malicious/path-traversal.hwpx": "CORRUPT_DOCUMENT",
        "malicious/corrupt-image.png": "CORRUPT_DOCUMENT",
        "malicious/polyglot-image.jpg": "CORRUPT_DOCUMENT",
        "malicious/corrupt.pdf": "CORRUPT_DOCUMENT",
    }
    if not required_codes.items() <= expected_codes.items():
        raise AssertionError("malicious fixture failure codes are incomplete")

    _expect_pdf_failure(FIXTURE_ROOT / "malicious/encrypted.pdf", encrypted=True)
    _expect_pdf_failure(FIXTURE_ROOT / "malicious/corrupt.pdf", encrypted=False)
    try:
        with Image.open(FIXTURE_ROOT / "malicious/corrupt-image.png") as image:
            image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        pass
    else:
        raise AssertionError("corrupt PNG unexpectedly decoded")

    polyglot = (FIXTURE_ROOT / "malicious/polyglot-image.jpg").read_bytes()
    jpeg_end = polyglot.find(b"\xff\xd9")
    zip_start = polyglot.find(b"PK\x03\x04", jpeg_end + 2)
    if jpeg_end < 0 or zip_start < 0:
        raise AssertionError("polyglot fixture lost a JPEG or ZIP boundary")
    with Image.open(io.BytesIO(polyglot)) as image:
        image.load()
    with ZipFile(io.BytesIO(polyglot[zip_start:])) as archive:
        if archive.read("payload.txt") != b"not an image payload":
            raise AssertionError("polyglot ZIP payload changed")

    with ZipFile(FIXTURE_ROOT / "malicious/zip-bomb.hwpx") as archive:
        section = archive.getinfo("Contents/section0.xml")
        ratio = section.file_size / max(section.compress_size, 1)
        minimum = entries["malicious/zip-bomb.hwpx"]["expected"][
            "min_compression_ratio"
        ]
        if ratio < minimum:
            raise AssertionError("ZIP expansion fixture ratio is below its contract")
    with ZipFile(FIXTURE_ROOT / "malicious/xxe.hwpx") as archive:
        xxe = archive.read("Contents/section0.xml")
        if b"<!DOCTYPE" not in xxe or b"<!ENTITY" not in xxe:
            raise AssertionError("XXE fixture lost its forbidden declarations")
    with ZipFile(FIXTURE_ROOT / "malicious/path-traversal.hwpx") as archive:
        if "../escape.xml" not in archive.namelist():
            raise AssertionError("path traversal fixture lost its escaping entry")


def _docker_tesseract(path: Path, *, output_format: str | None = None) -> bytes:
    command = [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "64",
        "--memory",
        "256m",
        "--cpus",
        "1",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=32m",
        "--mount",
        f"type=bind,source={path.resolve()},target=/input,readonly",
        OCR_IMAGE,
        "/input",
        "stdout",
        "-l",
        "kor",
        "--oem",
        "1",
        "--psm",
        "6",
    ]
    if output_format is not None:
        command.append(output_format)
    completed = subprocess.run(command, check=True, capture_output=True)
    return completed.stdout


def _line_confidences(tsv_payload: bytes) -> list[float]:
    reader = csv.DictReader(io.StringIO(tsv_payload.decode("utf-8")), delimiter="\t")
    accumulators: dict[tuple[str, str, str, str], tuple[float, int]] = {}
    for row in reader:
        word = (row.get("text") or "").strip()
        confidence = float(row.get("conf") or "-1")
        if not word or confidence < 0:
            continue
        key = tuple(
            row.get(field) or ""
            for field in ("page_num", "block_num", "par_num", "line_num")
        )
        weighted, weight = accumulators.get(key, (0.0, 0))
        word_weight = max(len(word), 1)
        accumulators[key] = (
            weighted + (confidence / 100) * word_weight,
            weight + word_weight,
        )
    return [weighted / weight for weighted, weight in accumulators.values()]


def _render_scanned_pdf(path: Path, destination: Path) -> None:
    document = pdfium.PdfDocument(path)
    try:
        page = document[0]
        try:
            bitmap = page.render(scale=300 / 72, rev_byteorder=True)
            try:
                bitmap.to_pil().convert("RGB").save(destination, format="PNG")
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()


def _validate_ocr(
    entries: dict[str, dict[str, Any]], *, build_image: bool
) -> dict[str, float]:
    if build_image:
        subprocess.run(
            [
                "docker",
                "build",
                "--platform",
                "linux/amd64",
                "--file",
                str(OCR_DOCKERFILE),
                "--tag",
                OCR_IMAGE,
                str(HERE),
            ],
            check=True,
        )
    measurements: dict[str, float] = {}
    for relative_path in ("images/korean-clean.png", "images/korean-clean.jpg"):
        actual = _normalized_ocr_text(
            _docker_tesseract(FIXTURE_ROOT / relative_path).decode("utf-8")
        )
        expected = entries[relative_path]["expected"]["text_nfc"]
        accuracy = _character_accuracy(expected, actual)
        measurements[relative_path] = accuracy
        if accuracy < entries[relative_path]["expected"]["min_ocr_accuracy"]:
            raise AssertionError(f"clean OCR threshold failed: {relative_path}")

    temp_parent = Path("C:/tmp") if os.name == "nt" else Path("/tmp")
    with tempfile.TemporaryDirectory(
        prefix="axit-fixture-ocr-", dir=temp_parent
    ) as temporary:
        temporary_root = Path(temporary)
        scanned = temporary_root / "scanned.png"
        _render_scanned_pdf(FIXTURE_ROOT / "pdf/scanned-korean.pdf", scanned)
        actual = _normalized_ocr_text(_docker_tesseract(scanned).decode("utf-8"))
        expected_entry = entries["pdf/scanned-korean.pdf"]["expected"]
        accuracy = _character_accuracy(expected_entry["text_nfc"], actual)
        measurements["pdf/scanned-korean.pdf"] = accuracy
        if accuracy < expected_entry["min_ocr_accuracy"]:
            raise AssertionError("scanned PDF OCR threshold failed")

        rotated = temporary_root / "rotated.png"
        with Image.open(FIXTURE_ROOT / "images/rotated-low-confidence.jpg") as source:
            ImageOps.exif_transpose(source).convert("RGB").save(rotated, format="PNG")
        confidences = _line_confidences(_docker_tesseract(rotated, output_format="tsv"))
        if not confidences or min(confidences) >= LOW_CONFIDENCE_THRESHOLD:
            raise AssertionError("rotated fixture does not trigger LOW_CONFIDENCE")
        measurements["images/rotated-low-confidence.jpg:minimum_line_confidence"] = min(
            confidences
        )
    return measurements


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-ocr-image-build",
        action="store_true",
        help="reuse the already-built pinned Tesseract image",
    )
    args = parser.parse_args()
    metadata, entries = _load_metadata()
    _validate_metadata_and_bytes(metadata, entries)
    _validate_media_shapes(entries)
    _validate_malicious_shapes(entries)
    measurements = _validate_ocr(entries, build_image=not args.skip_ocr_image_build)
    print(
        json.dumps(
            {
                "fixture_count": len(entries),
                "ocr": measurements,
                "status": "PASS",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
