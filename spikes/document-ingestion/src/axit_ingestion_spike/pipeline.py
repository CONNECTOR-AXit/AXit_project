"""Safe media dispatch that always returns a typed bounded envelope."""

from __future__ import annotations

import hashlib
from typing import Protocol

from axit_ingestion_spike.images import ImageDecoder, ImageExtractor, PillowImageDecoder
from axit_ingestion_spike.media import inspect_input
from axit_ingestion_spike.models import (
    ErrorCode,
    ExtractionEnvelope,
    ExtractionException,
    ExtractionPolicy,
    ExtractionResult,
    MediaType,
    extraction_failure,
)
from axit_ingestion_spike.ocr import OcrEngine, TesseractCli
from axit_ingestion_spike.pdf import PdfBackend, PdfExtractor, PdfiumBackend


class HwpExtractor(Protocol):
    """Integration hook owned by the isolated HWP/HWPX sidecar lane."""

    def extract(
        self,
        data: bytes,
        *,
        media_type: MediaType,
        source_sha256: str,
    ) -> ExtractionResult: ...


def extract_document(
    data: bytes,
    *,
    filename: str | None,
    policy: ExtractionPolicy | None = None,
    ocr_engine: OcrEngine | None = None,
    image_decoder: ImageDecoder | None = None,
    pdf_backend: PdfBackend | None = None,
    hwp_extractor: HwpExtractor | None = None,
) -> ExtractionEnvelope:
    """Extract a document or reduce any parser failure to a safe public error."""

    active_policy = policy or ExtractionPolicy()
    try:
        media = inspect_input(data, filename, active_policy)
        source_sha256 = hashlib.sha256(data).hexdigest()
        ocr = ocr_engine or TesseractCli(policy=active_policy)
        if media.media_type in (MediaType.PNG, MediaType.JPEG):
            result = ImageExtractor(
                decoder=image_decoder or PillowImageDecoder(),
                ocr=ocr,
                policy=active_policy,
            ).extract(
                data,
                media_type=media.media_type,
                source_sha256=source_sha256,
            )
        elif media.media_type is MediaType.PDF:
            result = PdfExtractor(
                backend=pdf_backend or PdfiumBackend(policy=active_policy),
                ocr=ocr,
                policy=active_policy,
            ).extract(data, source_sha256=source_sha256)
        elif media.media_type in (MediaType.HWP, MediaType.HWPX):
            if hwp_extractor is None:
                from axit_ingestion_spike.hwp import JavaHwpExtractor

                hwp_extractor = JavaHwpExtractor(policy=active_policy)
            result = hwp_extractor.extract(
                data,
                media_type=media.media_type,
                source_sha256=source_sha256,
            )
        else:  # pragma: no cover - exhaustive MediaType dispatch
            raise extraction_failure(
                ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                "input media type is not supported",
            )
        result.validate_bounds(active_policy)
        success = ExtractionEnvelope.success(result)
        success.to_json(max_bytes=active_policy.max_output_bytes)
        return success
    except ExtractionException as error:
        return ExtractionEnvelope.failure(error.error)
    except Exception:
        return ExtractionEnvelope.failure(
            extraction_failure(
                ErrorCode.INTERNAL_ERROR,
                "document extraction failed without a safe typed result",
            ).error
        )
