from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from axit_ingestion_spike.normalization import (
    canonical_sha256,
    normalize_text,
    text_fingerprint,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MEDIA_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "application/x-hwp",
    "application/x-hwpx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_ERROR_CODES = {
    "EMPTY_INPUT",
    "INPUT_TOO_LARGE",
    "UNSUPPORTED_MEDIA_TYPE",
    "TYPE_MISMATCH",
    "DEPENDENCY_UNAVAILABLE",
    "CORRUPT_DOCUMENT",
    "ENCRYPTED_DOCUMENT",
    "IMAGE_PIXEL_LIMIT",
    "PDF_PAGE_LIMIT",
    "INVALID_COORDINATE",
    "ZIP_EXPANSION_LIMIT",
    "XML_DTD_FORBIDDEN",
    "OCR_REQUIRED",
    "OCR_TIMEOUT",
    "OCR_FAILED",
    "NO_EXTRACTABLE_TEXT",
    "OUTPUT_TOO_LARGE",
    "INTERNAL_ERROR",
}
_WARNING_CODES = {
    "LOW_CONFIDENCE",
    "PARTIAL_EXTRACTION",
    "FOOTNOTE_UNRESOLVED",
}
_APPROVED_PARSERS = {
    "application/pdf": ("pypdfium2", "5.12.1"),
    "image/png": ("pillow+tesseract-cli", "12.3.0+5.3.0"),
    "image/jpeg": ("pillow+tesseract-cli", "12.3.0+5.3.0"),
    "application/x-hwp": ("pyhwp", "0.1b15"),
    "application/x-hwpx": ("hwpxlib", "1.0.9"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "stdlib-docx", "1.0.0"
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        "libreoffice+pypdfium2+tesseract-cli", "1.0.0"
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        "stdlib-xlsx", "1.0.0"
    ),
}


@dataclass(frozen=True, slots=True)
class ProtocolBounds:
    max_blocks: int
    max_block_chars: int
    max_total_chars: int


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} contains a non-string key")
    return value


def _require_exact_keys(
    value: Mapping[str, Any], expected: set[str], label: str
) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} fields do not match the protocol")


def _require_string(value: object, label: str, *, maximum: int = 128) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or normalize_text(value) != value
    ):
        raise ValueError(f"{label} must be bounded normalized text")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError(f"{label} must contain only Unicode scalar values") from error
    return value


def _require_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")
    return value


def _require_index(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _validate_bbox(value: object) -> None:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) != 4
    ):
        raise ValueError("anchor bbox must contain four coordinates")
    coordinates: list[float] = []
    for coordinate in value:
        if (
            isinstance(coordinate, bool)
            or not isinstance(coordinate, (int, float))
            or not math.isfinite(coordinate)
            or not 0 <= coordinate <= 1
        ):
            raise ValueError("anchor bbox coordinate is outside [0, 1]")
        coordinates.append(float(coordinate))
    if coordinates[0] >= coordinates[2] or coordinates[1] >= coordinates[3]:
        raise ValueError("anchor bbox must have positive area")


