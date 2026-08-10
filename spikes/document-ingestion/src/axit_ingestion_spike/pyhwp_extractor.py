"""Pure-Python HWP 5.0 (classic binary/OLE2) extraction via pyhwp + olefile.

``hwplib`` (the pinned Java sidecar's HWP reader, see ``hwp.py``) bundles a
long-frozen, no-longer-maintained fork of an early Apache POI OLE2 reader.
Some real-world HWP 5.0 files have a small-block allocation table shape
that fork cannot open, even though the file is otherwise a well-formed
compound-file container. ``olefile`` (which pyhwp uses) is actively
maintained and reads those same files correctly.  This adapter walks
pyhwp's body-text event stream directly rather than its full document
pipeline, so a missing ``\\005HwpSummaryInformation`` stream (common in
minimal/synthetic HWP files) does not block extraction.
"""

from __future__ import annotations

import os
import tempfile
from importlib import metadata
from pathlib import Path
from typing import Any

from axit_ingestion_spike.anchors import HwpParagraphAnchor
from axit_ingestion_spike.models import (
    ErrorCode,
    ExtractedBlock,
    ExtractionPolicy,
    ExtractionResult,
    MediaType,
    extraction_failure,
)
from axit_ingestion_spike.normalization import NORMALIZATION_PROFILE, normalize_text

_PARSER_NAME = "pyhwp"


class _ParagraphFrame:
    __slots__ = ("parts", "context")

    def __init__(self, context: str) -> None:
        self.parts: list[str] = []
        self.context = context


