"""PDFium adapter with crop/rotation-aware text anchors and OCR fallback."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Protocol, cast

from axit_ingestion_spike.anchors import BBox, PdfBlockAnchor
from axit_ingestion_spike.images import _validate_pixel_count, pixel_bbox
from axit_ingestion_spike.models import (
    ErrorCode,
    ExtractedBlock,
    ExtractionException,
    ExtractionPolicy,
    ExtractionResult,
    ExtractionWarning,
    MediaType,
    WarningCode,
    extraction_failure,
)
from axit_ingestion_spike.normalization import (
    JsonValue,
    NORMALIZATION_PROFILE,
    canonical_json,
    config_profile_hash,
    normalize_text,
)
from axit_ingestion_spike.ocr import ImageForOcr, OcrEngine


@dataclass(frozen=True, slots=True)
class CanvasBBox:
    """A positive PDF canvas box using PDF's bottom-left coordinate system."""

    left: float
    bottom: float
    right: float
    top: float

    def __post_init__(self) -> None:
        coordinates = (self.left, self.bottom, self.right, self.top)
        if any(
            isinstance(value, bool) or not math.isfinite(value) for value in coordinates
        ):
            raise ValueError("PDF canvas coordinates must be finite")
        if self.left >= self.right or self.bottom >= self.top:
            raise ValueError("PDF canvas bbox must have positive area")


@dataclass(frozen=True, slots=True)
class PdfTextRect:
    text: str
    bbox: CanvasBBox


@dataclass(frozen=True, slots=True)
class PdfPageData:
    page: int
    crop_bbox: CanvasBBox
    rotation: int
    text_rects: tuple[PdfTextRect, ...]

    def __post_init__(self) -> None:
        if isinstance(self.page, bool) or self.page < 0:
            raise ValueError("PDF page must be zero-based")
        if self.rotation not in (0, 90, 180, 270):
            raise ValueError("PDF rotation must be 0, 90, 180, or 270")


class PdfDocumentAdapter(Protocol):
    @property
    def page_count(self) -> int: ...

    def read_page(self, index: int) -> PdfPageData: ...

    def render_page(self, index: int, *, dpi: int) -> ImageForOcr: ...

    def close(self) -> None: ...


class PdfBackend(Protocol):
    name: str
    version: str

    def open(self, data: bytes) -> PdfDocumentAdapter: ...


def _rotate_point(x: float, y: float, rotation: int) -> tuple[float, float]:
    if rotation == 0:
        return x, y
    if rotation == 90:
        return 1 - y, x
    if rotation == 180:
        return 1 - x, 1 - y
    if rotation == 270:
        return y, 1 - x
    raise ValueError("PDF rotation must be 0, 90, 180, or 270")


def normalize_pdf_bbox(
    bbox: CanvasBBox,
    *,
    crop_bbox: CanvasBBox,
    rotation: int,
) -> BBox:
    """Apply crop then clockwise page rotation and return a top-left unit bbox."""

    width = crop_bbox.right - crop_bbox.left
    height = crop_bbox.top - crop_bbox.bottom
    left = (bbox.left - crop_bbox.left) / width
    right = (bbox.right - crop_bbox.left) / width
    top = 1 - ((bbox.top - crop_bbox.bottom) / height)
    bottom = 1 - ((bbox.bottom - crop_bbox.bottom) / height)
    tolerance = 1e-6
    values = (left, top, right, bottom)
    if any(value < -tolerance or value > 1 + tolerance for value in values):
        raise extraction_failure(
            ErrorCode.INVALID_COORDINATE,
            "PDF text box is outside the cropped page",
        )
    left, top, right, bottom = (min(max(value, 0.0), 1.0) for value in values)
    rotated = (
        _rotate_point(left, top, rotation),
        _rotate_point(right, top, rotation),
        _rotate_point(right, bottom, rotation),
        _rotate_point(left, bottom, rotation),
    )
    xs = [point[0] for point in rotated]
    ys = [point[1] for point in rotated]
    return BBox(min(xs), min(ys), max(xs), max(ys))


def validate_pdf_render_dimensions(
    crop_bbox: CanvasBBox,
    *,
    dpi: int,
    policy: ExtractionPolicy,
) -> tuple[int, int]:
    """Reject a huge page before PDFium allocates its render bitmap."""

    if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi <= 0:
        raise ValueError("PDF render DPI must be a positive integer")
    scale = dpi / 72
    scaled_width = (crop_bbox.right - crop_bbox.left) * scale
    scaled_height = (crop_bbox.top - crop_bbox.bottom) * scale
    if (
        not math.isfinite(scaled_width)
        or not math.isfinite(scaled_height)
        or scaled_width <= 0
        or scaled_height <= 0
    ):
        raise extraction_failure(
            ErrorCode.IMAGE_PIXEL_LIMIT,
            "PDF page render dimensions exceed configured pixel limits",
        )
    width = max(1, math.ceil(scaled_width))
    height = max(1, math.ceil(scaled_height))
    _validate_pixel_count(width, height, policy)
    return width, height


