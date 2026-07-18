"""Bounded adapter for the pinned Java HWP/HWPX extraction sidecar."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from axit_ingestion_spike.anchors import HwpParagraphAnchor
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
from axit_ingestion_spike.normalization import text_fingerprint as fingerprint_text


_SIDECAR_SCHEMA = "hwp-sidecar.v1"
_SIDECAR_MAIN = "com.axit.ingestion.hwp.Main"
_DEFAULT_CLASSPATH = "/opt/axit-hwp/sidecar.jar:/opt/axit-hwp/dependency/*"
_PARSER_BY_MEDIA = {
    MediaType.HWP: ("HWP", "hwplib", "1.1.10"),
    MediaType.HWPX: ("HWPX", "hwpxlib", "1.0.9"),
}
_FAILURE_MAP = {
    "ARCHIVE_LIMIT_EXCEEDED": ErrorCode.ZIP_EXPANSION_LIMIT,
    "ARCHIVE_RATIO_REJECTED": ErrorCode.ZIP_EXPANSION_LIMIT,
    "XML_DTD_FORBIDDEN": ErrorCode.XML_DTD_FORBIDDEN,
    "XML_ENCODING_REJECTED": ErrorCode.CORRUPT_DOCUMENT,
    "ENCRYPTED_DOCUMENT": ErrorCode.ENCRYPTED_DOCUMENT,
    "CORRUPT_ARCHIVE": ErrorCode.CORRUPT_DOCUMENT,
    "ARCHIVE_DUPLICATE_ENTRY": ErrorCode.CORRUPT_DOCUMENT,
    "ARCHIVE_PATH_REJECTED": ErrorCode.CORRUPT_DOCUMENT,
    "CORRUPT_DOCUMENT": ErrorCode.CORRUPT_DOCUMENT,
    "OUTPUT_LIMIT_EXCEEDED": ErrorCode.OUTPUT_TOO_LARGE,
    "INPUT_SIZE_REJECTED": ErrorCode.INPUT_TOO_LARGE,
    "UNSUPPORTED_MEDIA_TYPE": ErrorCode.UNSUPPORTED_MEDIA_TYPE,
    "TYPE_MISMATCH": ErrorCode.TYPE_MISMATCH,
}
_PUBLIC_FAILURE_MESSAGE = {
    ErrorCode.ZIP_EXPANSION_LIMIT: "HWPX archive exceeds configured safety limits",
    ErrorCode.XML_DTD_FORBIDDEN: "HWPX XML contains a forbidden DTD or entity",
    ErrorCode.ENCRYPTED_DOCUMENT: "encrypted documents are not accepted",
    ErrorCode.CORRUPT_DOCUMENT: "HWP document could not be parsed safely",
    ErrorCode.OUTPUT_TOO_LARGE: "HWP extraction exceeds configured output limits",
    ErrorCode.INPUT_TOO_LARGE: "input exceeds configured byte limit",
    ErrorCode.UNSUPPORTED_MEDIA_TYPE: "HWP sidecar rejected the media type",
    ErrorCode.TYPE_MISMATCH: "input bytes do not match the declared HWP media type",
}


@dataclass(frozen=True, slots=True)
class HwpSidecarResult:
    stdout: bytes
    stderr: bytes
    exit_code: int
    boundary_error: str | None = None


class HwpSidecarRunner(Protocol):
    def invoke(
        self,
        data: bytes,
        *,
        media_type: MediaType,
        profile_hash: str,
        max_output_bytes: int,
        timeout_seconds: float,
    ) -> HwpSidecarResult: ...


class JavaHwpSidecarRunner:
    """Run one trusted pinned sidecar process with bounded pipes and a temp input."""

    def __init__(
        self,
        *,
        java_binary: str = "java",
        classpath: str | None = None,
        stderr_limit: int = 65_536,
    ) -> None:
        self._java_binary = java_binary
        self._classpath = classpath or os.environ.get(
            "AXIT_HWP_CLASSPATH", _DEFAULT_CLASSPATH
        )
        self._stderr_limit = stderr_limit

    def invoke(
        self,
        data: bytes,
        *,
        media_type: MediaType,
        profile_hash: str,
        max_output_bytes: int,
        timeout_seconds: float,
    ) -> HwpSidecarResult:
        selector = _PARSER_BY_MEDIA.get(media_type)
        if selector is None:
            raise extraction_failure(
                ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                "HWP sidecar only accepts HWP and HWPX inputs",
            )
        suffix = ".hwp" if media_type is MediaType.HWP else ".hwpx"
        staged_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix="axit-hwp-", suffix=suffix, delete=False
            ) as staged:
                staged.write(data)
                staged.flush()
                staged_path = Path(staged.name)
            try:
                staged_path.chmod(0o400)
            except OSError:
                # The sandbox bind/root boundary is authoritative on platforms that
                # do not implement POSIX file modes.
                pass
            command = [
                self._java_binary,
                "-cp",
                self._classpath,
                _SIDECAR_MAIN,
                "--input",
                str(staged_path),
                "--media",
                selector[0],
                "--profile-hash",
                profile_hash,
            ]
            return _run_bounded(
                command,
                stdout_limit=max_output_bytes,
                stderr_limit=self._stderr_limit,
                timeout_seconds=timeout_seconds,
            )
        except FileNotFoundError:
            raise extraction_failure(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                "HWP extraction sidecar runtime is unavailable",
            ) from None
        except OSError:
            raise extraction_failure(
                ErrorCode.INTERNAL_ERROR,
                "HWP sidecar input could not be staged safely",
            ) from None
        finally:
            if staged_path is not None:
                try:
                    staged_path.unlink()
                except OSError:
                    pass


def _run_bounded(
    command: Sequence[str],
    *,
    stdout_limit: int,
    stderr_limit: int,
    timeout_seconds: float,
) -> HwpSidecarResult:
    process = subprocess.Popen(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
    )
    if process.stdout is None or process.stderr is None:  # pragma: no cover
        process.kill()
        raise RuntimeError("sidecar pipes unavailable")

    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": stdout_limit, "stderr": stderr_limit}
    completed = {"stdout": threading.Event(), "stderr": threading.Event()}
    overflow = threading.Event()
    overflow_stream: list[str] = []

    def read_stream(name: str) -> None:
        stream = process.stdout if name == "stdout" else process.stderr
        assert stream is not None
        try:
            while True:
                chunk = stream.read(65_536)
                if not chunk:
                    return
                capacity = limits[name] - len(buffers[name])
                if len(chunk) > capacity:
                    buffers[name].extend(chunk[: max(0, capacity)])
                    overflow_stream.append(name)
                    overflow.set()
                    return
                buffers[name].extend(chunk)
        finally:
            completed[name].set()

    threads = [
        threading.Thread(target=read_stream, args=(name,), daemon=True)
        for name in ("stdout", "stderr")
    ]
    for thread in threads:
        thread.start()

    deadline = time.monotonic() + timeout_seconds
    boundary_error: str | None = None
    while not all(event.is_set() for event in completed.values()):
        if overflow.is_set():
            boundary_error = f"{overflow_stream[0]}_limit"
            process.kill()
            break
        if time.monotonic() >= deadline:
            boundary_error = "timeout"
            process.kill()
            break
        time.sleep(0.005)
    try:
        exit_code = process.wait(timeout=1)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive OS boundary
        process.kill()
        exit_code = process.wait(timeout=1)
        boundary_error = boundary_error or "timeout"
    for thread in threads:
        thread.join(timeout=1)
    return HwpSidecarResult(
        bytes(buffers["stdout"]),
        bytes(buffers["stderr"]),
        exit_code,
        boundary_error,
    )


class JavaHwpExtractor:
    def __init__(
        self,
        *,
        policy: ExtractionPolicy,
        runner: HwpSidecarRunner | None = None,
    ) -> None:
        self._policy = policy
        self._runner = runner or JavaHwpSidecarRunner()

    def extract(
        self,
        data: bytes,
        *,
        media_type: MediaType,
        source_sha256: str,
    ) -> ExtractionResult:
        if hashlib.sha256(data).hexdigest() != source_sha256:
            raise extraction_failure(
                ErrorCode.INTERNAL_ERROR,
                "HWP source identity does not match staged bytes",
            )
        if media_type not in _PARSER_BY_MEDIA:
            raise extraction_failure(
                ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                "HWP adapter only accepts HWP and HWPX inputs",
            )
        invocation = self._runner.invoke(
            data,
            media_type=media_type,
            profile_hash=hwp_config_profile_hash(self._policy, media_type),
            max_output_bytes=self._policy.max_output_bytes,
            timeout_seconds=self._policy.ocr_timeout_seconds,
        )
        if invocation.boundary_error == "stdout_limit":
            raise extraction_failure(
                ErrorCode.OUTPUT_TOO_LARGE,
                "HWP sidecar output exceeds configured byte limit",
            )
        if invocation.boundary_error is not None:
            raise extraction_failure(
                ErrorCode.INTERNAL_ERROR,
                "HWP sidecar exceeded its execution boundary",
            )
        if invocation.stderr:
            raise extraction_failure(
                ErrorCode.INTERNAL_ERROR,
                "HWP sidecar emitted unexpected diagnostic output",
            )
        payload = _parse_json_object(invocation.stdout)
        ok = payload.get("ok")
        if ok is True:
            if invocation.exit_code != 0:
                raise _protocol_failure()
            return self._parse_success(
                payload,
                media_type=media_type,
                expected_source_sha256=source_sha256,
            )
        if ok is False:
            if invocation.exit_code != 2:
                raise _protocol_failure()
            self._raise_mapped_failure(payload)
        raise _protocol_failure()

    def _parse_success(
        self,
        payload: Mapping[str, Any],
        *,
        media_type: MediaType,
        expected_source_sha256: str,
    ) -> ExtractionResult:
        _require_exact_keys(
            payload,
            {
                "extraction_profile_hash",
                "ok",
                "parser",
                "records",
                "schema_version",
                "source_sha256",
                "warnings",
            },
        )
        if payload["schema_version"] != _SIDECAR_SCHEMA:
            raise _protocol_failure()
        if payload["source_sha256"] != expected_source_sha256:
            raise _protocol_failure()
        profile_hash = hwp_config_profile_hash(self._policy, media_type)
        if payload["extraction_profile_hash"] != profile_hash:
            raise _protocol_failure()

        parser = _require_mapping(payload["parser"])
        _require_exact_keys(parser, {"name", "version"})
        expected = _PARSER_BY_MEDIA[media_type]
        if parser["name"] != expected[1] or parser["version"] != expected[2]:
            raise _protocol_failure()

        raw_records = payload["records"]
        if not _is_array(raw_records) or len(raw_records) > self._policy.max_blocks:
            raise _protocol_failure()
        blocks: list[ExtractedBlock] = []
        total_chars = 0
        for ordinal, raw_record in enumerate(raw_records):
            record = _require_mapping(raw_record)
            _require_exact_keys(
                record, {"kind", "locator", "text", "text_fingerprint"}
            )
            kind = record["kind"]
            if kind not in {"paragraph", "table_cell", "footnote"}:
                raise _protocol_failure()
            text = _require_text(record["text"], maximum=self._policy.max_block_chars)
            total_chars += len(text)
            if total_chars > self._policy.max_total_chars:
                raise extraction_failure(
                    ErrorCode.OUTPUT_TOO_LARGE,
                    "HWP extraction exceeds configured character limit",
                )
            if record["text_fingerprint"] != fingerprint_text(text):
                raise _protocol_failure()
            locator = _parse_locator(record["locator"], kind=kind)
            section = locator["section"]
            paragraph = locator["paragraph"]
            if section is None or paragraph is None:  # pragma: no cover - parser invariant
                raise _protocol_failure()
            anchor = HwpParagraphAnchor.from_text(
                source_sha256=expected_source_sha256,
                extraction_profile_hash=profile_hash,
                parser=expected[1],
                parser_version=expected[2],
                section=section,
                paragraph=paragraph,
                text=text,
                table=locator["table"],
                table_block=locator["table_block"],
                table_row=locator["table_row"],
                cell=locator["cell"],
                cell_paragraph=locator["cell_paragraph"],
                footnote=locator["footnote"],
                footnote_paragraph=locator["footnote_paragraph"],
            )
            blocks.append(
                ExtractedBlock(
                    ordinal=ordinal,
                    text=text,
                    block_type=f"hwp_{kind}",
                    confidence=None,
                    anchor=anchor,
                )
            )

        raw_warnings = payload["warnings"]
        if not _is_array(raw_warnings) or len(raw_warnings) > 128:
            raise _protocol_failure()
        warnings: list[ExtractionWarning] = []
        for raw_warning in raw_warnings:
            if raw_warning == "NO_EXTRACTABLE_TEXT":
                if blocks:
                    raise _protocol_failure()
                continue
            if raw_warning == "UNSUPPORTED_ENDNOTE":
                warnings.append(
                    ExtractionWarning(
                        WarningCode.PARTIAL_EXTRACTION,
                        "HWP endnotes were not extracted by the pinned parser",
                    )
                )
            elif raw_warning == "NESTED_CONTROL_SKIPPED":
                warnings.append(
                    ExtractionWarning(
                        WarningCode.PARTIAL_EXTRACTION,
                        "unsupported nested HWP controls were skipped",
                    )
                )
            else:
                raise _protocol_failure()
        if not blocks:
            raise extraction_failure(
                ErrorCode.NO_EXTRACTABLE_TEXT,
                "HWP document contains no extractable text",
            )
        return ExtractionResult(
            source_sha256=expected_source_sha256,
            media_type=media_type,
            parser_name=expected[1],
            parser_version=expected[2],
            normalization_profile=NORMALIZATION_PROFILE,
            config_profile_hash=profile_hash,
            blocks=tuple(blocks),
            warnings=tuple(warnings),
        )

    def _raise_mapped_failure(self, payload: Mapping[str, Any]) -> None:
        _require_exact_keys(payload, {"error", "ok"})
        raw_error = _require_mapping(payload["error"])
        _require_exact_keys(raw_error, {"code", "message", "retryable"})
        code = raw_error["code"]
        _require_text(raw_error["message"], maximum=512, single_line=True)
        if raw_error["retryable"] is not False or not isinstance(code, str):
            raise _protocol_failure()
        common_code = _FAILURE_MAP.get(code)
        if common_code is None:
            raise _protocol_failure()
        raise extraction_failure(common_code, _PUBLIC_FAILURE_MESSAGE[common_code])


def _parse_json_object(raw: bytes) -> Mapping[str, Any]:
    if raw.endswith(b"\r\n"):
        raw = raw[:-2]
    elif raw.endswith(b"\n"):
        raw = raw[:-1]
    if not raw or raw != raw.strip():
        raise _protocol_failure()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        parsed = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON number")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise _protocol_failure() from None
    return _require_mapping(parsed)


def hwp_config_profile_hash(
    policy: ExtractionPolicy,
    media_type: MediaType,
) -> str:
    parser = _PARSER_BY_MEDIA.get(media_type)
    if parser is None:
        raise ValueError("HWP profile requires HWP or HWPX media")
    return config_profile_hash(
        {
            "policy_hash": policy.profile_hash,
            "sidecar_schema": _SIDECAR_SCHEMA,
            "parser": {"name": parser[1], "version": parser[2]},
        }
    )


def _parse_locator(raw: object, *, kind: str) -> dict[str, int | None]:
    locator = _require_mapping(raw)
    base = {"paragraph", "section"}
    table = {"cell", "cell_paragraph", "table", "table_block", "table_row"}
    footnote = {"footnote", "footnote_paragraph"}
    expected = base | (table if kind == "table_cell" else set())
    if kind == "footnote":
        expected |= footnote
    _require_exact_keys(locator, expected)
    values = {key: _require_index(locator[key]) for key in expected}
    return {
        "section": values["section"],
        "paragraph": values["paragraph"],
        "table": values.get("table"),
        "table_block": values.get("table_block"),
        "table_row": values.get("table_row"),
        "cell": values.get("cell"),
        "cell_paragraph": values.get("cell_paragraph"),
        "footnote": values.get("footnote"),
        "footnote_paragraph": values.get("footnote_paragraph"),
    }


def _require_mapping(raw: object) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping) or any(not isinstance(key, str) for key in raw):
        raise _protocol_failure()
    return raw


def _require_exact_keys(raw: Mapping[str, Any], expected: set[str]) -> None:
    if set(raw) != expected:
        raise _protocol_failure()


def _is_array(raw: object) -> bool:
    return isinstance(raw, Sequence) and not isinstance(
        raw, (str, bytes, bytearray, memoryview)
    )


def _require_text(
    raw: object,
    *,
    maximum: int,
    single_line: bool = False,
) -> str:
    if (
        not isinstance(raw, str)
        or not raw
        or len(raw) > maximum
        or normalize_text(raw) != raw
        or (single_line and "\n" in raw)
    ):
        raise _protocol_failure()
    return raw


def _require_index(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise _protocol_failure()
    return raw


def _protocol_failure() -> Exception:
    return extraction_failure(
        ErrorCode.INTERNAL_ERROR,
        "HWP sidecar returned an invalid protocol response",
    )


__all__ = [
    "HwpSidecarResult",
    "HwpSidecarRunner",
    "JavaHwpExtractor",
    "JavaHwpSidecarRunner",
    "hwp_config_profile_hash",
]
