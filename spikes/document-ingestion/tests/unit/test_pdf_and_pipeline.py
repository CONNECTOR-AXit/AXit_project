from __future__ import annotations

from dataclasses import dataclass

import pytest

from axit_ingestion_spike.models import ErrorCode, ExtractionException, ExtractionPolicy
from axit_ingestion_spike.ocr import OcrSpan
from axit_ingestion_spike.pdf import (
    CanvasBBox,
    PdfDocumentAdapter,
    PdfExtractor,
    PdfPageData,
    PdfTextRect,
    normalize_pdf_bbox,
    validate_pdf_render_dimensions,
)
from axit_ingestion_spike.pipeline import extract_document


class RenderedImage:
    size = (200, 100)

    def save(self, destination: object, *, format: str) -> None:
        raise AssertionError("the fake OCR engine does not encode the image")


class FakeOcr:
    name = "fake-ocr"
    version = "1"
    config = {"language": "kor"}

    def recognize(self, image: RenderedImage) -> tuple[OcrSpan, ...]:
        assert image.size == (200, 100)
        return (OcrSpan("스캔 회의", 20, 10, 180, 40, 0.93),)


@dataclass
class FakeDocument(PdfDocumentAdapter):
    pages: tuple[PdfPageData, ...]
    closed: bool = False

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def read_page(self, index: int) -> PdfPageData:
        return self.pages[index]

    def render_page(self, index: int, *, dpi: int) -> RenderedImage:
        assert dpi == 300
        return RenderedImage()

    def close(self) -> None:
        self.closed = True


class FakeBackend:
    name = "fake-pdf"
    version = "1"

    def __init__(self, document: FakeDocument) -> None:
        self.document = document

    def open(self, data: bytes) -> FakeDocument:
        assert data.startswith(b"%PDF-")
        return self.document


@pytest.mark.parametrize(
    ("rotation", "expected"),
    [
        (0, [0.1, 0.2, 0.4, 0.8]),
        (90, [0.2, 0.1, 0.8, 0.4]),
        (180, [0.6, 0.2, 0.9, 0.8]),
        (270, [0.2, 0.6, 0.8, 0.9]),
    ],
)
def test_pdf_bbox_applies_crop_and_clockwise_page_rotation(
    rotation: int,
    expected: list[float],
) -> None:
    # Canvas uses bottom-left origin. Crop is x=10..110, y=20..220.
    bbox = normalize_pdf_bbox(
        CanvasBBox(20, 60, 50, 180),
        crop_bbox=CanvasBBox(10, 20, 110, 220),
        rotation=rotation,
    )
    assert bbox.to_list() == expected


def test_pdf_extractor_uses_zero_based_page_and_text_rect() -> None:
    document = FakeDocument(
        (
            PdfPageData(
                page=0,
                crop_bbox=CanvasBBox(0, 0, 100, 200),
                rotation=0,
                text_rects=(PdfTextRect("회의 안건", CanvasBBox(10, 120, 90, 180)),),
            ),
        )
    )
    result = PdfExtractor(
        backend=FakeBackend(document),
        ocr=FakeOcr(),
        policy=ExtractionPolicy(min_pdf_text_chars=2),
    ).extract(b"%PDF-1.7", source_sha256="a" * 64)

    assert document.closed
    assert result.blocks[0].text == "회의 안건"
    locator = result.blocks[0].anchor.to_dict()["locator"]
    assert isinstance(locator, dict)
    assert locator["page"] == 0
    assert locator["bbox"] == [0.1, 0.1, 0.9, 0.4]
    assert result.blocks[0].block_type == "pdf_text"


def test_pdf_extractor_calls_ocr_fallback_for_scanned_page() -> None:
    document = FakeDocument((PdfPageData(0, CanvasBBox(0, 0, 100, 200), 0, ()),))
    result = PdfExtractor(
        backend=FakeBackend(document),
        ocr=FakeOcr(),
        policy=ExtractionPolicy(),
    ).extract(b"%PDF-1.7", source_sha256="a" * 64)

    block = result.blocks[0]
    assert block.block_type == "pdf_ocr"
    assert block.text == "스캔 회의"
    locator = block.anchor.to_dict()["locator"]
    assert isinstance(locator, dict)
    assert locator["bbox"] == [0.1, 0.1, 0.9, 0.4]
    assert block.confidence == 0.93


def test_pdf_page_limit_is_checked_before_reading_any_page() -> None:
    pages = tuple(
        PdfPageData(index, CanvasBBox(0, 0, 1, 1), 0, ()) for index in range(2)
    )
    document = FakeDocument(pages)
    extractor = PdfExtractor(
        backend=FakeBackend(document),
        ocr=FakeOcr(),
        policy=ExtractionPolicy(max_pdf_pages=1),
    )
    with pytest.raises(ExtractionException) as caught:
        extractor.extract(b"%PDF-1.7", source_sha256="a" * 64)
    assert caught.value.error.code is ErrorCode.PDF_PAGE_LIMIT
    assert document.closed


def test_huge_scanned_page_is_rejected_before_bitmap_render() -> None:
    class NeverRenderDocument(FakeDocument):
        def render_page(self, index: int, *, dpi: int) -> RenderedImage:
            raise AssertionError("huge page must be rejected before PDFium render")

    document = NeverRenderDocument(
        (PdfPageData(0, CanvasBBox(0, 0, 100_000, 100_000), 0, ()),)
    )
    extractor = PdfExtractor(
        backend=FakeBackend(document),
        ocr=FakeOcr(),
        policy=ExtractionPolicy(max_image_pixels=25_000_000, render_dpi=300),
    )

    with pytest.raises(ExtractionException) as caught:
        extractor.extract(b"%PDF-1.7", source_sha256="a" * 64)

    assert caught.value.error.code is ErrorCode.IMAGE_PIXEL_LIMIT
    assert document.closed


def test_pdf_render_dimension_estimate_matches_ceil_at_configured_dpi() -> None:
    dimensions = validate_pdf_render_dimensions(
        CanvasBBox(0, 0, 100, 200),
        dpi=300,
        policy=ExtractionPolicy(max_image_pixels=1_000_000),
    )

    assert dimensions == (417, 834)


def test_pipeline_returns_safe_typed_failure_for_spoofed_media() -> None:
    envelope = extract_document(b"%PDF-1.7", filename="image.png")

    assert not envelope.ok
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.TYPE_MISMATCH