def _validate_locator(
    kind: str,
    raw_locator: object,
    *,
    expected_parser_name: str,
    expected_parser_version: str,
) -> None:
    locator = _require_mapping(raw_locator, "anchor.locator")
    if kind == "text_line":
        _require_exact_keys(locator, {"line", "start", "end"}, "text locator")
        _require_index(locator["line"], "text line", minimum=1)
        start = _require_index(locator["start"], "text start")
        end = _require_index(locator["end"], "text end")
        if end <= start:
            raise ValueError("text locator end must follow start")
        return
    if kind == "pdf_block":
        _require_exact_keys(locator, {"page", "block_id", "bbox"}, "PDF locator")
        _require_index(locator["page"], "PDF page")
        _require_string(locator["block_id"], "PDF block_id")
        _validate_bbox(locator["bbox"])
        return
    if kind == "image_bbox":
        _require_exact_keys(locator, {"image_id", "bbox"}, "image locator")
        _require_string(locator["image_id"], "image_id")
        _validate_bbox(locator["bbox"])
        return
    if kind == "docx_paragraph":
        allowed = {"paragraph", "table"}
        if "paragraph" not in locator or not set(locator) <= allowed:
            raise ValueError("DOCX locator has invalid fields")
        _require_index(locator["paragraph"], "DOCX paragraph")
        if "table" in locator:
            table = _require_mapping(locator["table"], "DOCX table path")
            _require_exact_keys(
                table, {"index", "row", "cell", "paragraph"}, "DOCX table path"
            )
            for key in ("index", "row", "cell", "paragraph"):
                _require_index(table[key], f"DOCX table {key}")
        return
    if kind == "xlsx_cell":
        _require_exact_keys(
            locator,
            {"sheet", "cell", "row", "column"},
            "XLSX locator",
        )
        _require_string(locator["sheet"], "XLSX sheet")
        _require_string(locator["cell"], "XLSX cell")
        _require_index(locator["row"], "XLSX row", minimum=1)
        _require_index(locator["column"], "XLSX column", minimum=1)
        return
    if kind != "hwp_paragraph":
        raise ValueError("unknown anchor kind")

    allowed = {"parser", "parser_version", "section", "paragraph", "table", "footnote"}
    if not {"parser", "parser_version", "section", "paragraph"} <= set(locator):
        raise ValueError("HWP locator is missing its structural base")
    if not set(locator) <= allowed:
        raise ValueError("HWP locator has unknown fields")
    if _require_string(locator["parser"], "HWP parser") != expected_parser_name:
        raise ValueError("HWP anchor parser differs from result parser")
    if (
        _require_string(locator["parser_version"], "HWP parser_version")
        != expected_parser_version
    ):
        raise ValueError("HWP anchor parser version differs from result parser")
    _require_index(locator["section"], "HWP section")
    _require_index(locator["paragraph"], "HWP paragraph")
    if "table" in locator and "footnote" in locator:
        raise ValueError("HWP table and footnote paths are mutually exclusive")
    if "table" in locator:
        table = _require_mapping(locator["table"], "HWP table path")
        _require_exact_keys(
            table,
            {"index", "block", "row", "cell", "paragraph"},
            "HWP table path",
        )
        for key in ("index", "block", "row", "cell", "paragraph"):
            _require_index(table[key], f"HWP table {key}")
    if "footnote" in locator:
        footnote = _require_mapping(locator["footnote"], "HWP footnote path")
        _require_exact_keys(footnote, {"index", "paragraph"}, "HWP footnote path")
        _require_index(footnote["index"], "HWP footnote index")
        _require_index(footnote["paragraph"], "HWP footnote paragraph")


def _validate_anchor(
    raw_anchor: object,
    *,
    expected_source_sha256: str,
    expected_profile_hash: str,
    expected_text: str,
    expected_parser_name: str,
    expected_parser_version: str,
) -> Mapping[str, Any]:
    anchor = _require_mapping(raw_anchor, "block.anchor")
    _require_exact_keys(
        anchor,
        {
            "schema_version",
            "kind",
            "source_sha256",
            "extraction_profile_hash",
            "locator",
            "text_fingerprint",
        },
        "block.anchor",
    )
    if anchor["schema_version"] != 1:
        raise ValueError("anchor schema_version is not 1")
    kind = _require_string(anchor["kind"], "anchor kind")
    if anchor["source_sha256"] != expected_source_sha256:
        raise ValueError("anchor source does not match the staged input")
    if anchor["extraction_profile_hash"] != expected_profile_hash:
        raise ValueError("anchor profile does not match extraction result")
    if anchor["text_fingerprint"] != text_fingerprint(expected_text):
        raise ValueError("anchor fingerprint does not match block text")
    _validate_locator(
        kind,
        anchor["locator"],
        expected_parser_name=expected_parser_name,
        expected_parser_version=expected_parser_version,
    )
    return anchor


