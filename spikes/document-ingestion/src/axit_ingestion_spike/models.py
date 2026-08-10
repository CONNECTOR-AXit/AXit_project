"""Typed, bounded worker input policy and output envelope."""

from __future__ import annotations

import math
import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from axit_ingestion_spike.anchors import AnchorType, canonical_anchor_set_hash
from axit_ingestion_spike.normalization import (
    JsonValue,
    canonical_json,
    config_profile_hash,
    normalize_text,
    text_fingerprint,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MediaType(StrEnum):
    PDF = "application/pdf"
    PNG = "image/png"
    JPEG = "image/jpeg"
    HWP = "application/x-hwp"
    HWPX = "application/x-hwpx"
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ErrorCode(StrEnum):
    EMPTY_INPUT = "EMPTY_INPUT"
    INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    CORRUPT_DOCUMENT = "CORRUPT_DOCUMENT"
    ENCRYPTED_DOCUMENT = "ENCRYPTED_DOCUMENT"
    IMAGE_PIXEL_LIMIT = "IMAGE_PIXEL_LIMIT"
    PDF_PAGE_LIMIT = "PDF_PAGE_LIMIT"
    INVALID_COORDINATE = "INVALID_COORDINATE"
    ZIP_EXPANSION_LIMIT = "ZIP_EXPANSION_LIMIT"
    XML_DTD_FORBIDDEN = "XML_DTD_FORBIDDEN"
    OCR_REQUIRED = "OCR_REQUIRED"
    OCR_TIMEOUT = "OCR_TIMEOUT"
    OCR_FAILED = "OCR_FAILED"
    NO_EXTRACTABLE_TEXT = "NO_EXTRACTABLE_TEXT"
    OUTPUT_TOO_LARGE = "OUTPUT_TOO_LARGE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class WarningCode(StrEnum):
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    PARTIAL_EXTRACTION = "PARTIAL_EXTRACTION"
    FOOTNOTE_UNRESOLVED = "FOOTNOTE_UNRESOLVED"


@dataclass(frozen=True, slots=True)
class ExtractionError:
    code: ErrorCode
    message: str
    retryable: bool = False

    def __post_init__(self) -> None:
        normalized = normalize_text(self.message)
        if not normalized or len(normalized) > 512:
            raise ValueError("error message must contain between 1 and 512 characters")
        if normalized != self.message or "\n" in normalized:
            raise ValueError("error message must be a normalized single line")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
        }


class ExtractionException(Exception):
    """A controlled failure whose public message never contains raw parser output."""

    def __init__(self, error: ExtractionError) -> None:
        super().__init__(error.code.value)
        self.error = error


def extraction_failure(
    code: ErrorCode,
    message: str,
    *,
    retryable: bool = False,
) -> ExtractionException:
    return ExtractionException(ExtractionError(code, message, retryable))


