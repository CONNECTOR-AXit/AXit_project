"""Bounded Office Open XML adapters.

PPTX is intentionally converted to PDF in the sandbox and sent through the
existing PDF renderer/OCR path.  XLSX stays a read-only ZIP/XML parser: cell
text is resolved through ``sharedStrings.xml`` and each emitted block keeps a
sheet/cell anchor so search hits can be traced back to the original workbook.
"""

from __future__ import annotations

import io
import os
import posixpath
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import PurePosixPath
from typing import Callable, Iterator
from xml.etree import ElementTree

from axit_ingestion_spike.anchors import XlsxCellAnchor
from axit_ingestion_spike.models import (
    ErrorCode,
    ExtractedBlock,
    ExtractionPolicy,
    ExtractionResult,
    ExtractionWarning,
    MediaType,
    WarningCode,
    extraction_failure,
)
from axit_ingestion_spike.normalization import (
    NORMALIZATION_PROFILE,
    config_profile_hash,
    normalize_text,
)
from axit_ingestion_spike.ocr import OcrEngine
from axit_ingestion_spike.pdf import PdfBackend, PdfExtractor


XLSX_PARSER_NAME = "stdlib-xlsx"
XLSX_PARSER_VERSION = "1.0.0"
PPTX_PARSER_NAME = "libreoffice+pypdfium2+tesseract-cli"
PPTX_PARSER_VERSION = "1.0.0"

# Excel normally uses the Transitional OOXML namespaces.  Excel/LibreOffice
# can also emit the ISO Strict namespaces, however; both are valid ``.xlsx``
# packages and differ only in their XML namespace URIs.  Keep the accepted set
# explicit instead of treating arbitrary XML namespaces as spreadsheet data.
_XLSX_NAMESPACES = frozenset(
    {
        "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "http://purl.oclc.org/ooxml/spreadsheetml/main",
    }
)
_DOC_REL_NAMESPACES = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "http://purl.oclc.org/ooxml/officeDocument/relationships",
    }
)
_PKG_REL_NAMESPACES = frozenset(
    {
        "http://schemas.openxmlformats.org/package/2006/relationships",
        "http://purl.oclc.org/ooxml/package/relationships",
    }
)
_REL_TYPE_WORKSHEET = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
        "http://purl.oclc.org/ooxml/officeDocument/relationships/worksheet",
    }
)
_CELL_REFERENCE_LIMIT = 32


def _xml_local_name(tag: str) -> str:
    """Return an XML local name without accepting namespace lookalikes."""

    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


def _xml_namespace(tag: str) -> str | None:
    if not tag.startswith("{") or "}" not in tag:
        return None
    return tag[1:].split("}", 1)[0]


def _is_allowed_xml_tag(tag: str, namespaces: frozenset[str], local_name: str) -> bool:
    return _xml_local_name(tag) == local_name and _xml_namespace(tag) in namespaces


def _child(root: ElementTree.Element, namespaces: frozenset[str], local_name: str) -> ElementTree.Element | None:
    for node in root:
        if _is_allowed_xml_tag(node.tag, namespaces, local_name):
            return node
    return None


def _children(root: ElementTree.Element, namespaces: frozenset[str], local_name: str) -> tuple[ElementTree.Element, ...]:
    return tuple(
        node for node in root
        if _is_allowed_xml_tag(node.tag, namespaces, local_name)
    )


def _descendants(
    root: ElementTree.Element,
    namespaces: frozenset[str],
    local_name: str,
) -> Iterator[ElementTree.Element]:
    return (
        node for node in root.iter()
        if _is_allowed_xml_tag(node.tag, namespaces, local_name)
    )


def _read_xml(archive: zipfile.ZipFile, name: str, policy: ExtractionPolicy) -> bytes:
    try:
        info = archive.getinfo(name)
        if info.file_size > policy.max_xml_bytes:
            raise extraction_failure(
                ErrorCode.ZIP_EXPANSION_LIMIT,
                "Office XML exceeds configured limit",
            )
        value = archive.read(name)
    except KeyError:
        raise extraction_failure(
            ErrorCode.CORRUPT_DOCUMENT,
            "required Office package part is missing",
        ) from None
    except (OSError, RuntimeError, zipfile.BadZipFile):
        raise extraction_failure(
            ErrorCode.CORRUPT_DOCUMENT,
            "Office package part could not be read",
        ) from None
    if len(value) > policy.max_xml_bytes:
        raise extraction_failure(
            ErrorCode.ZIP_EXPANSION_LIMIT,
            "Office XML exceeds configured limit",
        )
    upper = value.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise extraction_failure(
            ErrorCode.XML_DTD_FORBIDDEN,
            "Office XML contains a forbidden DTD or entity",
        )
    return value


