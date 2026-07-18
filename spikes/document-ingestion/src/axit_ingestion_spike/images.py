"""Pillow decoding and EXIF-aware image OCR extraction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import metadata
from io import BytesIO
from typing import Protocol, cast

from axit_ingestion_spike.anchors import BBox, ImageBBoxAnchor
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
    config_profile_hash,
    normalize_text,
)
from axit_ingestion_spike.ocr import ImageForOcr, OcrEngine, OcrSpan


@dataclass(frozen=True, slots=True)
class DecodedImage:
    image: ImageForOcr
    width: int
    height: int
    original_width: int
    original_height: int
    exif_orientation: int
    format: str

    def __post_init__(self) -> None:
        dimensions = (
            self.width,
            self.height,
            self.original_width,
            self.original_height,
        )
        if any(isinstance(value, bool) or value <= 0 for value in dimensions):
            raise ValueError("decoded image dimensions must be positive integers")
        if self.image.size != (self.width, self.height):
            raise ValueError("decoded image object dimensions do not match metadata")
        if self.exif_orientation not in range(1, 9):
            raise ValueError("EXIF orientation must be in [1, 8]")


class ImageDecoder(Protocol):
    name: str
    version: str

    def decode(
        self,
        data: bytes,
        *,
        expected_media_type: MediaType,
        policy: ExtractionPolicy,
    ) -> DecodedImage: ...


class PillowImageDecoder:
    name = "pillow"

    def __init__(self, *, version: str | None = None) -> None:
        try:
            detected = metadata.version("Pillow")
        except metadata.PackageNotFoundError:
            detected = "unavailable"
        self.version = version or detected

    def decode(
        self,
        data: bytes,
        *,
        expected_media_type: MediaType,
        policy: ExtractionPolicy,
    ) -> DecodedImage:
        try:
            from PIL import Image, ImageOps, UnidentifiedImageError
        except ImportError as error:
            raise extraction_failure(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                "Pillow image decoder is unavailable",
            ) from error

        expected_format = {
            MediaType.PNG: "PNG",
            MediaType.JPEG: "JPEG",
        }.get(expected_media_type)
        if expected_format is None:
            raise ValueError("Pillow decoder supports only PNG and JPEG")
        try:
            with Image.open(BytesIO(data)) as image:
                actual_format = image.format
                if actual_format != expected_format:
                    raise extraction_failure(
                        ErrorCode.TYPE_MISMATCH,
                        "decoded image format does not match inspected media type",
                    )
                original_width, original_height = image.size
                _validate_pixel_count(original_width, original_height, policy)
                orientation_value = image.getexif().get(274, 1)
                if (
                    isinstance(orientation_value, bool)
                    or not isinstance(orientation_value, int)
                    or orientation_value not in range(1, 9)
                ):
                    raise extraction_failure(
                        ErrorCode.CORRUPT_DOCUMENT,
                        "image contains an invalid EXIF orientation",
                    )
                orientation = orientation_value
                display_image = ImageOps.exif_transpose(image)
                display_image.load()
                display_width, display_height = display_image.size
                _validate_pixel_count(display_width, display_height, policy)
                detached = cast(ImageForOcr, display_image.convert("RGB").copy())
        except ExtractionException:
            raise
        except (
            Image.DecompressionBombError,
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            ValueError,
        ) as error:
            raise extraction_failure(
                ErrorCode.CORRUPT_DOCUMENT,
                "image decoder rejected corrupt or unsupported image data",
            ) from error
        return DecodedImage(
            image=detached,
            width=display_width,
            height=display_height,
            original_width=original_width,
            original_height=original_height,
            exif_orientation=orientation,
            format=actual_format,
        )


def _validate_pixel_count(width: int, height: int, policy: ExtractionPolicy) -> None:
    if width <= 0 or height <= 0 or width > policy.max_image_pixels // height:
        raise extraction_failure(
            ErrorCode.IMAGE_PIXEL_LIMIT,
            "decoded image exceeds configured pixel limit",
        )


def pixel_bbox(span: OcrSpan, *, width: int, height: int) -> BBox:
    if span.right > width or span.bottom > height:
        raise extraction_failure(
            ErrorCode.INVALID_COORDINATE,
            "OCR pixel box is outside the decoded image",
        )
    return BBox(
        span.left / width,
        span.top / height,
        span.right / width,
        span.bottom / height,
    )


class ImageExtractor:
    def __init__(
        self,
        *,
        decoder: ImageDecoder,
        ocr: OcrEngine,
        policy: ExtractionPolicy,
    ) -> None:
        self.decoder = decoder
        self.ocr = ocr
        self.policy = policy

    def extract(
        self,
        data: bytes,
        *,
        media_type: MediaType,
        source_sha256: str,
    ) -> ExtractionResult:
        decoded = self.decoder.decode(
            data,
            expected_media_type=media_type,
            policy=self.policy,
        )
        _validate_pixel_count(decoded.width, decoded.height, self.policy)
        profile: Mapping[str, JsonValue] = {
            "policy_hash": self.policy.profile_hash,
            "decoder": {"name": self.decoder.name, "version": self.decoder.version},
            "ocr": {
                "name": self.ocr.name,
                "version": self.ocr.version,
                "config": dict(self.ocr.config),
            },
            "exif_orientation_applied": True,
        }
        extraction_profile_hash = config_profile_hash(profile)
        spans = self.ocr.recognize(decoded.image)
        blocks: list[ExtractedBlock] = []
        warnings: list[ExtractionWarning] = []
        for span in spans:
            normalized = normalize_text(span.text).strip()
            if not normalized:
                continue
            anchor = ImageBBoxAnchor.from_ocr(
                source_sha256=source_sha256,
                extraction_profile_hash=extraction_profile_hash,
                image_id="image-0000",
                bbox=pixel_bbox(span, width=decoded.width, height=decoded.height),
                text=normalized,
            )
            ordinal = len(blocks)
            blocks.append(
                ExtractedBlock(
                    ordinal=ordinal,
                    text=normalized,
                    block_type="image_ocr",
                    confidence=span.confidence,
                    anchor=anchor,
                )
            )
            if span.confidence < self.policy.low_confidence_threshold:
                warnings.append(
                    ExtractionWarning(
                        WarningCode.LOW_CONFIDENCE,
                        "OCR confidence is below the configured review threshold",
                        ordinal,
                    )
                )
        if not blocks:
            raise extraction_failure(
                ErrorCode.NO_EXTRACTABLE_TEXT,
                "OCR produced no extractable image text",
            )
        return ExtractionResult(
            source_sha256=source_sha256,
            media_type=media_type,
            parser_name=f"{self.decoder.name}+{self.ocr.name}",
            parser_version=f"{self.decoder.version}+{self.ocr.version}",
            normalization_profile=NORMALIZATION_PROFILE,
            config_profile_hash=extraction_profile_hash,
            blocks=tuple(blocks),
            warnings=tuple(warnings),
        ).validate_bounds(self.policy)