@dataclass(frozen=True, slots=True)
class ExtractionPolicy:
    max_input_bytes: int = 200 * 1024 * 1024
    max_image_pixels: int = 25_000_000
    max_pdf_pages: int = 100
    max_archive_entries: int = 256
    max_archive_entry_bytes: int = 200 * 1024 * 1024
    max_archive_total_bytes: int = 512 * 1024 * 1024
    max_archive_compression_ratio: float = 100.0
    max_xml_bytes: int = 8 * 1024 * 1024
    max_blocks: int = 10_000
    max_block_chars: int = 100_000
    max_total_chars: int = 1_000_000
    max_output_bytes: int = 8 * 1024 * 1024
    max_ocr_tsv_bytes: int = 8 * 1024 * 1024
    max_ocr_rows: int = 100_000
    ocr_timeout_seconds: float = 15.0
    render_dpi: int = 300
    min_pdf_text_chars: int = 4
    low_confidence_threshold: float = 0.6

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value <= 0
            ):
                raise ValueError(f"{name} must be positive")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.max_archive_entry_bytes > self.max_archive_total_bytes:
            raise ValueError("archive entry limit cannot exceed archive total limit")
        if not 0 < self.low_confidence_threshold <= 1:
            raise ValueError("low_confidence_threshold must be in (0, 1]")

    @property
    def profile_hash(self) -> str:
        return config_profile_hash({"profile": "g0-ingestion-v1", **asdict(self)})

    @classmethod
    def from_policy_file(cls, path: Path) -> "ExtractionPolicy":
        """Load shared G0 bounds; reject malformed policy instead of drifting silently."""

        try:
            parsed: Any = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(parsed, dict) or parsed.get("schema_version") != 1:
                raise ValueError
            input_policy = parsed["input"]
            archive_policy = parsed["archive"]
            result_policy = parsed["result"]
            sandbox_policy = parsed["sandbox"]
            if not all(
                isinstance(section, dict)
                for section in (
                    input_policy,
                    archive_policy,
                    result_policy,
                    sandbox_policy,
                )
            ):
                raise ValueError
            wall_timeout = float(sandbox_policy["wall_timeout_seconds"])
            return cls(
                max_input_bytes=int(input_policy["max_bytes"]),
                max_image_pixels=int(input_policy["image_max_pixels"]),
                max_pdf_pages=int(input_policy["pdf_max_pages"]),
                max_archive_entries=int(archive_policy["max_entries"]),
                max_archive_entry_bytes=int(
                    archive_policy["max_entry_uncompressed_bytes"]
                ),
                max_archive_total_bytes=int(
                    archive_policy["max_total_uncompressed_bytes"]
                ),
                max_archive_compression_ratio=float(
                    archive_policy["max_compression_ratio"]
                ),
                max_xml_bytes=int(archive_policy["max_xml_bytes"]),
                max_blocks=int(result_policy["max_blocks"]),
                max_block_chars=int(result_policy["max_block_chars"]),
                max_total_chars=int(result_policy["max_total_chars"]),
                max_output_bytes=int(result_policy["max_stdout_bytes"]),
                max_ocr_tsv_bytes=int(result_policy["max_stdout_bytes"]),
                ocr_timeout_seconds=max(1.0, wall_timeout - 5.0),
            )
        except (
            KeyError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise ValueError("invalid G0 policy file") from error


def load_spike_policy() -> ExtractionPolicy:
    return ExtractionPolicy.from_policy_file(
        Path(__file__).resolve().parents[2] / "policy.v1.json"
    )


@dataclass(frozen=True, slots=True)
class ExtractionWarning:
    code: WarningCode
    message: str
    block_ordinal: int | None = None

    def __post_init__(self) -> None:
        normalized = normalize_text(self.message)
        if (
            not normalized
            or len(normalized) > 512
            or normalized != self.message
            or "\n" in normalized
        ):
            raise ValueError(
                "warning message must be a normalized single line up to 512 characters"
            )
        if self.block_ordinal is not None and (
            isinstance(self.block_ordinal, bool) or self.block_ordinal < 0
        ):
            raise ValueError("warning block ordinal must be a non-negative integer")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "code": self.code.value,
            "message": self.message,
            "block_ordinal": self.block_ordinal,
        }