class PyhwpExtractor:
    """Extract HWP 5.0 paragraphs/tables/footnotes using pyhwp + olefile."""

    def __init__(self, *, policy: ExtractionPolicy) -> None:
        self._policy = policy

    def extract(
        self,
        data: bytes,
        *,
        media_type: MediaType,
        source_sha256: str,
    ) -> ExtractionResult:
        if media_type is not MediaType.HWP:
            raise extraction_failure(
                ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                "pyhwp adapter only accepts HWP input",
            )
        try:
            from hwp5.dataio import ParseError
            from hwp5.errors import InvalidHwp5FileError, InvalidOleStorageError
            from hwp5.xmlmodel import Hwp5File
        except ImportError as error:
            raise extraction_failure(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                "pyhwp HWP parser is unavailable",
            ) from error

        broken_document_errors = (
            ParseError,
            InvalidHwp5FileError,
            InvalidOleStorageError,
            KeyError,
            IndexError,
            ValueError,
            OSError,
        )

        # ``delete=False`` + an explicit close before reopening: on Windows a
        # second handle (olefile's own ``open()``) cannot read a
        # NamedTemporaryFile while the writing handle is still held open.
        fd, staged_name = tempfile.mkstemp(suffix=".hwp")
        try:
            with os.fdopen(fd, "wb") as staged:
                staged.write(data)
            document = None
            try:
                document = Hwp5File(staged_name)
                blocks = self._walk(document, source_sha256=source_sha256)
            except broken_document_errors:
                raise extraction_failure(
                    ErrorCode.CORRUPT_DOCUMENT,
                    "HWP document could not be parsed safely",
                ) from None
            finally:
                closer = getattr(document, "close", None)
                if callable(closer):
                    closer()
        finally:
            # A file that failed to parse may have left an internal handle
            # open inside a partially constructed, unreachable pyhwp/olefile
            # object; Windows keeps such files locked until that handle is
            # released (process exit at the latest). Best-effort cleanup.
            try:
                Path(staged_name).unlink(missing_ok=True)
            except OSError:
                pass

        if not blocks:
            raise extraction_failure(
                ErrorCode.NO_EXTRACTABLE_TEXT,
                "HWP document contains no extractable text",
            )
        return ExtractionResult(
            source_sha256,
            MediaType.HWP,
            _PARSER_NAME,
            self._parser_version(),
            NORMALIZATION_PROFILE,
            self._policy.profile_hash,
            tuple(blocks),
        ).validate_bounds(self._policy)

    def _parser_version(self) -> str:
        try:
            return metadata.version("pyhwp")
        except metadata.PackageNotFoundError:
            return "unknown"

    def _walk(self, document: Any, *, source_sha256: str) -> list[ExtractedBlock]:
        profile = self._policy.profile_hash
        parser_version = self._parser_version()
        blocks: list[ExtractedBlock] = []

        paragraph_stack: list[_ParagraphFrame] = []
        container_stack: list[str] = []
        outer_paragraph = -1
        table_idx = row_idx = cell_idx = -1
        footnote_idx = -1
        cell_paragraph = footnote_paragraph = 0
        section = 0

        def emit(
            text: str,
            *,
            table: int | None = None,
            table_row: int | None = None,
            cell: int | None = None,
            cell_paragraph_value: int | None = None,
            footnote: int | None = None,
            footnote_paragraph_value: int | None = None,
        ) -> None:
            normalized = normalize_text(text)
            if not normalized:
                return
            kind = "table_cell" if table is not None else "footnote" if footnote is not None else "paragraph"
            anchor = HwpParagraphAnchor.from_text(
                source_sha256=source_sha256,
                extraction_profile_hash=profile,
                parser=_PARSER_NAME,
                parser_version=parser_version,
                section=section,
                paragraph=outer_paragraph,
                text=normalized,
                table=table,
                table_block=0 if table is not None else None,
                table_row=table_row,
                cell=cell,
                cell_paragraph=cell_paragraph_value,
                footnote=footnote,
                footnote_paragraph=footnote_paragraph_value,
            )
            blocks.append(ExtractedBlock(len(blocks), normalized, f"hwp_{kind}", None, anchor))

        for event_type, (cls, attrs, context) in document.bodytext.events():
            name = cls.__name__
            started = event_type.__name__ == "STARTEVENT"
            section = context.get("section_idx", section)

            if name == "Paragraph":
                if started:
                    ctx = container_stack[-1] if container_stack else "top"
                    if ctx == "top":
                        outer_paragraph += 1
                        table_idx = footnote_idx = -1
                    paragraph_stack.append(_ParagraphFrame(ctx))
                elif paragraph_stack:
                    frame = paragraph_stack.pop()
                    text = "".join(frame.parts)
                    if frame.context == "cell":
                        emit(
                            text,
                            table=table_idx,
                            table_row=row_idx,
                            cell=cell_idx,
                            cell_paragraph_value=cell_paragraph,
                        )
                        cell_paragraph += 1
                    elif frame.context == "footnote":
                        emit(text, footnote=footnote_idx, footnote_paragraph_value=footnote_paragraph)
                        footnote_paragraph += 1
                    elif frame.context == "top":
                        emit(text)
                    # else: a table's own caption paragraph (a direct child of
                    # TableControl, before TableBody/TableRow/TableCell) —
                    # hwplib's table model does not expose this either, so it
                    # is intentionally not emitted as a block.
            elif name == "Text":
                if started and paragraph_stack:
                    paragraph_stack[-1].parts.append(str(attrs.get("text", "")))
            elif name == "TableControl":
                if started:
                    table_idx += 1
                    row_idx = -1
                    container_stack.append("table")
                elif container_stack and container_stack[-1] == "table":
                    container_stack.pop()
            elif name == "TableRow":
                if started:
                    row_idx += 1
                    cell_idx = -1
            elif name == "TableCell":
                if started:
                    cell_idx += 1
                    cell_paragraph = 0
                    container_stack.append("cell")
                elif container_stack and container_stack[-1] == "cell":
                    container_stack.pop()
            elif name == "FootNote":
                if started:
                    footnote_idx += 1
                    footnote_paragraph = 0
                    container_stack.append("footnote")
                elif container_stack and container_stack[-1] == "footnote":
                    container_stack.pop()
        return blocks
