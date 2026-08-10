from __future__ import annotations

import hashlib
import io
import zipfile

from axit_ingestion_spike.docx import DocxExtractor
from axit_ingestion_spike.models import ExtractionPolicy


def test_docx_core_properties_are_extracted_as_cited_metadata_blocks() -> None:
    document = b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Body</w:t></w:r></w:p></w:body></w:document>'
    core = b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Meeting Plan</dc:title><dc:creator>Alice</dc:creator></cp:coreProperties>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("docProps/core.xml", core)
    payload = buffer.getvalue()

    result = DocxExtractor(policy=ExtractionPolicy()).extract(
        payload, source_sha256=hashlib.sha256(payload).hexdigest()
    )

    assert [(block.block_type, block.text) for block in result.blocks] == [
        ("docx_metadata", "title: Meeting Plan"),
        ("docx_metadata", "creator: Alice"),
        ("docx_paragraph", "Body"),
    ]
    assert result.blocks[-1].anchor.to_dict()["locator"]["paragraph"] == 0


def test_docx_core_properties_reject_dtd() -> None:
    document = b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Body</w:t></w:r></w:p></w:body></w:document>'
    core = b'<!DOCTYPE x [<!ENTITY leak "x">]><x>&leak;</x>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("docProps/core.xml", core)
    payload = buffer.getvalue()

    try:
        DocxExtractor(policy=ExtractionPolicy()).extract(
            payload, source_sha256=hashlib.sha256(payload).hexdigest()
        )
    except Exception as error:
        assert str(error) == "XML_DTD_FORBIDDEN"
    else:
        raise AssertionError("metadata DTD must fail closed")
