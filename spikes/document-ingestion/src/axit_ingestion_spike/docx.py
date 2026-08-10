"""Bounded DOCX paragraph/table extraction inside the parser sandbox."""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

from axit_ingestion_spike.anchors import DocxParagraphAnchor
from axit_ingestion_spike.models import (
    ErrorCode, ExtractedBlock, ExtractionPolicy, ExtractionResult, MediaType,
    extraction_failure,
)
from axit_ingestion_spike.normalization import normalize_text

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_CORE = "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}"
_DC = "{http://purl.org/dc/elements/1.1/}"
_DCTERMS = "{http://purl.org/dc/terms/}"
_PARSER_NAME = "stdlib-docx"
_PARSER_VERSION = "1.0.0"


class DocxExtractor:
    def __init__(self, *, policy: ExtractionPolicy) -> None:
        self._policy = policy

    def extract(self, data: bytes, *, source_sha256: str) -> ExtractionResult:
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except (OSError, zipfile.BadZipFile):
            raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "DOCX archive is invalid") from None
        with archive:
            infos = archive.infolist()
            if len(infos) > self._policy.max_archive_entries:
                raise extraction_failure(ErrorCode.ZIP_EXPANSION_LIMIT, "DOCX archive has too many entries")
            total = 0
            for info in infos:
                total += info.file_size
                ratio = info.file_size / max(info.compress_size, 1)
                if (info.file_size > self._policy.max_archive_entry_bytes
                        or total > self._policy.max_archive_total_bytes
                        or ratio > self._policy.max_archive_compression_ratio):
                    raise extraction_failure(ErrorCode.ZIP_EXPANSION_LIMIT, "DOCX archive exceeds expansion limits")
            try:
                xml = archive.read("word/document.xml")
            except KeyError:
                raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "DOCX document part is missing") from None
            try:
                core_xml = archive.read("docProps/core.xml")
            except KeyError:
                core_xml = b""
        if len(xml) > self._policy.max_xml_bytes:
            raise extraction_failure(ErrorCode.ZIP_EXPANSION_LIMIT, "DOCX XML exceeds configured limit")
        upper = xml.upper()
        if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
            raise extraction_failure(ErrorCode.XML_DTD_FORBIDDEN, "DOCX XML contains a forbidden DTD or entity")
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError:
            raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "DOCX XML is invalid") from None

        profile = self._policy.profile_hash
        blocks: list[ExtractedBlock] = []
        for metadata_index, (field, value) in enumerate(self._core_properties(core_xml)):
            self._append_metadata(
                blocks, field, value, source_sha256, profile, metadata_index
            )
        body = root.find(f"{_W}body")
        if body is None:
            raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "DOCX body is missing")
        paragraph_index = 0
        table_index = 0
        for child in body:
            if child.tag == f"{_W}p":
                self._append(blocks, child, source_sha256, profile, paragraph_index)
                paragraph_index += 1
            elif child.tag == f"{_W}tbl":
                for row_index, row in enumerate(child.findall(f"{_W}tr")):
                    for cell_index, cell in enumerate(row.findall(f"{_W}tc")):
                        for cell_paragraph, paragraph in enumerate(cell.findall(f"{_W}p")):
                            self._append(blocks, paragraph, source_sha256, profile,
                                         paragraph_index, table_index, row_index,
                                         cell_index, cell_paragraph)
                            paragraph_index += 1
                table_index += 1
        if not blocks:
            raise extraction_failure(ErrorCode.NO_EXTRACTABLE_TEXT, "DOCX contains no extractable text")
        return ExtractionResult(source_sha256, MediaType.DOCX, _PARSER_NAME,
                                _PARSER_VERSION, "nfc-lf-v1", profile,
                                tuple(blocks))

    def _core_properties(self, xml: bytes) -> tuple[tuple[str, str], ...]:
        if not xml:
            return ()
        if len(xml) > self._policy.max_xml_bytes:
            raise extraction_failure(ErrorCode.ZIP_EXPANSION_LIMIT, "DOCX metadata XML exceeds configured limit")
        upper = xml.upper()
        if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
            raise extraction_failure(ErrorCode.XML_DTD_FORBIDDEN, "DOCX metadata XML contains a forbidden DTD or entity")
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError:
            raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "DOCX metadata XML is invalid") from None
        fields = (
            ("title", f"{_DC}title"), ("subject", f"{_DC}subject"),
            ("creator", f"{_DC}creator"), ("description", f"{_DC}description"),
            ("keywords", f"{_CORE}keywords"),
            ("last_modified_by", f"{_CORE}lastModifiedBy"),
            ("created", f"{_DCTERMS}created"), ("modified", f"{_DCTERMS}modified"),
        )
        values: list[tuple[str, str]] = []
        for name, tag in fields:
            node = root.find(tag)
            value = normalize_text(node.text or "") if node is not None else ""
            if value:
                values.append((name, value[:512]))
        return tuple(values)

    @staticmethod
    def _append_metadata(
        blocks: list[ExtractedBlock], field: str, value: str,
        source_sha256: str, profile: str, paragraph_index: int,
    ) -> None:
        text = normalize_text(f"{field}: {value}")
        anchor = DocxParagraphAnchor.from_text(
            source_sha256=source_sha256, extraction_profile_hash=profile,
            paragraph=paragraph_index, text=text,
        )
        blocks.append(ExtractedBlock(len(blocks), text, "docx_metadata", 1.0, anchor))

    @staticmethod
    def _append(blocks: list[ExtractedBlock], paragraph: ElementTree.Element,
                source_sha256: str, profile: str, paragraph_index: int,
                table: int | None = None, row: int | None = None,
                cell: int | None = None, cell_paragraph: int | None = None) -> None:
        text = normalize_text("".join(node.text or "" for node in paragraph.iter(f"{_W}t")))
        if not text:
            return
        style = paragraph.find(f"{_W}pPr/{_W}pStyle")
        style_name = style.get(f"{_W}val", "") if style is not None else ""
        block_type = "toc_entry" if style_name.lower().startswith("toc") else (
            "heading" if style_name.lower().startswith("heading") else
            ("table_cell" if table is not None else "docx_paragraph")
        )
        anchor = DocxParagraphAnchor.from_text(
            source_sha256=source_sha256, extraction_profile_hash=profile,
            paragraph=paragraph_index, text=text, table=table, row=row,
            cell=cell, cell_paragraph=cell_paragraph,
        )
        blocks.append(ExtractedBlock(len(blocks), text, block_type, 1.0, anchor))
