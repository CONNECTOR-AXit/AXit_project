from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from axit_ingestion_spike.models import ErrorCode, ExtractionException, ExtractionPolicy, MediaType
from axit_ingestion_spike.office import PptxExtractor, XlsxExtractor
from axit_ingestion_spike.ocr import OcrSpan
from axit_ingestion_spike.pdf import CanvasBBox, PdfPageData


def _xlsx_bytes(*, xml_override: bytes | None = None, strict: bool = False) -> bytes:
    spreadsheet_ns = (
        "http://purl.oclc.org/ooxml/spreadsheetml/main"
        if strict
        else "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    )
    document_relationship_ns = (
        "http://purl.oclc.org/ooxml/officeDocument/relationships"
        if strict
        else "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    )
    package_relationship_ns = (
        "http://purl.oclc.org/ooxml/package/relationships"
        if strict
        else "http://schemas.openxmlformats.org/package/2006/relationships"
    )
    files = {
        "xl/workbook.xml": f'<workbook xmlns="{spreadsheet_ns}" xmlns:r="{document_relationship_ns}"><sheets><sheet name="Summary" sheetId="1" r:id="rId1"/></sheets></workbook>'.encode(),
        "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{package_relationship_ns}"><Relationship Id="rId1" Type="{document_relationship_ns}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'.encode(),
        "xl/sharedStrings.xml": f'<sst xmlns="{spreadsheet_ns}"><si><t>회의 안건</t></si><si><r><t>후속</t></r><r><t> 담당</t></r></si></sst>'.encode(),
        "xl/worksheets/sheet1.xml": xml_override
        or f'<worksheet xmlns="{spreadsheet_ns}"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1"><v>42</v></c></row></sheetData></worksheet>'.encode(),
    }
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return output.getvalue()


def _empty_zip() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED):
        pass
    return output.getvalue()


def test_xlsx_extracts_shared_strings_and_cell_provenance() -> None:
    result = XlsxExtractor(policy=ExtractionPolicy()).extract(
        _xlsx_bytes(), source_sha256="a" * 64
    )

    assert result.media_type is MediaType.XLSX
    assert [block.text for block in result.blocks] == ["회의 안건", "후속 담당", "42"]
    assert all(block.block_type == "xlsx_cell" for block in result.blocks)
    assert [block.anchor.to_dict()["locator"] for block in result.blocks] == [
        {"sheet": "Summary", "cell": "A1", "row": 1, "column": 1},
        {"sheet": "Summary", "cell": "B1", "row": 1, "column": 2},
        {"sheet": "Summary", "cell": "C1", "row": 1, "column": 3},
    ]


def test_xlsx_accepts_iso_strict_ooxml_namespaces() -> None:
    result = XlsxExtractor(policy=ExtractionPolicy()).extract(
        _xlsx_bytes(strict=True), source_sha256="a" * 64
    )

    assert [block.text for block in result.blocks] == ["회의 안건", "후속 담당", "42"]


def test_xlsx_rejects_dtd_and_keeps_shared_string_index_bounded() -> None:
    with pytest.raises(ExtractionException) as dtd:
        XlsxExtractor(policy=ExtractionPolicy()).extract(
            _xlsx_bytes(xml_override=b'<!DOCTYPE worksheet [<!ENTITY x "boom">]>'),
            source_sha256="a" * 64,
        )
    assert dtd.value.error.code is ErrorCode.XML_DTD_FORBIDDEN

    bad_index = b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c r="A1" t="s"><v>9</v></c></row></sheetData></worksheet>'
    with pytest.raises(ExtractionException) as index:
        XlsxExtractor(policy=ExtractionPolicy()).extract(
            _xlsx_bytes(xml_override=bad_index), source_sha256="a" * 64
        )
    assert index.value.error.code is ErrorCode.CORRUPT_DOCUMENT


class _RenderedImage:
    size = (200, 100)


class _Ocr:
    name = "tesseract-cli"
    version = "5.3.0"
    config = {"language": "kor", "oem": 1, "psm": 6, "format": "tsv"}

    def recognize(self, image: _RenderedImage) -> tuple[OcrSpan, ...]:
        return (OcrSpan("슬라이드 OCR", 10, 10, 180, 40, 0.95),)


@dataclass
class _PdfDocument:
    closed: bool = False

    @property
    def page_count(self) -> int:
        return 1

    def read_page(self, index: int) -> PdfPageData:
        return PdfPageData(
            index,
            CanvasBBox(0, 0, 100, 100),
            0,
            (),
        )

    def render_page(self, index: int, *, dpi: int) -> _RenderedImage:
        assert dpi == 300
        return _RenderedImage()

    def close(self) -> None:
        self.closed = True


class _PdfBackend:
    name = "pypdfium2"
    version = "5.12.1"

    def __init__(self) -> None:
        self.document = _PdfDocument()

    def open(self, data: bytes) -> _PdfDocument:
        assert data == b"%PDF-converted"
        return self.document


def test_pptx_converts_to_pdf_and_forces_one_ocr_render_per_page() -> None:
    backend = _PdfBackend()
    result = PptxExtractor(
        backend=backend,
        ocr=_Ocr(),
        policy=ExtractionPolicy(),
        converter=lambda data: b"%PDF-converted",
    ).extract(_empty_zip(), source_sha256="a" * 64)

    assert backend.document.closed
    assert result.media_type is MediaType.PPTX
    assert result.parser_name == "libreoffice+pypdfium2+tesseract-cli"
    assert result.blocks[0].block_type == "pdf_ocr"
    assert result.blocks[0].anchor.to_dict()["kind"] == "pdf_block"
