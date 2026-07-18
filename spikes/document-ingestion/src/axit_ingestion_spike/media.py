"""Strict input byte limits and magic/extension agreement checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from axit_ingestion_spike.models import (
    ErrorCode,
    ExtractionPolicy,
    MediaType,
    extraction_failure,
)


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_PNG_IEND = b"\x00\x00\x00\x00IEND\xaeB`\x82"
_EXTENSIONS: dict[str, MediaType] = {
    ".pdf": MediaType.PDF,
    ".png": MediaType.PNG,
    ".jpg": MediaType.JPEG,
    ".jpeg": MediaType.JPEG,
    ".hwp": MediaType.HWP,
    ".hwpx": MediaType.HWPX,
}


@dataclass(frozen=True, slots=True)
class MediaInfo:
    media_type: MediaType
    extension: str | None


def _media_from_magic(data: bytes) -> MediaType | None:
    if data.startswith(b"%PDF-"):
        return MediaType.PDF
    if data.startswith(_PNG_MAGIC):
        return MediaType.PNG
    if data.startswith(_JPEG_MAGIC):
        return MediaType.JPEG
    if data.startswith(_OLE_MAGIC):
        return MediaType.HWP
    if data.startswith(_ZIP_MAGICS):
        return MediaType.HWPX
    return None


def _extension(filename: str | None) -> str | None:
    if filename is None:
        return None
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    return suffix or None


def inspect_input(
    data: bytes,
    filename: str | None,
    policy: ExtractionPolicy,
) -> MediaInfo:
    """Reject empty, oversized, unknown, and extension-spoofed input before parsing."""

    if not isinstance(data, bytes):
        raise TypeError("document data must be bytes")
    if not data:
        raise extraction_failure(ErrorCode.EMPTY_INPUT, "input document is empty")
    if len(data) > policy.max_input_bytes:
        raise extraction_failure(
            ErrorCode.INPUT_TOO_LARGE,
            "input exceeds configured byte limit",
        )

    magic_type = _media_from_magic(data)
    suffix = _extension(filename)
    extension_type = _EXTENSIONS.get(suffix) if suffix is not None else None
    if magic_type is None:
        raise extraction_failure(
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            "input magic is not a supported document type",
        )
    if suffix is not None and extension_type is None:
        raise extraction_failure(
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            "filename extension is not supported",
        )
    if extension_type is not None and extension_type is not magic_type:
        raise extraction_failure(
            ErrorCode.TYPE_MISMATCH,
            "filename extension does not match input magic",
        )
    if magic_type is MediaType.HWPX and extension_type is not MediaType.HWPX:
        raise extraction_failure(
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            "ZIP input must be explicitly identified as HWPX",
        )
    if magic_type is MediaType.PNG and not data.endswith(_PNG_IEND):
        raise extraction_failure(
            ErrorCode.CORRUPT_DOCUMENT,
            "PNG input is truncated or contains trailing polyglot data",
        )
    if magic_type is MediaType.JPEG and not data.endswith(b"\xff\xd9"):
        raise extraction_failure(
            ErrorCode.CORRUPT_DOCUMENT,
            "JPEG input is truncated or contains trailing polyglot data",
        )
    return MediaInfo(magic_type, suffix)


__all__ = ["MediaInfo", "MediaType", "inspect_input"]