def _validate_success(
    payload: Mapping[str, Any],
    *,
    expected_source_sha256: str,
    expected_media_type: str,
    bounds: ProtocolBounds,
) -> None:
    _require_exact_keys(payload, {"schema_version", "ok", "result"}, "success envelope")
    result = _require_mapping(payload["result"], "result")
    _require_exact_keys(
        result,
        {
            "source_sha256",
            "media_type",
            "parser",
            "normalization_profile",
            "config_profile_hash",
            "anchor_set_hash",
            "blocks",
            "warnings",
        },
        "result",
    )
    if result["source_sha256"] != expected_source_sha256:
        raise ValueError("result source does not match the staged input")
    if result["media_type"] != expected_media_type:
        raise ValueError("result media_type does not match the staged input")
    parser = _require_mapping(result["parser"], "result.parser")
    _require_exact_keys(parser, {"name", "version"}, "result.parser")
    parser_name = _require_string(parser["name"], "parser name")
    parser_version = _require_string(parser["version"], "parser version")
    if (parser_name, parser_version) != _APPROVED_PARSERS[expected_media_type]:
        raise ValueError("result parser is not the approved pinned implementation")
    if result["normalization_profile"] != "nfc-lf-v1":
        raise ValueError("normalization profile is unsupported")
    profile_hash = _require_hash(result["config_profile_hash"], "config profile")
    _require_hash(result["anchor_set_hash"], "anchor set")

    blocks = result["blocks"]
    if (
        not isinstance(blocks, Sequence)
        or isinstance(blocks, (str, bytes, bytearray))
        or not blocks
        or len(blocks) > bounds.max_blocks
    ):
        raise ValueError("result blocks are missing or exceed the configured limit")
    anchor_hashes: list[str] = []
    total_chars = 0
    for expected_ordinal, raw_block in enumerate(blocks):
        block = _require_mapping(raw_block, f"blocks[{expected_ordinal}]")
        _require_exact_keys(
            block,
            {"ordinal", "text", "block_type", "confidence", "anchor", "anchor_hash"},
            f"blocks[{expected_ordinal}]",
        )
        if block["ordinal"] != expected_ordinal:
            raise ValueError("block ordinals are not contiguous")
        text = _require_string(
            block["text"], f"blocks[{expected_ordinal}].text", maximum=bounds.max_block_chars
        )
        total_chars += len(text)
        if total_chars > bounds.max_total_chars:
            raise ValueError("result text exceeds the configured limit")
        _require_string(block["block_type"], "block_type", maximum=64)
        confidence = block["confidence"]
        if confidence is not None and (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise ValueError("block confidence is invalid")
        anchor = _validate_anchor(
            block["anchor"],
            expected_source_sha256=expected_source_sha256,
            expected_profile_hash=profile_hash,
            expected_text=text,
            expected_parser_name=parser_name,
            expected_parser_version=parser_version,
        )
        expected_anchor_kind = {
            "application/pdf": "pdf_block",
            "image/png": "image_bbox",
            "image/jpeg": "image_bbox",
            "application/x-hwp": "hwp_paragraph",
            "application/x-hwpx": "hwp_paragraph",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx_paragraph",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pdf_block",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx_cell",
        }[expected_media_type]
        if anchor["kind"] != expected_anchor_kind:
            raise ValueError("anchor kind is incompatible with the staged media type")
        expected_anchor_hash = canonical_sha256(anchor)
        if block["anchor_hash"] != expected_anchor_hash:
            raise ValueError("anchor hash does not match its canonical payload")
        anchor_hashes.append(expected_anchor_hash)
    if len(set(anchor_hashes)) != len(anchor_hashes):
        raise ValueError("result contains duplicate anchors")
    if result["anchor_set_hash"] != canonical_sha256(
        {"schema_version": 1, "anchor_hashes": anchor_hashes}
    ):
        raise ValueError("anchor set hash does not match the ordered block sequence")

    warnings = result["warnings"]
    if not isinstance(warnings, Sequence) or isinstance(
        warnings, (str, bytes, bytearray)
    ):
        raise ValueError("result warnings must be an array")
    for index, raw_warning in enumerate(warnings):
        warning = _require_mapping(raw_warning, f"warnings[{index}]")
        _require_exact_keys(
            warning, {"code", "message", "block_ordinal"}, f"warnings[{index}]"
        )
        if warning["code"] not in _WARNING_CODES:
            raise ValueError("warning code is unsupported")
        _require_string(warning["message"], "warning message", maximum=512)
        ordinal = warning["block_ordinal"]
        if ordinal is not None:
            parsed_ordinal = _require_index(ordinal, "warning block ordinal")
            if parsed_ordinal >= len(blocks):
                raise ValueError("warning references an unknown block")


def _validate_failure(payload: Mapping[str, Any]) -> None:
    _require_exact_keys(payload, {"schema_version", "ok", "error"}, "failure envelope")
    error = _require_mapping(payload["error"], "error")
    _require_exact_keys(error, {"code", "message", "retryable"}, "error")
    if error["code"] not in _ERROR_CODES:
        raise ValueError("error code is unsupported")
    message = _require_string(error["message"], "error message", maximum=512)
    if "\n" in message:
        raise ValueError("error message must be one line")
    if not isinstance(error["retryable"], bool):
        raise ValueError("error retryable must be boolean")


def validate_parser_payload(
    payload: Mapping[str, Any],
    *,
    expected_source_sha256: str,
    expected_media_type: str,
    bounds: ProtocolBounds,
) -> None:
    _require_hash(expected_source_sha256, "expected source")
    if expected_media_type not in _MEDIA_TYPES:
        raise ValueError("expected media type is unsupported")
    if payload.get("schema_version") != 1 or not isinstance(payload.get("ok"), bool):
        raise ValueError("parser envelope header is invalid")
    if payload["ok"] is True:
        _validate_success(
            payload,
            expected_source_sha256=expected_source_sha256,
            expected_media_type=expected_media_type,
            bounds=bounds,
        )
    else:
        _validate_failure(payload)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