@dataclass(frozen=True, slots=True)
class ExtractedBlock:
    ordinal: int
    text: str
    block_type: str
    confidence: float | None
    anchor: AnchorType

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError("block ordinal must be a non-negative integer")
        if not self.text or normalize_text(self.text) != self.text:
            raise ValueError("block text must be non-empty normalized text")
        if not self.block_type or len(self.block_type) > 64:
            raise ValueError("block_type must contain 1 to 64 characters")
        if self.confidence is not None and (
            isinstance(self.confidence, bool)
            or not math.isfinite(self.confidence)
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("block confidence must be finite and in [0, 1]")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "ordinal": self.ordinal,
            "text": self.text,
            "block_type": self.block_type,
            "confidence": self.confidence,
            "anchor": self.anchor.to_dict(),
            "anchor_hash": self.anchor.anchor_hash,
        }


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    source_sha256: str
    media_type: MediaType
    parser_name: str
    parser_version: str
    normalization_profile: str
    config_profile_hash: str
    blocks: tuple[ExtractedBlock, ...]
    warnings: tuple[ExtractionWarning, ...] = ()

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.source_sha256):
            raise ValueError("source_sha256 must be lowercase SHA-256 hex")
        if not _SHA256.fullmatch(self.config_profile_hash):
            raise ValueError("config_profile_hash must be lowercase SHA-256 hex")
        for label, value in (
            ("parser_name", self.parser_name),
            ("parser_version", self.parser_version),
            ("normalization_profile", self.normalization_profile),
        ):
            if not value or len(value) > 128 or normalize_text(value) != value:
                raise ValueError(
                    f"{label} must be normalized text up to 128 characters"
                )
        if not self.blocks:
            raise ValueError("successful extraction must contain at least one block")
        if tuple(block.ordinal for block in self.blocks) != tuple(
            range(len(self.blocks))
        ):
            raise ValueError("block ordinals must be contiguous from zero")
        anchor_hashes: list[str] = []
        for block in self.blocks:
            anchor = block.anchor.to_dict()
            if anchor.get("source_sha256") != self.source_sha256:
                raise ValueError("block anchor belongs to a different source")
            if anchor.get("extraction_profile_hash") != self.config_profile_hash:
                raise ValueError(
                    "block anchor belongs to a different extraction profile"
                )
            if anchor.get("text_fingerprint") != text_fingerprint(block.text):
                raise ValueError("block text does not match its anchor fingerprint")
            anchor_hashes.append(block.anchor.anchor_hash)
        if len(set(anchor_hashes)) != len(anchor_hashes):
            raise ValueError("successful extraction contains duplicate anchors")
        if any(
            warning.block_ordinal is not None
            and warning.block_ordinal >= len(self.blocks)
            for warning in self.warnings
        ):
            raise ValueError("warning refers to an unknown block ordinal")

    def validate_bounds(self, policy: ExtractionPolicy) -> "ExtractionResult":
        if len(self.blocks) > policy.max_blocks:
            raise extraction_failure(
                ErrorCode.OUTPUT_TOO_LARGE,
                "extracted block count exceeds configured limit",
            )
        total_chars = 0
        for block in self.blocks:
            if len(block.text) > policy.max_block_chars:
                raise extraction_failure(
                    ErrorCode.OUTPUT_TOO_LARGE,
                    "an extracted block exceeds configured character limit",
                )
            total_chars += len(block.text)
            if total_chars > policy.max_total_chars:
                raise extraction_failure(
                    ErrorCode.OUTPUT_TOO_LARGE,
                    "extracted text exceeds configured character limit",
                )
        return self

    @property
    def anchor_set_hash(self) -> str:
        return canonical_anchor_set_hash(block.anchor for block in self.blocks)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "source_sha256": self.source_sha256,
            "media_type": self.media_type.value,
            "parser": {"name": self.parser_name, "version": self.parser_version},
            "normalization_profile": self.normalization_profile,
            "config_profile_hash": self.config_profile_hash,
            "anchor_set_hash": self.anchor_set_hash,
            "blocks": [block.to_dict() for block in self.blocks],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


@dataclass(frozen=True, slots=True)
class ExtractionEnvelope:
    ok: bool
    result: ExtractionResult | None = None
    error: ExtractionError | None = None

    def __post_init__(self) -> None:
        if self.ok != (self.result is not None and self.error is None):
            raise ValueError(
                "envelope must contain exactly one matching result or error"
            )

    @classmethod
    def success(cls, result: ExtractionResult) -> "ExtractionEnvelope":
        return cls(ok=True, result=result)

    @classmethod
    def failure(cls, error: ExtractionError) -> "ExtractionEnvelope":
        return cls(ok=False, error=error)

    def to_dict(self) -> dict[str, JsonValue]:
        if self.ok and self.result is not None:
            return {"schema_version": 1, "ok": True, "result": self.result.to_dict()}
        if self.error is None:  # pragma: no cover - guarded by __post_init__
            raise AssertionError("failure envelope requires an error")
        return {"schema_version": 1, "ok": False, "error": self.error.to_dict()}

    def to_json(self, *, max_bytes: int) -> str:
        if isinstance(max_bytes, bool) or max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        serialized = canonical_json(self.to_dict())
        if len(serialized.encode("utf-8")) > max_bytes:
            raise extraction_failure(
                ErrorCode.OUTPUT_TOO_LARGE,
                "serialized extraction output exceeds configured byte limit",
            )
        return serialized
