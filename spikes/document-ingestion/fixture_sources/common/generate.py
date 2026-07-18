"""Generate deterministic, repository-authored PDF/image/adversarial fixtures.

The generator intentionally does not use office suites or proprietary documents.
Pillow rasterizes a committed OFL font; PDF and ZIP containers are serialized by
this module with fixed identifiers, object order, timestamps, and compression.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import struct
import unicodedata
import zlib
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable, Optional
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

from fixture_text import CLEAN_LINES, LOW_CONFIDENCE_LINES, TEXT_PDF_LINES, nfc_text


HERE = Path(__file__).resolve().parent
FONT_PATH = HERE / "font" / "NotoSansKR-FixtureSubset.ttf"
FIXTURE_LICENSE = "CC0-1.0"
FONT_LICENSE = "OFL-1.1"
FONT_SOURCE_URL = (
    "https://raw.githubusercontent.com/notofonts/noto-cjk/Sans2.004/"
    "Sans/Variable/TTF/Subset/NotoSansKR-VF.ttf"
)
FONT_SOURCE_SHA256 = "9e1d729e7e2b36f9ef439da102f8c134c10aabe46f1c843bf0aca5c043b86f76"
FONT_SUBSET_SHA256 = "a2c4986eabb2296fe733b90c4a6c8911c1c7bf7dd6d2b47675139e1afa0eb1bb"
FONT_LICENSE_SHA256 = "6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2"
GENERATOR_IMAGE = "axit-g0-fixture-generator:python3.12.11-pillow11.3.0"
GENERATOR_COMMAND = (
    "pwsh -NoProfile -File "
    "spikes/document-ingestion/fixture_sources/common/regenerate.ps1"
)
METADATA_PATH = HERE / "metadata.v1.json"

_PDF_PASSWORD_PADDING = bytes.fromhex(
    "28bf4e5e4e758a4164004e56fffa01082e2e00b6d0683e802f0ca9fe6453697a"
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=False, compress_level=9)


def _save_jpeg(
    image: Image.Image,
    path: Path,
    *,
    quality: int,
    exif: Optional[Image.Exif] = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    save_options: dict[str, object] = {
        "format": "JPEG",
        "quality": quality,
        "subsampling": 0,
        "optimize": False,
        "progressive": False,
    }
    if exif is not None:
        save_options["exif"] = exif
    image.save(path, **save_options)


def _render_clean_image() -> Image.Image:
    image = Image.new("RGB", (1800, 1000), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT_PATH), size=72)
    draw.rounded_rectangle(
        (42, 42, 1758, 958), radius=24, outline=(35, 52, 70), width=4
    )
    y = 120
    for line in CLEAN_LINES:
        draw.text((105, y), line, font=font, fill=(12, 12, 12))
        y += 190
    return image


def _render_low_confidence_upright() -> Image.Image:
    width, height = (960, 480)
    image = Image.new("L", (width, height), 232)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT_PATH), size=40)
    draw.text((135, 145), LOW_CONFIDENCE_LINES[0], font=font, fill=98)
    draw.text((190, 255), LOW_CONFIDENCE_LINES[1], font=font, fill=108)
    image = image.filter(ImageFilter.GaussianBlur(radius=1.35))

    rng = random.Random(0xA71_600D)
    pixels = bytearray(image.tobytes())
    for index, value in enumerate(pixels):
        noise = rng.randint(-34, 34)
        pixels[index] = min(255, max(0, value + noise))
    noisy = Image.frombytes("L", image.size, bytes(pixels))
    return noisy.convert("RGB")


@dataclass(frozen=True)
class _TtfMetrics:
    units_per_em: int
    ascent: int
    descent: int
    bbox: tuple[int, int, int, int]
    cmap: dict[int, int]
    advances: tuple[int, ...]


def _ttf_tables(data: bytes) -> dict[str, tuple[int, int]]:
    if len(data) < 12:
        raise ValueError("truncated TTF")
    num_tables = struct.unpack_from(">H", data, 4)[0]
    result: dict[str, tuple[int, int]] = {}
    for index in range(num_tables):
        offset = 12 + index * 16
        tag, _checksum, table_offset, length = struct.unpack_from(
            ">4sIII", data, offset
        )
        result[tag.decode("ascii")] = (table_offset, length)
    return result


def _parse_cmap_format4(data: bytes, offset: int) -> dict[int, int]:
    seg_count = struct.unpack_from(">H", data, offset + 6)[0] // 2
    end_codes_offset = offset + 14
    start_codes_offset = end_codes_offset + 2 * seg_count + 2
    deltas_offset = start_codes_offset + 2 * seg_count
    ranges_offset = deltas_offset + 2 * seg_count
    cmap: dict[int, int] = {}
    for segment in range(seg_count):
        end = struct.unpack_from(">H", data, end_codes_offset + 2 * segment)[0]
        start = struct.unpack_from(">H", data, start_codes_offset + 2 * segment)[0]
        delta = struct.unpack_from(">h", data, deltas_offset + 2 * segment)[0]
        range_word_offset = ranges_offset + 2 * segment
        range_offset = struct.unpack_from(">H", data, range_word_offset)[0]
        if start == 0xFFFF and end == 0xFFFF:
            continue
        for codepoint in range(start, end + 1):
            if range_offset == 0:
                glyph_id = (codepoint + delta) & 0xFFFF
            else:
                glyph_offset = (
                    range_word_offset + range_offset + 2 * (codepoint - start)
                )
                if glyph_offset + 2 > len(data):
                    raise ValueError("invalid cmap glyph offset")
                glyph_id = struct.unpack_from(">H", data, glyph_offset)[0]
                if glyph_id:
                    glyph_id = (glyph_id + delta) & 0xFFFF
            if glyph_id:
                cmap[codepoint] = glyph_id
    return cmap


def _parse_cmap_format12(data: bytes, offset: int) -> dict[int, int]:
    group_count = struct.unpack_from(">I", data, offset + 12)[0]
    cmap: dict[int, int] = {}
    for index in range(group_count):
        start, end, start_glyph = struct.unpack_from(
            ">III", data, offset + 16 + 12 * index
        )
        if end > 0xFFFF:
            end = 0xFFFF
        for codepoint in range(start, end + 1):
            cmap[codepoint] = start_glyph + codepoint - start
    return cmap


def _parse_ttf(data: bytes) -> _TtfMetrics:
    tables = _ttf_tables(data)
    head_offset, _ = tables["head"]
    hhea_offset, _ = tables["hhea"]
    maxp_offset, _ = tables["maxp"]
    hmtx_offset, _ = tables["hmtx"]
    cmap_offset, _ = tables["cmap"]

    units_per_em = struct.unpack_from(">H", data, head_offset + 18)[0]
    bbox = struct.unpack_from(">hhhh", data, head_offset + 36)
    ascent, descent = struct.unpack_from(">hh", data, hhea_offset + 4)
    hmetrics_count = struct.unpack_from(">H", data, hhea_offset + 34)[0]
    glyph_count = struct.unpack_from(">H", data, maxp_offset + 4)[0]
    advances = [
        struct.unpack_from(">H", data, hmtx_offset + index * 4)[0]
        for index in range(hmetrics_count)
    ]
    advances.extend([advances[-1]] * (glyph_count - hmetrics_count))

    subtable_count = struct.unpack_from(">H", data, cmap_offset + 2)[0]
    choices: list[tuple[int, int, int]] = []
    for index in range(subtable_count):
        platform, encoding, relative_offset = struct.unpack_from(
            ">HHI", data, cmap_offset + 4 + 8 * index
        )
        subtable_offset = cmap_offset + relative_offset
        format_number = struct.unpack_from(">H", data, subtable_offset)[0]
        priority = 0
        if (platform, encoding, format_number) == (3, 10, 12):
            priority = 3
        elif platform == 0 and format_number == 12:
            priority = 2
        elif format_number == 4 and platform in (0, 3):
            priority = 1
        if priority:
            choices.append((priority, format_number, subtable_offset))
    if not choices:
        raise ValueError("font has no supported Unicode cmap")
    _, cmap_format, selected_offset = max(choices)
    cmap = (
        _parse_cmap_format12(data, selected_offset)
        if cmap_format == 12
        else _parse_cmap_format4(data, selected_offset)
    )
    return _TtfMetrics(
        units_per_em=units_per_em,
        ascent=ascent,
        descent=descent,
        bbox=bbox,
        cmap=cmap,
        advances=tuple(advances),
    )


def _pdf_stream(data: bytes, *, extra: bytes = b"") -> bytes:
    prefix = b"<< /Length " + str(len(data)).encode("ascii")
    if extra:
        prefix += b" " + extra
    return prefix + b" >>\nstream\n" + data + b"\nendstream"


def _serialize_pdf(
    objects: Iterable[bytes],
    *,
    trailer_extra: bytes = b"",
    file_id: Optional[bytes] = None,
) -> bytes:
    object_list = list(objects)
    output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_number, payload in enumerate(object_list, start=1):
        offsets.append(len(output))
        output.extend(f"{object_number} 0 obj\n".encode("ascii"))
        output.extend(payload)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(object_list) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    if file_id is None:
        file_id = hashlib.md5(bytes(output), usedforsecurity=False).digest()
    trailer = f"<< /Size {len(object_list) + 1} /Root 1 0 R".encode("ascii")
    if trailer_extra:
        trailer += b" " + trailer_extra
    trailer += (
        b" /ID [<"
        + file_id.hex().encode("ascii")
        + b"><"
        + file_id.hex().encode("ascii")
        + b">] >>"
    )
    output.extend(b"trailer\n" + trailer + b"\nstartxref\n")
    output.extend(str(xref_offset).encode("ascii") + b"\n%%EOF\n")
    return bytes(output)


def _pdf_number(value: float) -> str:
    rounded = round(value, 3)
    text = f"{rounded:.3f}".rstrip("0").rstrip(".")
    return text if text != "-0" else "0"


def _build_text_pdf(font_bytes: bytes) -> bytes:
    metrics = _parse_ttf(font_bytes)
    used_characters = sorted(
        {character for line in TEXT_PDF_LINES for character in line}
    )
    used_codepoints = [ord(character) for character in used_characters]
    missing = [
        codepoint for codepoint in used_codepoints if codepoint not in metrics.cmap
    ]
    if missing:
        raise ValueError(f"subset font is missing codepoints: {missing!r}")
    if any(codepoint > 0xFFFF for codepoint in used_codepoints):
        raise ValueError("fixture PDF supports only BMP codepoints")

    # Use compact sequential CIDs rather than Unicode codepoints as CIDs.  Some
    # PDF engines otherwise apply a legacy Korean character collection fallback
    # before consulting ToUnicode, yielding CP949 mojibake even though the page
    # renders correctly.  The explicit CID -> Unicode and CID -> glyph maps make
    # text extraction and rendering agree across PDFium and other readers.
    character_to_cid = {
        character: index for index, character in enumerate(used_characters, start=1)
    }

    content_lines = [b"BT\n/F1 24 Tf\n"]
    for index, line in enumerate(TEXT_PDF_LINES):
        encoded = "".join(f"{character_to_cid[character]:04X}" for character in line)
        y = 735 - index * 64
        content_lines.append(f"1 0 0 1 56 {y} Tm\n<{encoded}> Tj\n".encode("ascii"))
    content_lines.append(b"ET\n")
    content = b"".join(content_lines)

    units = metrics.units_per_em
    width_parts: list[str] = []
    cid_to_gid = bytearray((len(used_characters) + 1) * 2)
    for character in used_characters:
        codepoint = ord(character)
        cid = character_to_cid[character]
        glyph_id = metrics.cmap[codepoint]
        struct.pack_into(">H", cid_to_gid, cid * 2, glyph_id)
        width = round(metrics.advances[glyph_id] * 1000 / units)
        width_parts.append(f"{cid} [{width}]")

    bbox = [round(value * 1000 / units) for value in metrics.bbox]
    ascent = round(metrics.ascent * 1000 / units)
    descent = round(metrics.descent * 1000 / units)

    bfchar_lines = [
        f"<{character_to_cid[character]:04X}> <{ord(character):04X}>"
        for character in used_characters
    ]
    cmap = (
        "/CIDInit /ProcSet findresource begin\n"
        "12 dict begin\n"
        "begincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /AXitFixtureToUnicode def\n"
        "/CMapType 2 def\n"
        "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        f"{len(bfchar_lines)} beginbfchar\n"
        + "\n".join(bfchar_lines)
        + "\nendbfchar\nendcmap\n"
        "CMapName currentdict /CMap defineresource pop\n"
        "end\nend\n"
    ).encode("ascii")

    cid_map_compressed = zlib.compress(bytes(cid_to_gid), level=9)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        _pdf_stream(content),
        (
            b"<< /Type /Font /Subtype /Type0 /BaseFont /AXitFixtureSansKR "
            b"/Encoding /Identity-H /DescendantFonts [6 0 R] /ToUnicode 9 0 R >>"
        ),
        (
            b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /AXitFixtureSansKR "
            b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
            b"/FontDescriptor 7 0 R /DW 1000 /W ["
            + " ".join(width_parts).encode("ascii")
            + b"] /CIDToGIDMap 10 0 R >>"
        ),
        (
            b"<< /Type /FontDescriptor /FontName /AXitFixtureSansKR /Flags 4 "
            + f"/FontBBox [{' '.join(map(str, bbox))}] /ItalicAngle 0 ".encode("ascii")
            + f"/Ascent {ascent} /Descent {descent} /CapHeight {ascent} ".encode(
                "ascii"
            )
            + b"/StemV 80 /FontFile2 8 0 R >>"
        ),
        _pdf_stream(
            font_bytes, extra=b"/Length1 " + str(len(font_bytes)).encode("ascii")
        ),
        _pdf_stream(cmap),
        _pdf_stream(cid_map_compressed, extra=b"/Filter /FlateDecode"),
    ]
    return _serialize_pdf(objects)


def _build_scanned_pdf(image: Image.Image) -> bytes:
    rgb = image.convert("RGB")
    raw = rgb.tobytes()
    compressed = zlib.compress(raw, level=9)
    display_width = 539.0
    display_height = display_width * rgb.height / rgb.width
    content = (
        "q\n"
        f"{_pdf_number(display_width)} 0 0 {_pdf_number(display_height)} 28 271 cm\n"
        "/Im0 Do\nQ\n"
    ).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>"
        ),
        _pdf_stream(content),
        _pdf_stream(
            compressed,
            extra=(
                f"/Type /XObject /Subtype /Image /Width {rgb.width} /Height {rgb.height} "
                "/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode"
            ).encode("ascii"),
        ),
    ]
    return _serialize_pdf(objects)


def _build_oversized_page_pdf() -> bytes:
    """Valid text-free PDF whose 300 DPI bitmap would exceed the 25 MP bound."""

    return _serialize_pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R "
                b"/MediaBox [0 0 100000 100000] /Contents 4 0 R >>"
            ),
            _pdf_stream(b""),
        ]
    )


def _rc4(key: bytes, data: bytes) -> bytes:
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) & 0xFF
        state[i], state[j] = state[j], state[i]
    i = 0
    j = 0
    output = bytearray()
    for value in data:
        i = (i + 1) & 0xFF
        j = (j + state[i]) & 0xFF
        state[i], state[j] = state[j], state[i]
        output.append(value ^ state[(state[i] + state[j]) & 0xFF])
    return bytes(output)


def _padded_password(password: str) -> bytes:
    encoded = password.encode("latin-1")[:32]
    return (encoded + _PDF_PASSWORD_PADDING)[:32]


def _build_encrypted_pdf() -> bytes:
    user_password = "fixture-user"
    owner_password = "fixture-owner"
    user_pad = _padded_password(user_password)
    owner_pad = _padded_password(owner_password)
    owner_key = hashlib.md5(owner_pad, usedforsecurity=False).digest()[:5]
    owner_value = _rc4(owner_key, user_pad)
    permissions = -4
    file_id = hashlib.md5(b"AXit encrypted fixture v1", usedforsecurity=False).digest()
    file_key = hashlib.md5(
        user_pad + owner_value + struct.pack("<i", permissions) + file_id,
        usedforsecurity=False,
    ).digest()[:5]
    user_value = _rc4(file_key, _PDF_PASSWORD_PADDING)

    plain_content = b"q\n0.15 0.25 0.35 rg\n72 720 180 36 re f\nQ\n"
    object_key = hashlib.md5(
        file_key + (4).to_bytes(3, "little") + b"\x00\x00",
        usedforsecurity=False,
    ).digest()[:10]
    encrypted_content = _rc4(object_key, plain_content)
    encryption_dictionary = (
        b"<< /Filter /Standard /V 1 /R 2 /Length 40 "
        b"/O <" + owner_value.hex().encode("ascii") + b"> "
        b"/U <" + user_value.hex().encode("ascii") + b"> "
        b"/P " + str(permissions).encode("ascii") + b" >>"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>",
        _pdf_stream(encrypted_content),
        encryption_dictionary,
    ]
    return _serialize_pdf(objects, trailer_extra=b"/Encrypt 5 0 R", file_id=file_id)


def _zip_info(name: str, compression: int) -> ZipInfo:
    info = ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = compression
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _make_zip(entries: tuple[tuple[str, bytes, int], ...]) -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    with ZipFile(buffer, "w", allowZip64=False) as archive:
        for name, data, compression in entries:
            archive.writestr(
                _zip_info(name, compression),
                data,
                compress_type=compression,
                compresslevel=9 if compression == ZIP_DEFLATED else None,
            )
    return buffer.getvalue()


def _fixture_entry(
    output_root: Path,
    relative_path: str,
    *,
    classification: str,
    media_type: str,
    expected: dict[str, object],
) -> dict[str, object]:
    data = (output_root / relative_path).read_bytes()
    exact_expected = dict(expected)
    expected_text = exact_expected.get("text_nfc")
    if expected_text is not None:
        if not isinstance(expected_text, str):
            raise TypeError("expected text_nfc must be a string")
        if _nfc(expected_text) != expected_text:
            raise ValueError("expected text_nfc must already use Unicode NFC")
        exact_expected["normalization_profile"] = "nfc-lf-v1"
        exact_expected["text_nfc_sha256"] = _sha256(expected_text.encode("utf-8"))
    return {
        "path": relative_path,
        "classification": classification,
        "media_type": media_type,
        "size_bytes": len(data),
        "sha256": _sha256(data),
        "expected": exact_expected,
        "provenance": {
            "generated_by_repository": True,
            "redistributable": True,
            "content_license": FIXTURE_LICENSE,
            "copyrighted_source_document": False,
        },
        "generation_command": GENERATOR_COMMAND,
    }


def generate(
    output_root: Path,
    *,
    metadata_path: Path = METADATA_PATH,
) -> dict[str, object]:
    if _sha256(FONT_PATH.read_bytes()) != FONT_SUBSET_SHA256:
        raise SystemExit("committed fixture font hash does not match the pinned subset")

    clean = _render_clean_image()
    _save_png(clean, output_root / "images/korean-clean.png")
    _save_jpeg(clean, output_root / "images/korean-clean.jpg", quality=95)

    low_confidence = _render_low_confidence_upright()
    stored = low_confidence.transpose(Image.Transpose.ROTATE_90)
    orientation = Image.Exif()
    orientation[274] = 6
    _save_jpeg(
        stored,
        output_root / "images/rotated-low-confidence.jpg",
        quality=54,
        exif=orientation,
    )

    font_bytes = FONT_PATH.read_bytes()
    _write(output_root / "pdf/text-korean.pdf", _build_text_pdf(font_bytes))
    _write(output_root / "pdf/scanned-korean.pdf", _build_scanned_pdf(clean))
    _write(output_root / "malicious/encrypted.pdf", _build_encrypted_pdf())

    zip_bomb_xml = (
        b"<?xml version='1.0'?><section>" + b"A" * (4 * 1024 * 1024) + b"</section>"
    )
    zip_bomb = _make_zip(
        (
            ("mimetype", b"application/hwp+zip", ZIP_STORED),
            ("Contents/section0.xml", zip_bomb_xml, ZIP_DEFLATED),
        )
    )
    _write(output_root / "malicious/zip-bomb.hwpx", zip_bomb)

    xxe_xml = (
        b"<?xml version='1.0' encoding='UTF-8'?>\n"
        b"<!DOCTYPE section [<!ENTITY xxe SYSTEM "
        b"'http://169.254.169.254/latest/meta-data/'>]>\n"
        b"<section xmlns='http://www.hancom.co.kr/hwpml/2011/section'>"
        b"<p><run><t>&xxe;</t></run></p></section>"
    )
    xxe = _make_zip(
        (
            ("mimetype", b"application/hwp+zip", ZIP_STORED),
            ("Contents/section0.xml", xxe_xml, ZIP_DEFLATED),
        )
    )
    _write(output_root / "malicious/xxe.hwpx", xxe)

    traversal = _make_zip(
        (
            ("mimetype", b"application/hwp+zip", ZIP_STORED),
            ("../escape.xml", b"<escape>must-not-extract</escape>", ZIP_DEFLATED),
        )
    )
    _write(output_root / "malicious/path-traversal.hwpx", traversal)

    corrupt_png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 64) + b"IHDR" + b"truncated"
    _write(output_root / "malicious/corrupt-image.png", corrupt_png)

    polyglot_zip = _make_zip((("payload.txt", b"not an image payload", ZIP_DEFLATED),))
    clean_jpeg = (output_root / "images/korean-clean.jpg").read_bytes()
    _write(output_root / "malicious/polyglot-image.jpg", clean_jpeg + polyglot_zip)

    corrupt_pdf = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 99 0 R >>\nendobj\n"
    _write(output_root / "malicious/corrupt.pdf", corrupt_pdf)
    _write(
        output_root / "malicious/oversized-page.pdf",
        _build_oversized_page_pdf(),
    )

    entries = [
        _fixture_entry(
            output_root,
            "pdf/text-korean.pdf",
            classification="golden",
            media_type="application/pdf",
            expected={
                "anchor_kind": "pdf_block",
                "has_text_layer": True,
                "text_nfc": nfc_text(TEXT_PDF_LINES),
            },
        ),
        _fixture_entry(
            output_root,
            "pdf/scanned-korean.pdf",
            classification="golden",
            media_type="application/pdf",
            expected={
                "anchor_kind": "pdf_block",
                "text_nfc": nfc_text(CLEAN_LINES),
                "min_ocr_accuracy": 0.9,
                "image_only": True,
            },
        ),
        _fixture_entry(
            output_root,
            "images/korean-clean.png",
            classification="golden",
            media_type="image/png",
            expected={
                "anchor_kind": "image_bbox",
                "text_nfc": nfc_text(CLEAN_LINES),
                "min_ocr_accuracy": 0.9,
            },
        ),
        _fixture_entry(
            output_root,
            "images/korean-clean.jpg",
            classification="golden",
            media_type="image/jpeg",
            expected={
                "anchor_kind": "image_bbox",
                "text_nfc": nfc_text(CLEAN_LINES),
                "min_ocr_accuracy": 0.9,
            },
        ),
        _fixture_entry(
            output_root,
            "images/rotated-low-confidence.jpg",
            classification="golden",
            media_type="image/jpeg",
            expected={
                "anchor_kind": "image_bbox",
                "text_nfc": nfc_text(LOW_CONFIDENCE_LINES),
                "required_warning": "LOW_CONFIDENCE",
                "exif_orientation": 6,
                "required_anchor_bbox": [0, 0, 1, 0.060417],
            },
        ),
        _fixture_entry(
            output_root,
            "malicious/encrypted.pdf",
            classification="malicious",
            media_type="application/pdf",
            expected={"error_code": "ENCRYPTED_DOCUMENT", "password": "fixture-user"},
        ),
        _fixture_entry(
            output_root,
            "malicious/zip-bomb.hwpx",
            classification="malicious",
            media_type="application/x-hwpx",
            expected={
                "error_code": "ZIP_EXPANSION_LIMIT",
                "min_compression_ratio": 100,
            },
        ),
        _fixture_entry(
            output_root,
            "malicious/xxe.hwpx",
            classification="malicious",
            media_type="application/x-hwpx",
            expected={"error_code": "XML_DTD_FORBIDDEN"},
        ),
        _fixture_entry(
            output_root,
            "malicious/path-traversal.hwpx",
            classification="malicious",
            media_type="application/x-hwpx",
            expected={
                "error_code": "CORRUPT_DOCUMENT",
                "forbidden_entry": "../escape.xml",
            },
        ),
        _fixture_entry(
            output_root,
            "malicious/corrupt-image.png",
            classification="malicious",
            media_type="image/png",
            expected={"error_code": "CORRUPT_DOCUMENT"},
        ),
        _fixture_entry(
            output_root,
            "malicious/polyglot-image.jpg",
            classification="malicious",
            media_type="image/jpeg",
            expected={"error_code": "CORRUPT_DOCUMENT", "contains_appended_zip": True},
        ),
        _fixture_entry(
            output_root,
            "malicious/corrupt.pdf",
            classification="malicious",
            media_type="application/pdf",
            expected={"error_code": "CORRUPT_DOCUMENT"},
        ),
        _fixture_entry(
            output_root,
            "malicious/oversized-page.pdf",
            classification="malicious",
            media_type="application/pdf",
            expected={
                "error_code": "IMAGE_PIXEL_LIMIT",
                "media_box_points": [100000, 100000],
                "render_dpi": 300,
            },
        ),
    ]

    metadata = {
        "schema_version": 1,
        "content_license": FIXTURE_LICENSE,
        "generator": {
            "path": "spikes/document-ingestion/fixture_sources/common/generate.py",
            "command": GENERATOR_COMMAND,
            "container_image": GENERATOR_IMAGE,
            "platform": "linux/amd64",
            "python": platform.python_version(),
            "pillow": Image.__version__,
            "freetype": features.version_module("freetype2"),
            "jpeg_codec": features.version_codec("jpg"),
            "libjpeg_turbo": features.version_feature("libjpeg_turbo"),
            "pillow_zlib_codec": features.version_codec("zlib"),
            "python_zlib": zlib.ZLIB_VERSION,
            "random_seed": "0xA71600D",
            "timestamps": "fixed-or-omitted",
        },
        "font": {
            "path": "spikes/document-ingestion/fixture_sources/common/font/NotoSansKR-FixtureSubset.ttf",
            "license": FONT_LICENSE,
            "license_file": "spikes/document-ingestion/fixture_sources/common/font/OFL.txt",
            "license_sha256": FONT_LICENSE_SHA256,
            "upstream_version": "Noto Sans KR 2.004 (Sans2.004 tag)",
            "upstream_url": FONT_SOURCE_URL,
            "upstream_sha256": FONT_SOURCE_SHA256,
            "subset_sha256": FONT_SUBSET_SHA256,
            "subset_tool": "fonttools==4.59.2",
            "subset_platform": "linux/amd64",
            "subset_tool_wheel_sha256": (
                "738f31f23e0339785fd67652a94bc69ea49e413dfdb14dcb8c8ff383d249464e"
            ),
            "subset_recipe": (
                "spikes/document-ingestion/fixture_sources/common/font-build.Dockerfile"
            ),
            "deterministic_rebuild_verified": True,
            "subset_command": (
                "pwsh -NoProfile -File spikes/document-ingestion/fixture_sources/"
                "common/verify-font-rebuild.ps1"
            ),
        },
        "fixtures": entries,
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_bytes(
        (
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
    )
    return metadata


def verify_existing(output_root: Path) -> None:
    """Regenerate in an empty directory and compare every owned byte."""

    if not METADATA_PATH.is_file():
        raise SystemExit(f"missing committed metadata: {METADATA_PATH}")
    committed_metadata = METADATA_PATH.read_bytes()
    with TemporaryDirectory(prefix="axit-fixture-regeneration-") as temporary:
        temporary_root = Path(temporary)
        staged_root = temporary_root / "fixtures"
        staged_metadata = temporary_root / "metadata.v1.json"
        generated = generate(staged_root, metadata_path=staged_metadata)

        mismatches: list[str] = []
        fixtures = generated.get("fixtures")
        if not isinstance(fixtures, list):
            raise TypeError("generated fixture metadata must be a list")
        for entry in fixtures:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise TypeError("generated fixture entry has an invalid path")
            relative_path = entry["path"]
            committed_path = output_root / relative_path
            staged_path = staged_root / relative_path
            if not committed_path.is_file():
                mismatches.append(f"missing: {relative_path}")
                continue
            if committed_path.read_bytes() != staged_path.read_bytes():
                mismatches.append(f"byte mismatch: {relative_path}")
        if committed_metadata != staged_metadata.read_bytes():
            mismatches.append("byte mismatch: metadata.v1.json")
        if mismatches:
            raise SystemExit("regeneration check failed:\n- " + "\n- ".join(mismatches))
        print(
            f"byte-for-byte regeneration verified for {len(fixtures)} fixtures and metadata"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="fixture root containing pdf/, images/, and malicious/",
    )
    parser.add_argument(
        "--verify-existing",
        action="store_true",
        help="regenerate in an empty temporary directory and compare owned bytes",
    )
    args = parser.parse_args()
    if args.verify_existing:
        verify_existing(args.output_root.resolve())
        return
    metadata = generate(args.output_root.resolve())
    for entry in metadata["fixtures"]:
        print(f"{entry['sha256']}  {entry['path']}")


if __name__ == "__main__":
    main()
