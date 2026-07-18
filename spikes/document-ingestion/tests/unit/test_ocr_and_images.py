from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO

import pytest

from axit_ingestion_spike.images import DecodedImage, ImageExtractor, PillowImageDecoder
from axit_ingestion_spike.media import MediaType
from axit_ingestion_spike.models import ErrorCode, ExtractionException, ExtractionPolicy
from axit_ingestion_spike.ocr import (
    CommandResult,
    OcrSpan,
    TesseractCli,
    parse_tesseract_tsv,
)


TSV = """level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext
5\t1\t1\t1\t1\t1\t10\t20\t30\t10\t90.0\t회의
5\t1\t1\t1\t1\t2\t45\t20\t40\t10\t80.0\t안건
5\t1\t1\t1\t2\t1\t10\t50\t20\t10\t-1\t
"""


class FakeImage:
    size = (100, 100)

    def save(self, destination: BinaryIO, *, format: str) -> None:
        assert format == "PNG"
        destination.write(b"encoded-png")


@dataclass
class FakeRunner:
    result: CommandResult
    calls: list[tuple[tuple[str, ...], bytes]]

    def run(
        self,
        args: tuple[str, ...],
        *,
        stdin: bytes,
        timeout_seconds: float,
        environment: dict[str, str],
    ) -> CommandResult:
        assert timeout_seconds > 0
        assert environment == {
            "HOME": "/tmp",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "OMP_THREAD_LIMIT": "1",
            "TMPDIR": "/tmp",
        }
        self.calls.append((args, stdin))
        return self.result


def test_tesseract_tsv_groups_words_into_lines_and_weights_confidence() -> None:
    spans = parse_tesseract_tsv(TSV.encode(), image_size=(100, 100), max_rows=20)

    assert spans == (
        OcrSpan(
            text="회의 안건", left=10, top=20, right=85, bottom=30, confidence=0.85
        ),
    )


def test_tesseract_cli_uses_stdin_stdout_without_shell_or_paths() -> None:
    runner = FakeRunner(
        CommandResult(return_code=0, stdout=TSV.encode(), stderr=b""), []
    )
    engine = TesseractCli(
        executable="/usr/bin/tesseract",
        language="kor",
        version="5.3.0",
        policy=ExtractionPolicy(),
        runner=runner,
    )

    assert engine.recognize(FakeImage())[0].text == "회의 안건"
    args, stdin = runner.calls[0]
    assert args == (
        "/usr/bin/tesseract",
        "stdin",
        "stdout",
        "-l",
        "kor",
        "--oem",
        "1",
        "--psm",
        "6",
        "tsv",
    )
    assert stdin == b"encoded-png"


def test_tesseract_cli_maps_timeout_and_nonzero_without_stderr_leak() -> None:
    class TimeoutRunner(FakeRunner):
        def run(self, *args: object, **kwargs: object) -> CommandResult:
            raise TimeoutError

    engine = TesseractCli(
        version="5.3.0",
        policy=ExtractionPolicy(),
        runner=TimeoutRunner(CommandResult(0, b"", b""), []),
    )
    with pytest.raises(ExtractionException) as timed_out:
        engine.recognize(FakeImage())
    assert timed_out.value.error.code is ErrorCode.OCR_TIMEOUT

    failed = TesseractCli(
        version="5.3.0",
        policy=ExtractionPolicy(),
        runner=FakeRunner(CommandResult(7, b"", b"secret input path"), []),
    )
    with pytest.raises(ExtractionException) as nonzero:
        failed.recognize(FakeImage())
    assert nonzero.value.error.code is ErrorCode.OCR_FAILED
    assert "secret" not in nonzero.value.error.message

    oversized = TesseractCli(
        version="5.3.0",
        policy=ExtractionPolicy(),
        runner=FakeRunner(
            CommandResult(0, b"partial", b"", stdout_truncated=True),
            [],
        ),
    )
    with pytest.raises(ExtractionException) as output_limit:
        oversized.recognize(FakeImage())
    assert output_limit.value.error.code is ErrorCode.OUTPUT_TOO_LARGE


class FakeDecoder:
    name = "fake-decoder"
    version = "1"

    def __init__(self, decoded: DecodedImage) -> None:
        self.decoded = decoded

    def decode(
        self,
        data: bytes,
        *,
        expected_media_type: MediaType,
        policy: ExtractionPolicy,
    ) -> DecodedImage:
        assert data
        assert expected_media_type is MediaType.PNG
        return self.decoded


class FakeOcr:
    name = "fake-ocr"
    version = "1"
    config = {"language": "kor"}

    def recognize(self, image: FakeImage) -> tuple[OcrSpan, ...]:
        return (OcrSpan("회의", 10, 20, 60, 40, 0.9),)


def test_image_extractor_normalizes_post_orientation_pixel_bbox() -> None:
    decoded = DecodedImage(
        image=FakeImage(),
        width=100,
        height=100,
        original_width=50,
        original_height=100,
        exif_orientation=6,
        format="PNG",
    )
    result = ImageExtractor(
        decoder=FakeDecoder(decoded),
        ocr=FakeOcr(),
        policy=ExtractionPolicy(),
    ).extract(b"png", media_type=MediaType.PNG, source_sha256="a" * 64)

    block = result.blocks[0]
    locator = block.anchor.to_dict()["locator"]
    assert isinstance(locator, dict)
    assert locator["bbox"] == [0.1, 0.2, 0.6, 0.4]
    assert block.confidence == 0.9
    assert block.anchor.to_dict()["source_sha256"] == "a" * 64


def test_image_extractor_rejects_post_decode_pixel_overflow() -> None:
    decoded = DecodedImage(FakeImage(), 100, 100, 100, 100, 1, "PNG")
    extractor = ImageExtractor(
        decoder=FakeDecoder(decoded),
        ocr=FakeOcr(),
        policy=ExtractionPolicy(max_image_pixels=9_999),
    )
    with pytest.raises(ExtractionException) as caught:
        extractor.extract(b"png", media_type=MediaType.PNG, source_sha256="a" * 64)
    assert caught.value.error.code is ErrorCode.IMAGE_PIXEL_LIMIT


def test_image_extractor_emits_typed_low_confidence_warning() -> None:
    decoded = DecodedImage(FakeImage(), 100, 100, 100, 100, 1, "PNG")
    result = ImageExtractor(
        decoder=FakeDecoder(decoded),
        ocr=FakeOcr(),
        policy=ExtractionPolicy(low_confidence_threshold=0.95),
    ).extract(b"png", media_type=MediaType.PNG, source_sha256="a" * 64)

    assert [warning.code.value for warning in result.warnings] == ["LOW_CONFIDENCE"]
    assert result.warnings[0].block_ordinal == 0


def test_pillow_decoder_applies_exif_orientation_before_reporting_dimensions() -> None:
    pillow = pytest.importorskip("PIL.Image")
    image = pillow.new("RGB", (2, 3), color="white")
    exif = image.getexif()
    exif[274] = 6
    encoded = BytesIO()
    image.save(encoded, format="JPEG", exif=exif)

    decoded = PillowImageDecoder().decode(
        encoded.getvalue(),
        expected_media_type=MediaType.JPEG,
        policy=ExtractionPolicy(max_image_pixels=100),
    )

    assert (decoded.original_width, decoded.original_height) == (2, 3)
    assert (decoded.width, decoded.height) == (3, 2)
    assert decoded.exif_orientation == 6
