"""Versioned canonical source anchors, separate from server-issued UUIDs."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, TypeAlias

from axit_ingestion_spike.normalization import (
    JsonValue,
    canonical_sha256,
    canonicalize_json,
    normalize_text,
    text_fingerprint,
)


ANCHOR_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _require_integer(value: int, *, label: str, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")


def _require_identifier(value: str, *, label: str) -> None:
    if not value or len(value) > 128 or normalize_text(value) != value:
        raise ValueError(
            f"{label} must be non-empty normalized text up to 128 characters"
        )


def _require_sha256(value: str, *, label: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256 hex")


@dataclass(frozen=True, slots=True)
class BBox:
    """A top-left-origin box normalized to the closed unit square."""

    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        values = (self.left, self.top, self.right, self.bottom)
        if any(isinstance(value, bool) or not math.isfinite(value) for value in values):
            raise ValueError("bbox coordinates must be finite numbers")
        if any(value < 0 or value > 1 for value in values):
            raise ValueError("bbox coordinates must be in [0, 1]")
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("bbox must have positive area")

    def to_list(self) -> list[JsonValue]:
        canonical = canonicalize_json([self.left, self.top, self.right, self.bottom])
        if not isinstance(canonical, list):  # pragma: no cover - structural invariant
            raise AssertionError("canonical bbox must be a list")
        numeric: list[JsonValue] = []
        for value in canonical:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AssertionError("canonical bbox entries must be numeric")
            numeric.append(value)
        return numeric


class Anchor(Protocol):
    def to_dict(self) -> dict[str, JsonValue]: ...

    @property
    def anchor_hash(self) -> str: ...


class _AnchorMixin:
    source_sha256: str
    extraction_profile_hash: str

    def _validate_identity(self) -> None:
        _require_sha256(self.source_sha256, label="anchor source_sha256")
        _require_sha256(
            self.extraction_profile_hash,
            label="anchor extraction_profile_hash",
        )

    def _identity(
        self,
        *,
        kind: str,
        locator: dict[str, JsonValue],
        fingerprint: str,
    ) -> dict[str, JsonValue]:
        return {
            "schema_version": ANCHOR_SCHEMA_VERSION,
            "kind": kind,
            "source_sha256": self.source_sha256,
            "extraction_profile_hash": self.extraction_profile_hash,
            "locator": locator,
            "text_fingerprint": fingerprint,
        }

    def to_dict(self) -> dict[str, JsonValue]:
        raise NotImplementedError

    @property
    def anchor_hash(self) -> str:
        # This is a deterministic lookup identity, never the server-issued anchor UUID.
        return canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class TextLineAnchor(_AnchorMixin):
    source_sha256: str
    extraction_profile_hash: str
    line: int
    start: int
    end: int
    text_fingerprint: str

    def __post_init__(self) -> None:
        self._validate_identity()
        if (
            isinstance(self.line, bool)
            or not isinstance(self.line, int)
            or self.line < 1
        ):
            raise ValueError("text line must use a 1-based positive integer")
        if (
            isinstance(self.start, bool)
            or isinstance(self.end, bool)
            or not isinstance(self.start, int)
            or not isinstance(self.end, int)
            or self.start < 0
            or self.end <= self.start
        ):
            raise ValueError("text offsets must be a valid Unicode code-point range")
        _require_sha256(self.text_fingerprint, label="anchor text_fingerprint")

    @classmethod
    def from_line(
        cls,
        *,
        source_sha256: str,
        extraction_profile_hash: str,
        line: int,
        start: int,
        end: int,
        source_line: str,
    ) -> "TextLineAnchor":
        if isinstance(line, bool) or not isinstance(line, int) or line < 1:
            raise ValueError("text line must use a 1-based positive integer")
        normalized_line = normalize_text(source_line)
        if "\n" in normalized_line:
            raise ValueError("source_line must contain exactly one logical line")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > len(normalized_line)
        ):
            raise ValueError("text offsets must be a valid Unicode code-point range")
        return cls(
            source_sha256,
            extraction_profile_hash,
            line,
            start,
            end,
            text_fingerprint(normalized_line[start:end]),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return self._identity(
            kind="text_line",
            locator={"line": self.line, "start": self.start, "end": self.end},
            fingerprint=self.text_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class PdfBlockAnchor(_AnchorMixin):
    source_sha256: str
    extraction_profile_hash: str
    page: int
    block_id: str
    bbox: BBox
    text_fingerprint: str

    def __post_init__(self) -> None:
        self._validate_identity()
        if (
            isinstance(self.page, bool)
            or not isinstance(self.page, int)
            or self.page < 0
        ):
            raise ValueError("PDF page must be a zero-based non-negative integer")
        _require_identifier(self.block_id, label="PDF block_id")
        _require_sha256(self.text_fingerprint, label="anchor text_fingerprint")

    @classmethod
    def from_text(
        cls,
        *,
        source_sha256: str,
        extraction_profile_hash: str,
        page: int,
        block_id: str,
        bbox: BBox,
        text: str,
    ) -> "PdfBlockAnchor":
        normalized = normalize_text(text)
        if not normalized:
            raise ValueError("PDF anchor text must not be empty")
        return cls(
            source_sha256,
            extraction_profile_hash,
            page,
            block_id,
            bbox,
            text_fingerprint(normalized),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return self._identity(
            kind="pdf_block",
            locator={
                "page": self.page,
                "block_id": self.block_id,
                "bbox": self.bbox.to_list(),
            },
            fingerprint=self.text_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class ImageBBoxAnchor(_AnchorMixin):
    source_sha256: str
    extraction_profile_hash: str
    image_id: str
    bbox: BBox
    text_fingerprint: str

    def __post_init__(self) -> None:
        self._validate_identity()
        _require_identifier(self.image_id, label="image_id")
        _require_sha256(self.text_fingerprint, label="anchor text_fingerprint")

    @classmethod
    def from_ocr(
        cls,
        *,
        source_sha256: str,
        extraction_profile_hash: str,
        image_id: str,
        bbox: BBox,
        text: str,
    ) -> "ImageBBoxAnchor":
        normalized = normalize_text(text)
        if not normalized:
            raise ValueError("OCR anchor text must not be empty")
        return cls(
            source_sha256,
            extraction_profile_hash,
            image_id,
            bbox,
            text_fingerprint(normalized),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        # OCR text and confidence are block attributes, not hash identity inputs.
        return self._identity(
            kind="image_bbox",
            locator={"image_id": self.image_id, "bbox": self.bbox.to_list()},
            fingerprint=self.text_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class HwpParagraphAnchor(_AnchorMixin):
    source_sha256: str
    extraction_profile_hash: str
    parser: str
    parser_version: str
    section: int
    paragraph: int
    table: int | None
    table_block: int | None
    table_row: int | None
    cell: int | None
    cell_paragraph: int | None
    footnote: int | None
    footnote_paragraph: int | None
    text_fingerprint: str

    def __post_init__(self) -> None:
        self._validate_identity()
        _require_identifier(self.parser, label="HWP parser")
        _require_identifier(self.parser_version, label="HWP parser_version")
        _require_integer(self.section, label="HWP section", minimum=0)
        _require_integer(self.paragraph, label="HWP paragraph", minimum=0)
        table_components = (
            self.table,
            self.table_block,
            self.table_row,
            self.cell,
            self.cell_paragraph,
        )
        footnote_components = (self.footnote, self.footnote_paragraph)
        if any(value is not None for value in table_components):
            if any(value is None for value in table_components):
                raise ValueError(
                    "complete HWP table/block/row/cell/paragraph path is required"
                )
            for value in table_components:
                if value is not None:
                    _require_integer(value, label="HWP table path", minimum=0)
        if any(value is not None for value in footnote_components):
            if any(value is None for value in footnote_components):
                raise ValueError("complete HWP footnote/paragraph path is required")
            if any(value is not None for value in table_components):
                raise ValueError("HWP table and footnote paths are mutually exclusive")
            for value in footnote_components:
                if value is not None:
                    _require_integer(value, label="HWP footnote path", minimum=0)
        _require_sha256(self.text_fingerprint, label="anchor text_fingerprint")

    @classmethod
    def from_text(
        cls,
        *,
        source_sha256: str,
        extraction_profile_hash: str,
        parser: str,
        parser_version: str,
        section: int,
        paragraph: int,
        text: str,
        table: int | None = None,
        table_block: int | None = None,
        table_row: int | None = None,
        cell: int | None = None,
        cell_paragraph: int | None = None,
        footnote: int | None = None,
        footnote_paragraph: int | None = None,
    ) -> "HwpParagraphAnchor":
        normalized = normalize_text(text)
        if not normalized:
            raise ValueError("HWP anchor text must not be empty")
        return cls(
            source_sha256,
            extraction_profile_hash,
            parser,
            parser_version,
            section,
            paragraph,
            table,
            table_block,
            table_row,
            cell,
            cell_paragraph,
            footnote,
            footnote_paragraph,
            text_fingerprint(normalized),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        locator: dict[str, JsonValue] = {
            "parser": self.parser,
            "parser_version": self.parser_version,
            "section": self.section,
            "paragraph": self.paragraph,
        }
        if self.table is not None:
            locator["table"] = {
                "index": self.table,
                "block": self.table_block,
                "row": self.table_row,
                "cell": self.cell,
                "paragraph": self.cell_paragraph,
            }
        if self.footnote is not None:
            locator["footnote"] = {
                "index": self.footnote,
                "paragraph": self.footnote_paragraph,
            }
        return self._identity(
            kind="hwp_paragraph",
            locator=locator,
            fingerprint=self.text_fingerprint,
        )


AnchorType: TypeAlias = (
    TextLineAnchor | PdfBlockAnchor | ImageBBoxAnchor | HwpParagraphAnchor
)


def canonical_anchor_set_hash(anchors: Iterable[Anchor]) -> str:
    """Hash the canonical extraction sequence of source/profile-bound anchors."""

    hashes = [anchor.anchor_hash for anchor in anchors]
    return canonical_sha256(
        {
            "schema_version": ANCHOR_SCHEMA_VERSION,
            "anchor_hashes": hashes,
        }
    )