def _parse_xml(value: bytes, *, label: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(value)
    except ElementTree.ParseError:
        raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, f"{label} XML is invalid") from None


def _check_archive(archive: zipfile.ZipFile, policy: ExtractionPolicy) -> None:
    infos = archive.infolist()
    if len(infos) > policy.max_archive_entries:
        raise extraction_failure(
            ErrorCode.ZIP_EXPANSION_LIMIT,
            "Office archive has too many entries",
        )
    seen: set[str] = set()
    total = 0
    for info in infos:
        name = info.filename
        if not name or name in seen:
            raise extraction_failure(
                ErrorCode.CORRUPT_DOCUMENT,
                "Office archive contains duplicate or invalid entries",
            )
        seen.add(name)
        if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
            raise extraction_failure(
                ErrorCode.CORRUPT_DOCUMENT,
                "Office archive contains an unsafe entry path",
            )
        total += info.file_size
        ratio = info.file_size / max(info.compress_size, 1)
        if (
            info.file_size > policy.max_archive_entry_bytes
            or total > policy.max_archive_total_bytes
            or ratio > policy.max_archive_compression_ratio
        ):
            raise extraction_failure(
                ErrorCode.ZIP_EXPANSION_LIMIT,
                "Office archive exceeds expansion limits",
            )


def _open_archive(data: bytes, policy: ExtractionPolicy) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (OSError, zipfile.BadZipFile):
        raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "Office archive is invalid") from None
    try:
        _check_archive(archive, policy)
    except Exception:
        archive.close()
        raise
    return archive


def _shared_string_text(node: ElementTree.Element) -> str:
    return normalize_text(
        "".join(part.text or "" for part in _descendants(node, _XLSX_NAMESPACES, "t"))
    )


def _column_number(label: str) -> int:
    if (
        not label
        or len(label) > _CELL_REFERENCE_LIMIT
        or any(character < "A" or character > "Z" for character in label.upper())
    ):
        raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "XLSX cell reference is invalid")
    value = 0
    for character in label.upper():
        value = value * 26 + (ord(character) - ord("A") + 1)
        if value > 16_384:
            raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "XLSX cell reference is invalid")
    return value


def _cell_location(reference: str) -> tuple[str, int, int]:
    normalized = normalize_text(reference).upper()
    if len(normalized) > _CELL_REFERENCE_LIMIT:
        raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "XLSX cell reference is invalid")
    split = 0
    while split < len(normalized) and normalized[split].isalpha():
        split += 1
    if (
        split == 0
        or split == len(normalized)
        or any(character < "0" or character > "9" for character in normalized[split:])
    ):
        raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "XLSX cell reference is invalid")
    row = int(normalized[split:])
    if row < 1 or row > 1_048_576:
        raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "XLSX cell reference is invalid")
    return normalized, row, _column_number(normalized[:split])


def _safe_relationship_target(target: str) -> str:
    normalized = target.replace("\\", "/")
    path = (
        normalized.lstrip("/")
        if normalized.startswith("/")
        else posixpath.normpath(posixpath.join("xl", normalized))
    )
    if not path.startswith("xl/") or ".." in PurePosixPath(path).parts:
        raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "XLSX relationship target is invalid")
    return path