class _PdfiumDocument:
    def __init__(self, document: Any, *, policy: ExtractionPolicy) -> None:
        self._document = document
        self._policy = policy

    @property
    def page_count(self) -> int:
        try:
            return int(len(self._document))
        except Exception as error:
            raise extraction_failure(
                ErrorCode.CORRUPT_DOCUMENT,
                "PDF parser could not read the page tree",
            ) from error

    def read_page(self, index: int) -> PdfPageData:
        page: Any | None = None
        text_page: Any | None = None
        try:
            page = self._document[index]
            crop_values = page.get_bbox()
            crop = CanvasBBox(*(float(value) for value in crop_values))
            rotation = int(page.get_rotation())
            text_page = page.get_textpage()
            rect_count = int(text_page.count_rects())
            if rect_count > self._policy.max_blocks:
                raise extraction_failure(
                    ErrorCode.OUTPUT_TOO_LARGE,
                    "PDF text rectangle count exceeds configured limit",
                )
            rects: list[PdfTextRect] = []
            seen: set[str] = set()
            for rect_index in range(rect_count):
                rect_values = text_page.get_rect(rect_index)
                canvas_bbox = CanvasBBox(*(float(value) for value in rect_values))
                text = normalize_text(
                    text_page.get_text_bounded(
                        left=canvas_bbox.left,
                        bottom=canvas_bbox.bottom,
                        right=canvas_bbox.right,
                        top=canvas_bbox.top,
                    )
                ).strip()
                if not text:
                    continue
                identity = canonical_json({"text": text, "bbox": list(rect_values)})
                if identity in seen:
                    continue
                seen.add(identity)
                rects.append(PdfTextRect(text, canvas_bbox))
            if not rects:
                whole_text = normalize_text(text_page.get_text_bounded()).strip()
                if whole_text:
                    rects.append(PdfTextRect(whole_text, crop))
            return PdfPageData(index, crop, rotation, tuple(rects))
        except ExtractionException:
            raise
        except Exception as error:
            raise extraction_failure(
                ErrorCode.CORRUPT_DOCUMENT,
                "PDF parser rejected page content",
            ) from error
        finally:
            if text_page is not None:
                text_page.close()
            if page is not None:
                page.close()

    def render_page(self, index: int, *, dpi: int) -> ImageForOcr:
        page: Any | None = None
        bitmap: Any | None = None
        try:
            page = self._document[index]
            bitmap = page.render(
                scale=dpi / 72,
                rotation=0,
                grayscale=False,
                maybe_alpha=False,
                rev_byteorder=True,
            )
            width = int(bitmap.width)
            height = int(bitmap.height)
            _validate_pixel_count(width, height, self._policy)
            image: Any = bitmap.to_pil().convert("RGB").copy()
            return cast(ImageForOcr, image)
        except ExtractionException:
            raise
        except Exception as error:
            raise extraction_failure(
                ErrorCode.CORRUPT_DOCUMENT,
                "PDF renderer rejected page content",
            ) from error
        finally:
            if bitmap is not None:
                bitmap.close()
            if page is not None:
                page.close()

    def close(self) -> None:
        self._document.close()


class PdfiumBackend:
    name = "pypdfium2"

    def __init__(self, *, policy: ExtractionPolicy, version: str | None = None) -> None:
        try:
            detected = metadata.version("pypdfium2")
        except metadata.PackageNotFoundError:
            detected = "unavailable"
        self.version = version or detected
        self.policy = policy

    def open(self, data: bytes) -> PdfDocumentAdapter:
        try:
            import pypdfium2 as pdfium  # type: ignore[import-untyped]
        except ImportError as error:
            raise extraction_failure(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                "pypdfium2 PDF parser is unavailable",
            ) from error
        try:
            document = pdfium.PdfDocument(data)
        except Exception as error:
            error_code = getattr(error, "err_code", None)
            if error_code == 4:
                raise extraction_failure(
                    ErrorCode.ENCRYPTED_DOCUMENT,
                    "encrypted PDF documents are not accepted",
                ) from error
            raise extraction_failure(
                ErrorCode.CORRUPT_DOCUMENT,
                "PDF parser rejected corrupt or unsupported data",
            ) from error
        return _PdfiumDocument(document, policy=self.policy)


