"""Bounded Tesseract CLI adapter and deterministic TSV-to-line conversion."""

from __future__ import annotations

import csv
import io
import os
import subprocess
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import BinaryIO, Protocol

from axit_ingestion_spike.models import (
    ErrorCode,
    ExtractionPolicy,
    extraction_failure,
)
from axit_ingestion_spike.normalization import JsonValue, normalize_text


class ImageForOcr(Protocol):
    @property
    def size(self) -> tuple[int, int]: ...

    def save(self, destination: BinaryIO, *, format: str) -> None: ...


@dataclass(frozen=True, slots=True)
class OcrSpan:
    text: str
    left: int
    top: int
    right: int
    bottom: int
    confidence: float

    def __post_init__(self) -> None:
        if not self.text or normalize_text(self.text) != self.text:
            raise ValueError("OCR span text must be non-empty normalized text")
        values = (self.left, self.top, self.right, self.bottom)
        if any(
            isinstance(value, bool) or not isinstance(value, int) for value in values
        ):
            raise ValueError("OCR coordinates must be integers")
        if (
            self.left < 0
            or self.top < 0
            or self.left >= self.right
            or self.top >= self.bottom
        ):
            raise ValueError("OCR span must be a positive top-left pixel box")
        if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 1:
            raise ValueError("OCR confidence must be in [0, 1]")


class OcrEngine(Protocol):
    name: str
    version: str
    config: Mapping[str, JsonValue]

    def recognize(self, image: ImageForOcr) -> tuple[OcrSpan, ...]: ...


@dataclass(frozen=True, slots=True)
class CommandResult:
    return_code: int
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool = False
    stderr_truncated: bool = False


class CommandRunner(Protocol):
    def run(
        self,
        args: tuple[str, ...],
        *,
        stdin: bytes,
        timeout_seconds: float,
        environment: dict[str, str],
    ) -> CommandResult: ...


class _SubprocessRunner:
    def __init__(self, *, stdout_limit: int, stderr_limit: int) -> None:
        self.stdout_limit = stdout_limit
        self.stderr_limit = stderr_limit

    def run(
        self,
        args: tuple[str, ...],
        *,
        stdin: bytes,
        timeout_seconds: float,
        environment: dict[str, str],
    ) -> CommandResult:
        with (
            tempfile.TemporaryFile(mode="w+b") as stdin_file,
            tempfile.TemporaryFile(mode="w+b") as stdout_file,
            tempfile.TemporaryFile(mode="w+b") as stderr_file,
        ):
            stdin_file.write(stdin)
            stdin_file.seek(0)
            try:
                process = subprocess.Popen(
                    args,
                    stdin=stdin_file,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    shell=False,
                    env=environment,
                )
            except FileNotFoundError as error:
                raise extraction_failure(
                    ErrorCode.DEPENDENCY_UNAVAILABLE,
                    "Tesseract executable is unavailable",
                ) from error

            deadline = time.monotonic() + timeout_seconds
            stdout_truncated = False
            stderr_truncated = False
            while process.poll() is None:
                stdout_truncated = (
                    os.fstat(stdout_file.fileno()).st_size > self.stdout_limit
                )
                stderr_truncated = (
                    os.fstat(stderr_file.fileno()).st_size > self.stderr_limit
                )
                if stdout_truncated or stderr_truncated:
                    process.kill()
                    break
                if time.monotonic() >= deadline:
                    process.kill()
                    process.wait(timeout=5)
                    raise TimeoutError
                time.sleep(0.01)
            return_code = process.wait(timeout=5)
            stdout_size = os.fstat(stdout_file.fileno()).st_size
            stderr_size = os.fstat(stderr_file.fileno()).st_size
            stdout_truncated = stdout_truncated or stdout_size > self.stdout_limit
            stderr_truncated = stderr_truncated or stderr_size > self.stderr_limit
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read(self.stdout_limit + 1)
            stderr = stderr_file.read(self.stderr_limit + 1)
            return CommandResult(
                return_code,
                stdout,
                stderr,
                stdout_truncated,
                stderr_truncated,
            )


@dataclass(slots=True)
class _LineAccumulator:
    words: list[str]
    left: int
    top: int
    right: int
    bottom: int
    weighted_confidence: float
    weight: int

    def add(
        self,
        *,
        text: str,
        left: int,
        top: int,
        right: int,
        bottom: int,
        confidence: float,
    ) -> None:
        self.words.append(text)
        self.left = min(self.left, left)
        self.top = min(self.top, top)
        self.right = max(self.right, right)
        self.bottom = max(self.bottom, bottom)
        word_weight = max(len(text), 1)
        self.weighted_confidence += confidence * word_weight
        self.weight += word_weight


_REQUIRED_TSV_COLUMNS = {
    "page_num",
    "block_num",
    "par_num",
    "line_num",
    "left",
    "top",
    "width",
    "height",
    "conf",
    "text",
}


def _invalid_tsv() -> Exception:
    return extraction_failure(
        ErrorCode.OCR_FAILED, "Tesseract returned malformed TSV output"
    )