class XlsxExtractor:
    """Extract searchable cell text while preserving workbook provenance."""

    def __init__(self, *, policy: ExtractionPolicy) -> None:
        self._policy = policy

    def extract(self, data: bytes, *, source_sha256: str) -> ExtractionResult:
        archive = _open_archive(data, self._policy)
        try:
            workbook_xml = _read_xml(archive, "xl/workbook.xml", self._policy)
            rels_xml = _read_xml(archive, "xl/_rels/workbook.xml.rels", self._policy)
            shared_xml = (
                _read_xml(archive, "xl/sharedStrings.xml", self._policy)
                if "xl/sharedStrings.xml" in archive.namelist()
                else None
            )
            shared_strings = self._parse_shared_strings(shared_xml) if shared_xml is not None else ()
            sheets = self._sheet_parts(workbook_xml, rels_xml)
            blocks: list[ExtractedBlock] = []
            warnings: list[ExtractionWarning] = []
            profile = config_profile_hash(
                {
                    "policy_hash": self._policy.profile_hash,
                    "parser": {"name": XLSX_PARSER_NAME, "version": XLSX_PARSER_VERSION},
                    "index": "shared-strings-cell-text-v1",
                }
            )
            total_chars = 0
            for sheet_name, part_name in sheets:
                sheet_xml = _read_xml(archive, part_name, self._policy)
                root = _parse_xml(sheet_xml, label="XLSX worksheet")
                for cell in _descendants(root, _XLSX_NAMESPACES, "c"):
                    text = self._cell_value(cell, shared_strings)
                    if not text:
                        continue
                    reference = cell.get("r")
                    if not reference:
                        raise extraction_failure(
                            ErrorCode.CORRUPT_DOCUMENT,
                            "XLSX text cell has no coordinate",
                        )
                    cell_ref, row, column = _cell_location(reference)
                    if len(blocks) >= self._policy.max_blocks or total_chars + len(text) > self._policy.max_total_chars:
                        warnings.append(
                            ExtractionWarning(
                                WarningCode.PARTIAL_EXTRACTION,
                                "XLSX cell text was truncated at the configured extraction limit",
                                len(blocks) - 1 if blocks else None,
                            )
                        )
                        break
                    anchor = XlsxCellAnchor.from_text(
                        source_sha256=source_sha256,
                        extraction_profile_hash=profile,
                        sheet=sheet_name,
                        cell=cell_ref,
                        row=row,
                        column=column,
                        text=text,
                    )
                    blocks.append(ExtractedBlock(len(blocks), text, "xlsx_cell", 1.0, anchor))
                    total_chars += len(text)
                if warnings:
                    break
        finally:
            archive.close()
        if not blocks:
            raise extraction_failure(ErrorCode.NO_EXTRACTABLE_TEXT, "XLSX contains no extractable cell text")
        return ExtractionResult(
            source_sha256=source_sha256,
            media_type=MediaType.XLSX,
            parser_name=XLSX_PARSER_NAME,
            parser_version=XLSX_PARSER_VERSION,
            normalization_profile=NORMALIZATION_PROFILE,
            config_profile_hash=profile,
            blocks=tuple(blocks),
            warnings=tuple(warnings),
        ).validate_bounds(self._policy)

    @staticmethod
    def _parse_shared_strings(xml: bytes) -> tuple[str, ...]:
        root = _parse_xml(xml, label="XLSX shared strings")
        return tuple(
            _shared_string_text(node)
            for node in _children(root, _XLSX_NAMESPACES, "si")
        )

    @staticmethod
    def _sheet_parts(workbook_xml: bytes, rels_xml: bytes) -> tuple[tuple[str, str], ...]:
        workbook = _parse_xml(workbook_xml, label="XLSX workbook")
        rels = _parse_xml(rels_xml, label="XLSX workbook relationships")
        targets = {
            relation.get("Id"): relation.get("Target")
            for relation in _children(rels, _PKG_REL_NAMESPACES, "Relationship")
            if relation.get("Type") in _REL_TYPE_WORKSHEET
        }
        result: list[tuple[str, str]] = []
        workbook_namespace = _xml_namespace(workbook.tag)
        if workbook_namespace not in _XLSX_NAMESPACES:
            raise extraction_failure(
                ErrorCode.CORRUPT_DOCUMENT,
                "XLSX workbook namespace is unsupported",
            )
        sheets = _child(workbook, _XLSX_NAMESPACES, "sheets")
        if sheets is None:
            raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "XLSX workbook has no worksheets")
        for sheet in _children(sheets, _XLSX_NAMESPACES, "sheet"):
            name = normalize_text(sheet.get("name") or "").strip()
            relationship_id = next(
                (
                    value
                    for key, value in sheet.attrib.items()
                    if _xml_local_name(key) == "id"
                    and _xml_namespace(key) in _DOC_REL_NAMESPACES
                ),
                None,
            )
            target = targets.get(relationship_id)
            if not name or not target:
                raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "XLSX worksheet relationship is invalid")
            result.append((name[:128], _safe_relationship_target(target)))
        if not result:
            raise extraction_failure(ErrorCode.NO_EXTRACTABLE_TEXT, "XLSX workbook has no worksheets")
        return tuple(result)

    @staticmethod
    def _cell_value(cell: ElementTree.Element, shared_strings: tuple[str, ...]) -> str:
        cell_type = cell.get("t")
        if cell_type == "s":
            value_node = _child(cell, _XLSX_NAMESPACES, "v")
            raw_index = (value_node.text or "").strip() if value_node is not None else ""
            if not raw_index.isdigit() or int(raw_index) >= len(shared_strings):
                raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "XLSX shared string reference is invalid")
            return shared_strings[int(raw_index)].strip()
        if cell_type == "inlineStr":
            inline = _child(cell, _XLSX_NAMESPACES, "is")
            return _shared_string_text(inline) if inline is not None else ""
        value_node = _child(cell, _XLSX_NAMESPACES, "v")
        if value_node is not None and value_node.text:
            return normalize_text(value_node.text).strip()
        formula = _child(cell, _XLSX_NAMESPACES, "f")
        return normalize_text(formula.text or "").strip() if formula is not None else ""