class PdfExtractor:
    def __init__(
        self,
        *,
        backend: PdfBackend,
        ocr: OcrEngine | None,
        policy: ExtractionPolicy,
    ) -> None:
        self.backend = backend
        self.ocr = ocr
        self.policy = policy

    def extract(self, data: bytes, *, source_sha256: str) -> ExtractionResult:
        ocr_profile: JsonValue
        if self.ocr is None:
            ocr_profile = None
        else:
            ocr_profile = {
                "name": self.ocr.name,
                "version": self.ocr.version,
                "config": dict(self.ocr.config),
            }
        profile: Mapping[str, JsonValue] = {
            "policy_hash": self.policy.profile_hash,
            "backend": {"name": self.backend.name, "version": self.backend.version},
            "ocr": ocr_profile,
            "render_dpi": self.policy.render_dpi,
            "coordinate_profile": "crop-rotate-top-left-unit-v1",
        }
        extraction_profile_hash = config_profile_hash(profile)
        document = self.backend.open(data)
        blocks: list[ExtractedBlock] = []
        warnings: list[ExtractionWarning] = []
        try:
            page_count = document.page_count
            if page_count <= 0:
                raise extraction_failure(
                    ErrorCode.CORRUPT_DOCUMENT,
                    "PDF contains no pages",
                )
            if page_count > self.policy.max_pdf_pages:
                raise extraction_failure(
                    ErrorCode.PDF_PAGE_LIMIT,
                    "PDF page count exceeds configured limit",
                )
            for page_index in range(page_count):
                page = document.read_page(page_index)
                if page.page != page_index:
                    raise extraction_failure(
                        ErrorCode.INVALID_COORDINATE,
                        "PDF adapter returned an inconsistent page index",
                    )
                normalized_rects = tuple(
                    (normalize_text(rect.text).strip(), rect.bbox)
                    for rect in page.text_rects
                    if normalize_text(rect.text).strip()
                )
                text_chars = sum(len(text) for text, _ in normalized_rects)
                if text_chars >= self.policy.min_pdf_text_chars:
                    for rect_index, (text, bbox) in enumerate(normalized_rects):
                        anchor = PdfBlockAnchor.from_text(
                            source_sha256=source_sha256,
                            extraction_profile_hash=extraction_profile_hash,
                            page=page_index,
                            block_id=f"text-{rect_index:04d}",
                            bbox=normalize_pdf_bbox(
                                bbox,
                                crop_bbox=page.crop_bbox,
                                rotation=page.rotation,
                            ),
                            text=text,
                        )
                        blocks.append(
                            ExtractedBlock(
                                ordinal=len(blocks),
                                text=text,
                                block_type="pdf_text",
                                confidence=None,
                                anchor=anchor,
                            )
                        )
                else:
                    validate_pdf_render_dimensions(
                        page.crop_bbox,
                        dpi=self.policy.render_dpi,
                        policy=self.policy,
                    )
                    self._append_ocr_page(
                        document,
                        page_index,
                        blocks,
                        warnings,
                        source_sha256=source_sha256,
                        extraction_profile_hash=extraction_profile_hash,
                    )
                if len(blocks) > self.policy.max_blocks:
                    raise extraction_failure(
                        ErrorCode.OUTPUT_TOO_LARGE,
                        "extracted block count exceeds configured limit",
                    )
        finally:
            document.close()

        if not blocks:
            raise extraction_failure(
                ErrorCode.NO_EXTRACTABLE_TEXT,
                "PDF contains no extractable text",
            )
        return ExtractionResult(
            source_sha256=source_sha256,
            media_type=MediaType.PDF,
            parser_name=self.backend.name,
            parser_version=self.backend.version,
            normalization_profile=NORMALIZATION_PROFILE,
            config_profile_hash=extraction_profile_hash,
            blocks=tuple(blocks),
            warnings=tuple(warnings),
        ).validate_bounds(self.policy)

    def _append_ocr_page(
        self,
        document: PdfDocumentAdapter,
        page_index: int,
        blocks: list[ExtractedBlock],
        warnings: list[ExtractionWarning],
        *,
        source_sha256: str,
        extraction_profile_hash: str,
    ) -> None:
        if self.ocr is None:
            raise extraction_failure(
                ErrorCode.OCR_REQUIRED,
                "PDF page requires OCR but no OCR adapter is configured",
            )
        rendered = document.render_page(page_index, dpi=self.policy.render_dpi)
        width, height = rendered.size
        _validate_pixel_count(width, height, self.policy)
        for span_index, span in enumerate(self.ocr.recognize(rendered)):
            text = normalize_text(span.text).strip()
            if not text:
                continue
            anchor = PdfBlockAnchor.from_text(
                source_sha256=source_sha256,
                extraction_profile_hash=extraction_profile_hash,
                page=page_index,
                block_id=f"ocr-{span_index:04d}",
                bbox=pixel_bbox(span, width=width, height=height),
                text=text,
            )
            blocks.append(
                ExtractedBlock(
                    ordinal=len(blocks),
                    text=text,
                    block_type="pdf_ocr",
                    confidence=span.confidence,
                    anchor=anchor,
                )
            )
            if span.confidence < self.policy.low_confidence_threshold:
                warnings.append(
                    ExtractionWarning(
                        WarningCode.LOW_CONFIDENCE,
                        "OCR confidence is below the configured review threshold",
                        len(blocks) - 1,
                    )
                )