def parse_tesseract_tsv(
    payload: bytes,
    *,
    image_size: tuple[int, int],
    max_rows: int,
) -> tuple[OcrSpan, ...]:
    """Parse word rows and combine them into stable line-order OCR spans."""

    image_width, image_height = image_size
    if image_width <= 0 or image_height <= 0:
        raise ValueError("image dimensions must be positive")
    try:
        text_payload = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise _invalid_tsv() from error

    reader = csv.DictReader(io.StringIO(text_payload), delimiter="\t")
    if reader.fieldnames is None or not _REQUIRED_TSV_COLUMNS.issubset(
        reader.fieldnames
    ):
        raise _invalid_tsv()

    lines: dict[tuple[int, int, int, int], _LineAccumulator] = {}
    for row_index, row in enumerate(reader, start=1):
        if row_index > max_rows:
            raise extraction_failure(
                ErrorCode.OUTPUT_TOO_LARGE,
                "Tesseract TSV row count exceeds configured limit",
            )
        try:
            word = normalize_text(row["text"] or "").strip()
            confidence_percent = float(row["conf"] or "-1")
            if not word or confidence_percent < 0:
                continue
            if confidence_percent > 100:
                raise ValueError
            left = int(row["left"] or "")
            top = int(row["top"] or "")
            width = int(row["width"] or "")
            height = int(row["height"] or "")
            right = left + width
            bottom = top + height
            key = (
                int(row["page_num"] or ""),
                int(row["block_num"] or ""),
                int(row["par_num"] or ""),
                int(row["line_num"] or ""),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise _invalid_tsv() from error
        if (
            left < 0
            or top < 0
            or width <= 0
            or height <= 0
            or right > image_width
            or bottom > image_height
        ):
            raise extraction_failure(
                ErrorCode.INVALID_COORDINATE,
                "Tesseract returned a pixel box outside the decoded image",
            )
        confidence = round(confidence_percent / 100, 6)
        existing = lines.get(key)
        if existing is None:
            weight = max(len(word), 1)
            lines[key] = _LineAccumulator(
                words=[word],
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                weighted_confidence=confidence * weight,
                weight=weight,
            )
        else:
            existing.add(
                text=word,
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                confidence=confidence,
            )

    return tuple(
        OcrSpan(
            text=" ".join(line.words),
            left=line.left,
            top=line.top,
            right=line.right,
            bottom=line.bottom,
            confidence=round(line.weighted_confidence / line.weight, 6),
        )
        for line in lines.values()
    )


class TesseractCli:
    """Invoke pinned Tesseract over bytes only; never expose stderr or input paths."""

    name = "tesseract-cli"

    def __init__(
        self,
        *,
        executable: str = "/usr/bin/tesseract",
        language: str = "kor",
        version: str = "5.3.0",
        page_segmentation_mode: int = 6,
        policy: ExtractionPolicy,
        runner: CommandRunner | None = None,
    ) -> None:
        if not executable or not language or not version:
            raise ValueError("Tesseract executable, language, and version are required")
        if (
            isinstance(page_segmentation_mode, bool)
            or not 0 <= page_segmentation_mode <= 13
        ):
            raise ValueError("Tesseract page segmentation mode must be in [0, 13]")
        self.executable = executable
        self.language = language
        self.version = version
        self.page_segmentation_mode = page_segmentation_mode
        self.policy = policy
        self.runner = runner or _SubprocessRunner(
            stdout_limit=policy.max_ocr_tsv_bytes,
            stderr_limit=min(policy.max_ocr_tsv_bytes, 65_536),
        )
        self.config: Mapping[str, JsonValue] = {
            "language": language,
            "oem": 1,
            "psm": page_segmentation_mode,
            "format": "tsv",
        }

    def recognize(self, image: ImageForOcr) -> tuple[OcrSpan, ...]:
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")
        image_bytes = encoded.getvalue()
        if len(image_bytes) > self.policy.max_input_bytes:
            raise extraction_failure(
                ErrorCode.INPUT_TOO_LARGE,
                "encoded OCR image exceeds configured byte limit",
            )
        args = (
            self.executable,
            "stdin",
            "stdout",
            "-l",
            self.language,
            "--oem",
            "1",
            "--psm",
            str(self.page_segmentation_mode),
            "tsv",
        )
        try:
            completed = self.runner.run(
                args,
                stdin=image_bytes,
                timeout_seconds=self.policy.ocr_timeout_seconds,
                environment={
                    "HOME": "/tmp",
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                    "OMP_THREAD_LIMIT": "1",
                    "TMPDIR": "/tmp",
                },
            )
        except TimeoutError as error:
            raise extraction_failure(
                ErrorCode.OCR_TIMEOUT,
                "Tesseract exceeded configured execution time",
                retryable=True,
            ) from error
        if (
            completed.stdout_truncated
            or len(completed.stdout) > self.policy.max_ocr_tsv_bytes
        ):
            raise extraction_failure(
                ErrorCode.OUTPUT_TOO_LARGE,
                "Tesseract TSV exceeds configured byte limit",
            )
        if completed.return_code != 0 or completed.stderr_truncated:
            raise extraction_failure(
                ErrorCode.OCR_FAILED,
                "Tesseract exited without a valid OCR result",
            )
        return parse_tesseract_tsv(
            completed.stdout,
            image_size=image.size,
            max_rows=self.policy.max_ocr_rows,
        )