class PptxExtractor:
    """Convert each slide to a PDF page and force screenshot OCR per page."""

    def __init__(
        self,
        *,
        backend: PdfBackend,
        ocr: OcrEngine | None,
        policy: ExtractionPolicy,
        converter: Callable[[bytes], bytes] | None = None,
    ) -> None:
        self._backend = backend
        self._ocr = ocr
        self._policy = policy
        self._converter = converter or self._convert_to_pdf

    def extract(self, data: bytes, *, source_sha256: str) -> ExtractionResult:
        # PPTX is also an OOXML ZIP package.  Apply the same archive expansion
        # limits before handing the bytes to the office converter.
        package = _open_archive(data, self._policy)
        package.close()
        pdf_data = self._converter(data)
        if not isinstance(pdf_data, bytes):
            raise extraction_failure(
                ErrorCode.CORRUPT_DOCUMENT,
                "PPTX converter returned an invalid PDF",
            )
        if len(pdf_data) > self._policy.max_input_bytes:
            raise extraction_failure(
                ErrorCode.OUTPUT_TOO_LARGE,
                "converted PPTX PDF exceeds configured limit",
            )
        return PdfExtractor(
            backend=self._backend,
            ocr=self._ocr,
            policy=self._policy,
            force_ocr=True,
            result_media_type=MediaType.PPTX,
            result_parser_name=PPTX_PARSER_NAME,
            result_parser_version=PPTX_PARSER_VERSION,
        ).extract(pdf_data, source_sha256=source_sha256)

    def _convert_to_pdf(self, data: bytes) -> bytes:
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if soffice is None:
            raise extraction_failure(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                "PPTX PDF converter is unavailable",
            )
        with tempfile.TemporaryDirectory(prefix="axit-pptx-") as temporary:
            root = os.path.abspath(temporary)
            input_path = os.path.join(root, "source.pptx")
            output_dir = os.path.join(root, "output")
            profile_dir = os.path.join(root, "profile")
            os.makedirs(output_dir)
            os.makedirs(profile_dir)
            with open(input_path, "xb") as staged:
                staged.write(data)
            environment = {
                "PATH": os.environ.get("PATH", os.defpath),
                "HOME": root,
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
            }
            command = [
                soffice,
                "--headless",
                "--nologo",
                "--nodefault",
                "--nolockcheck",
                f"-env:UserInstallation=file://{profile_dir}",
                "--convert-to",
                "pdf",
                "--outdir",
                output_dir,
                input_path,
            ]
            try:
                completed = subprocess.run(
                    command,
                    cwd=root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    # Conversion diagnostics are intentionally discarded: the
                    # parser envelope must never expose unbounded office logs.
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=max(1.0, self._policy.ocr_timeout_seconds),
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise extraction_failure(ErrorCode.OCR_TIMEOUT, "PPTX PDF conversion timed out") from None
            except OSError:
                raise extraction_failure(ErrorCode.DEPENDENCY_UNAVAILABLE, "PPTX PDF converter is unavailable") from None
            if completed.returncode != 0:
                raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "PPTX could not be converted to PDF")
            candidates = [
                os.path.join(output_dir, entry)
                for entry in os.listdir(output_dir)
                if entry.lower().endswith(".pdf")
            ]
            if len(candidates) != 1:
                raise extraction_failure(ErrorCode.CORRUPT_DOCUMENT, "PPTX conversion did not produce one PDF")
            with open(candidates[0], "rb") as converted:
                pdf_data = converted.read(self._policy.max_input_bytes + 1)
            if len(pdf_data) > self._policy.max_input_bytes:
                raise extraction_failure(ErrorCode.OUTPUT_TOO_LARGE, "converted PPTX PDF exceeds configured limit")
            return pdf_data


__all__ = [
    "PPTX_PARSER_NAME",
    "PPTX_PARSER_VERSION",
    "XLSX_PARSER_NAME",
    "XLSX_PARSER_VERSION",
    "PptxExtractor",
    "XlsxExtractor",
]
