"""Bounded orchestrator-to-parser IPC for an untrusted extraction process.

This module is deliberately transport-only: the caller owns durable job state,
blob access, and credentials, while the parser receives a staged byte snapshot,
an allowlisted metadata envelope, and one output-file path.  A container or
restricted process launcher can use the same three paths with fixed in-sandbox
mount locations.  The local harness never inherits the caller environment and
never returns parser stdout/stderr, so database, provider, and session secrets
cannot accidentally cross this IPC boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, TypeAlias


JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_MEDIA_TYPES: Final = frozenset(
    {
        "text/plain",
        "application/pdf",
        "image/png",
        "image/jpeg",
        "application/x-hwp",
        "application/x-hwpx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)
_ANCHOR_KIND_BY_MEDIA_TYPE: Final = {
    "text/plain": "text_line",
    "application/pdf": "pdf_block",
    "image/png": "image_bbox",
    "image/jpeg": "image_bbox",
    "application/x-hwp": "hwp_paragraph",
    "application/x-hwpx": "hwp_paragraph",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx_paragraph",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pdf_block",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx_cell",
}
_PARSER_FAILURE_CODES: Final = frozenset(
    {
        "EMPTY_INPUT",
        "INPUT_TOO_LARGE",
        "UNSUPPORTED_MEDIA_TYPE",
        "TYPE_MISMATCH",
        "DEPENDENCY_UNAVAILABLE",
        "CORRUPT_DOCUMENT",
        "ENCRYPTED_DOCUMENT",
        "IMAGE_PIXEL_LIMIT",
        "PDF_PAGE_LIMIT",
        "INVALID_COORDINATE",
        "ZIP_EXPANSION_LIMIT",
        "XML_DTD_FORBIDDEN",
        "OCR_REQUIRED",
        "OCR_TIMEOUT",
        "OCR_FAILED",
        "NO_EXTRACTABLE_TEXT",
        "OUTPUT_TOO_LARGE",
        "INTERNAL_ERROR",
    }
)
_WARNING_CODES: Final = frozenset(
    {"LOW_CONFIDENCE", "PARTIAL_EXTRACTION", "FOOTNOTE_UNRESOLVED"}
)
_SAFE_ENVIRONMENT: Final = {
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUNBUFFERED": "1",
    "PATH": os.defpath,
}


class SandboxFailureCode(StrEnum):
    """Stable codes that can be stored by the orchestrator without raw logs."""

    INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
    SANDBOX_LAUNCH_FAILED = "SANDBOX_LAUNCH_FAILED"
    PARSER_TIMEOUT = "PARSER_TIMEOUT"
    PARSER_LOG_LIMIT = "PARSER_LOG_LIMIT"
    PARSER_LOG_OUTPUT = "PARSER_LOG_OUTPUT"
    PARSER_CRASH = "PARSER_CRASH"
    PARSER_EXIT_MISMATCH = "PARSER_EXIT_MISMATCH"
    PARSER_OUTPUT_TOO_LARGE = "PARSER_OUTPUT_TOO_LARGE"
    INVALID_PARSER_OUTPUT = "INVALID_PARSER_OUTPUT"
    STAGED_INPUT_TAMPERED = "STAGED_INPUT_TAMPERED"
    PARSER_REPORTED_FAILURE = "PARSER_REPORTED_FAILURE"


@dataclass(frozen=True, slots=True)
class ParserIdentity:
    """Pinned parser name/version expected by the orchestrator for one run."""

    name: str
    version: str

    def __post_init__(self) -> None:
        _require_normalized_text(self.name, "parser name")
        _require_normalized_text(self.version, "parser version")

    def to_dict(self) -> dict[str, JsonValue]:
        return {"name": self.name, "version": self.version}


@dataclass(frozen=True, slots=True)
class SandboxRequest:
    """The complete parser-visible request surface; it contains no credentials."""

    input_bytes: bytes
    original_filename: str
    expected_media_type: str
    expected_parser: ParserIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.input_bytes, bytes):
            raise ValueError("input_bytes must be immutable bytes")
        if (
            not self.original_filename
            or len(self.original_filename) > 255
            or any(
                character in self.original_filename
                for character in ("/", "\\", "\x00", "\r", "\n")
            )
        ):
            raise ValueError("original_filename must be a safe basename")
        if self.expected_media_type not in _ALLOWED_MEDIA_TYPES:
            raise ValueError("expected_media_type is not approved")
        if not isinstance(self.expected_parser, ParserIdentity):
            raise ValueError("expected_parser must be a ParserIdentity")


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    """Host-enforced bounds for one parser subprocess invocation."""

    max_input_bytes: int
    max_output_bytes: int
    max_stdout_bytes: int
    max_stderr_bytes: int
    wall_timeout_seconds: float
    max_blocks: int
    max_block_chars: int
    max_total_chars: int

    def __post_init__(self) -> None:
        values = {
            "max_input_bytes": self.max_input_bytes,
            "max_output_bytes": self.max_output_bytes,
            "max_stdout_bytes": self.max_stdout_bytes,
            "max_stderr_bytes": self.max_stderr_bytes,
            "wall_timeout_seconds": self.wall_timeout_seconds,
            "max_blocks": self.max_blocks,
            "max_block_chars": self.max_block_chars,
            "max_total_chars": self.max_total_chars,
        }
        for name, value in values.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value <= 0
            ):
                raise ValueError(f"{name} must be positive")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.max_block_chars > self.max_total_chars:
            raise ValueError("max_block_chars cannot exceed max_total_chars")


@dataclass(frozen=True, slots=True)
class SandboxFailure:
    """Typed error data safe to persist; raw process output is intentionally absent."""

    code: SandboxFailureCode
    parser_code: str | None = None
    retryable: bool | None = None


@dataclass(frozen=True, slots=True)
class SandboxExecution:
    """The one bounded outcome returned to an orchestrator outside its DB transaction."""

    ok: bool
    payload: Mapping[str, Any] | None
    failure: SandboxFailure | None
    source_sha256: str
    exit_code: int | None
    duration_ms: int
    stdout_bytes: int
    stderr_bytes: int
    killed: bool


@dataclass(frozen=True, slots=True)
class _StagedRequest:
    root: Path
    input_path: Path
    request_path: Path
    output_dir: Path
    output_path: Path
    input_bytes: bytes
    source_sha256: str


@dataclass(frozen=True, slots=True)
class _Capture:
    stdout: bytes
    stderr: bytes
    exit_code: int | None
    boundary_failure: SandboxFailureCode | None
    killed: bool


@dataclass(frozen=True, slots=True)
class _ParsedFailure:
    code: str
    retryable: bool


def canonical_sha256(value: object) -> str:
    """Return the Phase-1-compatible hash of canonical NFC/LF JSON."""

    serialized = json.dumps(
        _canonicalize_json(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def execute_sandbox(
    request: SandboxRequest,
    parser_command: Sequence[str],
    policy: SandboxPolicy,
    *,
    staging_root: Path | None = None,
) -> SandboxExecution:
    """Run one parser command against a private byte snapshot.

    ``parser_command`` is orchestrator-controlled (never user input).  The
    harness appends ``--input``, ``--request``, and ``--output`` paths and
    invokes it with a fresh allowlisted environment rather than inheriting
    ``os.environ``.  In production a container launcher should preserve this
    protocol while additionally enforcing network, UID, CPU, memory, PID, and
    filesystem limits.
    """

    _validate_command(parser_command)
    if not isinstance(policy, SandboxPolicy):
        raise ValueError("policy must be a SandboxPolicy")

    start = time.monotonic()
    source_sha256 = hashlib.sha256(request.input_bytes).hexdigest()
    if len(request.input_bytes) > policy.max_input_bytes:
        return _failure_execution(
            SandboxFailureCode.INPUT_TOO_LARGE,
            source_sha256=source_sha256,
            start=start,
        )

    try:
        with _stage_request(request, policy, staging_root=staging_root) as staged:
            return _run_staged_parser(
                request,
                tuple(parser_command),
                policy,
                staged,
                start=start,
            )
    except OSError:
        return _failure_execution(
            SandboxFailureCode.SANDBOX_LAUNCH_FAILED,
            source_sha256=source_sha256,
            start=start,
        )


def _run_staged_parser(
    request: SandboxRequest,
    parser_command: tuple[str, ...],
    policy: SandboxPolicy,
    staged: _StagedRequest,
    *,
    start: float,
) -> SandboxExecution:
    command = (
        *parser_command,
        "--input",
        str(staged.input_path),
        "--request",
        str(staged.request_path),
        "--output",
        str(staged.output_path),
    )
    popen_options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": staged.root,
        "env": _safe_environment(staged.root),
    }
    if os.name == "nt":
        # This is only best-effort tree cleanup for the local adapter. It is
        # not a substitute for the G0 container's UID/network/cgroup boundary.
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_options["start_new_session"] = True
    try:
        process = subprocess.Popen[bytes](command, **popen_options)
    except OSError:
        return _failure_execution(
            SandboxFailureCode.SANDBOX_LAUNCH_FAILED,
            source_sha256=staged.source_sha256,
            start=start,
        )

    capture = _bounded_capture(process, policy)
    if capture.boundary_failure is not None:
        return _capture_failure(capture.boundary_failure, staged, capture, start)
    if capture.exit_code not in (0, 2):
        return _capture_failure(SandboxFailureCode.PARSER_CRASH, staged, capture, start)
    if capture.stdout or capture.stderr:
        return _capture_failure(
            SandboxFailureCode.PARSER_LOG_OUTPUT, staged, capture, start
        )
    if not _staged_input_is_unchanged(staged):
        return _capture_failure(
            SandboxFailureCode.STAGED_INPUT_TAMPERED, staged, capture, start
        )

    try:
        raw_output = _read_single_output(staged, policy.max_output_bytes)
    except _OutputTooLarge:
        return _capture_failure(
            SandboxFailureCode.PARSER_OUTPUT_TOO_LARGE, staged, capture, start
        )
    except ValueError:
        return _capture_failure(
            SandboxFailureCode.INVALID_PARSER_OUTPUT, staged, capture, start
        )

    try:
        payload = _parse_json_object(raw_output)
        parser_failure = _validate_phase1_payload(payload, request, policy)
    except ValueError:
        return _capture_failure(
            SandboxFailureCode.INVALID_PARSER_OUTPUT, staged, capture, start
        )

    expected_exit_code = 2 if parser_failure is not None else 0
    if capture.exit_code != expected_exit_code:
        return _capture_failure(
            SandboxFailureCode.PARSER_EXIT_MISMATCH, staged, capture, start
        )
    if parser_failure is not None:
        return SandboxExecution(
            ok=False,
            # The parser controls failure text. Keep only the reviewed typed
            # code/retryability on this side of the trust boundary.
            payload=None,
            failure=SandboxFailure(
                SandboxFailureCode.PARSER_REPORTED_FAILURE,
                parser_code=parser_failure.code,
                retryable=parser_failure.retryable,
            ),
            source_sha256=staged.source_sha256,
            exit_code=capture.exit_code,
            duration_ms=_duration_ms(start),
            stdout_bytes=len(capture.stdout),
            stderr_bytes=len(capture.stderr),
            killed=False,
        )
    return SandboxExecution(
        ok=True,
        payload=payload,
        failure=None,
        source_sha256=staged.source_sha256,
        exit_code=capture.exit_code,
        duration_ms=_duration_ms(start),
        stdout_bytes=len(capture.stdout),
        stderr_bytes=len(capture.stderr),
        killed=False,
    )


def _failure_execution(
    code: SandboxFailureCode,
    *,
    source_sha256: str,
    start: float,
    exit_code: int | None = None,
    stdout_bytes: int = 0,
    stderr_bytes: int = 0,
    killed: bool = False,
) -> SandboxExecution:
    return SandboxExecution(
        ok=False,
        payload=None,
        failure=SandboxFailure(code),
        source_sha256=source_sha256,
        exit_code=exit_code,
        duration_ms=_duration_ms(start),
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        killed=killed,
    )


def _capture_failure(
    code: SandboxFailureCode,
    staged: _StagedRequest,
    capture: _Capture,
    start: float,
) -> SandboxExecution:
    return _failure_execution(
        code,
        source_sha256=staged.source_sha256,
        start=start,
        exit_code=capture.exit_code,
        stdout_bytes=len(capture.stdout),
        stderr_bytes=len(capture.stderr),
        killed=capture.killed,
    )


def _duration_ms(start: float) -> int:
    return round((time.monotonic() - start) * 1000)


def _validate_command(parser_command: Sequence[str]) -> None:
    if isinstance(parser_command, (str, bytes)) or not parser_command:
        raise ValueError("parser_command must be a non-empty string sequence")
    for index, item in enumerate(parser_command):
        if not isinstance(item, str) or not item or "\x00" in item or len(item) > 4096:
            raise ValueError(f"parser_command[{index}] is invalid")


def _safe_environment(root: Path) -> dict[str, str]:
    """Build the parser environment without inheriting host credentials."""

    environment = dict(_SAFE_ENVIRONMENT)
    environment["HOME"] = str(root / "home")
    if os.name == "nt":
        # Windows process startup can require this platform path. It is not a
        # tenant credential and is the only host-derived environment value.
        system_root = os.environ.get("SystemRoot")
        if system_root:
            environment["SystemRoot"] = system_root
    return environment


@contextmanager
def _stage_request(
    request: SandboxRequest,
    policy: SandboxPolicy,
    *,
    staging_root: Path | None,
) -> Iterator[_StagedRequest]:
    parent = _staging_parent(staging_root)
    root = Path(tempfile.mkdtemp(prefix="axit-parser-", dir=parent))
    input_dir = root / "input"
    output_dir = root / "output"
    input_path = input_dir / "source"
    request_path = input_dir / "request.json"
    output_path = output_dir / "result.json"
    source_sha256 = hashlib.sha256(request.input_bytes).hexdigest()
    try:
        input_dir.mkdir(mode=0o700)
        output_dir.mkdir(mode=0o700)
        _write_exclusive(input_path, request.input_bytes)
        request_payload: dict[str, JsonValue] = {
            "schema_version": 1,
            "source_sha256": source_sha256,
            "original_filename": request.original_filename,
            "expected_media_type": request.expected_media_type,
            "parser": request.expected_parser.to_dict(),
        }
        _write_exclusive(request_path, _canonical_json_bytes(request_payload))
        _make_read_only(input_path)
        _make_read_only(request_path)
        _make_read_only_directory(input_dir)
        _make_read_only_directory(root)
        yield _StagedRequest(
            root=root,
            input_path=input_path,
            request_path=request_path,
            output_dir=output_dir,
            output_path=output_path,
            input_bytes=request.input_bytes,
            source_sha256=source_sha256,
        )
    finally:
        _remove_stage(root)


def _staging_parent(staging_root: Path | None) -> str | None:
    if staging_root is None:
        return None
    staging_root.mkdir(parents=True, exist_ok=True)
    if not staging_root.is_dir():
        raise ValueError("staging_root must be a directory")
    return str(staging_root)


def _write_exclusive(path: Path, data: bytes) -> None:
    with path.open("xb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def _make_read_only(path: Path) -> None:
    path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def _make_read_only_directory(path: Path) -> None:
    path.chmod(stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IXOTH)


def _remove_stage(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(
        root.rglob("*"), key=lambda candidate: len(candidate.parts), reverse=True
    ):
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        except OSError:
            pass
    try:
        root.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    except OSError:
        pass
    shutil.rmtree(root, ignore_errors=True)


def _bounded_capture(
    process: subprocess.Popen[bytes], policy: SandboxPolicy
) -> _Capture:
    if process.stdout is None or process.stderr is None:
        raise RuntimeError("parser pipes are unavailable")
    buffers: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": policy.max_stdout_bytes, "stderr": policy.max_stderr_bytes}
    completed = {"stdout": threading.Event(), "stderr": threading.Event()}
    overflow = threading.Event()
    overflow_stream: list[str] = []

    def read_stream(name: str, stream: Any) -> None:
        try:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    return
                remaining = limits[name] - len(buffers[name])
                if len(chunk) > remaining:
                    buffers[name].extend(chunk[: max(remaining, 0)])
                    overflow_stream.append(name)
                    overflow.set()
                    return
                buffers[name].extend(chunk)
        finally:
            completed[name].set()

    threads = [
        threading.Thread(
            target=read_stream, args=("stdout", process.stdout), daemon=True
        ),
        threading.Thread(
            target=read_stream, args=("stderr", process.stderr), daemon=True
        ),
    ]
    for thread in threads:
        thread.start()

    deadline = time.monotonic() + policy.wall_timeout_seconds
    failure: SandboxFailureCode | None = None
    killed = False
    while True:
        if overflow.is_set():
            failure = SandboxFailureCode.PARSER_LOG_LIMIT
            killed = True
            _kill_process(process)
            break
        if time.monotonic() >= deadline:
            failure = SandboxFailureCode.PARSER_TIMEOUT
            killed = True
            _kill_process(process)
            break
        if process.poll() is not None and all(
            event.is_set() for event in completed.values()
        ):
            break
        time.sleep(0.005)

    try:
        exit_code = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _kill_process(process)
        exit_code = process.wait(timeout=5)
        failure = failure or SandboxFailureCode.PARSER_TIMEOUT
        killed = True
    for thread in threads:
        thread.join(timeout=1)
    # Popen does not close PIPE handles when callers use wait() instead of
    # communicate(). The reader threads have reached EOF by this point, so the
    # parent must release both descriptors explicitly on every outcome path.
    process.stdout.close()
    process.stderr.close()
    return _Capture(
        stdout=bytes(buffers["stdout"]),
        stderr=bytes(buffers["stderr"]),
        exit_code=exit_code,
        boundary_failure=failure,
        killed=killed,
    )


def _kill_process(process: subprocess.Popen[bytes]) -> None:
    """Best-effort process-tree cleanup for the adapter's local harness.

    The production launcher must still supply the G0 container's no-network,
    non-root, cgroup, PID, and filesystem controls. This only prevents a
    timed-out local parser from leaving ordinary child processes behind.
    """

    try:
        if os.name == "nt":
            subprocess.run(
                ("taskkill", "/PID", str(process.pid), "/T", "/F"),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
        else:
            kill_process_group = getattr(os, "killpg", None)
            kill_signal = getattr(signal, "SIGKILL", None)
            if callable(kill_process_group) and kill_signal is not None:
                kill_process_group(process.pid, kill_signal)
            else:
                process.kill()
    except ProcessLookupError:
        pass
    except (OSError, subprocess.TimeoutExpired):
        # The parent may already have exited, or the platform may not support
        # process-group cleanup. A final direct kill keeps the bounded caller
        # path deterministic without exposing parser output.
        try:
            process.kill()
        except ProcessLookupError:
            pass


def _staged_input_is_unchanged(staged: _StagedRequest) -> bool:
    try:
        return staged.input_path.read_bytes() == staged.input_bytes
    except OSError:
        return False


class _OutputTooLarge(ValueError):
    pass


def _read_single_output(staged: _StagedRequest, max_output_bytes: int) -> bytes:
    try:
        entries: list[Path] = []
        for entry in staged.output_dir.iterdir():
            entries.append(entry)
            if len(entries) > 1:
                raise ValueError("parser must write exactly one result.json file")
    except OSError as error:
        raise ValueError("parser output directory cannot be inspected") from error
    if entries != [staged.output_path]:
        raise ValueError("parser must write exactly one result.json file")
    try:
        mode = staged.output_path.lstat().st_mode
    except OSError as error:
        raise ValueError("parser result file cannot be inspected") from error
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError("parser result must be a regular file")
    if staged.output_path.stat().st_size > max_output_bytes:
        raise _OutputTooLarge("parser result exceeds configured byte limit")
    try:
        with staged.output_path.open("rb") as file:
            value = file.read(max_output_bytes + 1)
    except OSError as error:
        raise ValueError("parser result cannot be read") from error
    if len(value) > max_output_bytes:
        raise _OutputTooLarge("parser result exceeds configured byte limit")
    if not value:
        raise ValueError("parser result is empty")
    return value


def _parse_json_object(raw: bytes) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("parser result contains duplicate JSON keys")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("parser result contains a non-finite number")
            ),
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as error:
        raise ValueError("parser result must be one UTF-8 JSON object") from error
    if not isinstance(value, dict):
        raise ValueError("parser result must be an object")
    _reject_non_scalar_unicode(value)
    return value


def _validate_phase1_payload(
    payload: Mapping[str, Any], request: SandboxRequest, policy: SandboxPolicy
) -> _ParsedFailure | None:
    if payload.get("schema_version") != 1 or not isinstance(payload.get("ok"), bool):
        raise ValueError("parser result header is invalid")
    if payload["ok"] is False:
        return _validate_failure_payload(payload)
    _validate_success_payload(payload, request, policy)
    return None


def _validate_failure_payload(payload: Mapping[str, Any]) -> _ParsedFailure:
    _require_exact_keys(payload, {"schema_version", "ok", "error"}, "failure envelope")
    error = _require_mapping(payload["error"], "error")
    _require_exact_keys(error, {"code", "message", "retryable"}, "error")
    code = error.get("code")
    if not isinstance(code, str) or code not in _PARSER_FAILURE_CODES:
        raise ValueError("parser failure code is unsupported")
    message = _require_normalized_text(
        error.get("message"), "parser failure message", maximum=512
    )
    if "\n" in message:
        raise ValueError("parser failure message must be a single line")
    retryable = error.get("retryable")
    if not isinstance(retryable, bool):
        raise ValueError("parser failure retryable must be boolean")
    return _ParsedFailure(code=code, retryable=retryable)


def _validate_success_payload(
    payload: Mapping[str, Any], request: SandboxRequest, policy: SandboxPolicy
) -> None:
    _require_exact_keys(payload, {"schema_version", "ok", "result"}, "success envelope")
    result = _require_mapping(payload["result"], "result")
    _require_exact_keys(
        result,
        {
            "source_sha256",
            "media_type",
            "parser",
            "normalization_profile",
            "config_profile_hash",
            "anchor_set_hash",
            "blocks",
            "warnings",
        },
        "result",
    )
    if result.get("source_sha256") != hashlib.sha256(request.input_bytes).hexdigest():
        raise ValueError("result source does not match the staged snapshot")
    if result.get("media_type") != request.expected_media_type:
        raise ValueError("result media type does not match the request")
    parser = _require_mapping(result["parser"], "result.parser")
    _require_exact_keys(parser, {"name", "version"}, "result.parser")
    if parser != request.expected_parser.to_dict():
        raise ValueError("result parser does not match the pinned request")
    if result.get("normalization_profile") != "nfc-lf-v1":
        raise ValueError("result normalization profile is unsupported")
    profile_hash = _require_sha256(
        result.get("config_profile_hash"), "result config profile"
    )
    anchor_set_hash = _require_sha256(
        result.get("anchor_set_hash"), "result anchor set"
    )
    blocks = result.get("blocks")
    if not isinstance(blocks, list) or not blocks or len(blocks) > policy.max_blocks:
        raise ValueError("result blocks are missing or exceed the configured limit")
    anchor_hashes: list[str] = []
    total_characters = 0
    for ordinal, block_value in enumerate(blocks):
        block = _require_mapping(block_value, f"blocks[{ordinal}]")
        _require_exact_keys(
            block,
            {"ordinal", "text", "block_type", "confidence", "anchor", "anchor_hash"},
            f"blocks[{ordinal}]",
        )
        if block.get("ordinal") != ordinal:
            raise ValueError("block ordinals must be contiguous")
        text = _require_normalized_text(
            block.get("text"), f"blocks[{ordinal}].text", maximum=policy.max_block_chars
        )
        total_characters += len(text)
        if total_characters > policy.max_total_chars:
            raise ValueError("result text exceeds the configured limit")
        _require_normalized_text(block.get("block_type"), "block type", maximum=64)
        _validate_confidence(block.get("confidence"))
        anchor = _require_mapping(block.get("anchor"), f"blocks[{ordinal}].anchor")
        _validate_anchor(anchor, request, profile_hash, text)
        anchor_hash = _require_sha256(block.get("anchor_hash"), "block anchor hash")
        if anchor_hash != canonical_sha256(anchor):
            raise ValueError("block anchor hash is not canonical")
        anchor_hashes.append(anchor_hash)
    expected_anchor_set_hash = canonical_sha256(
        {"schema_version": 1, "anchor_hashes": anchor_hashes}
    )
    if anchor_set_hash != expected_anchor_set_hash:
        raise ValueError("anchor set hash is not canonical")
    _validate_warnings(result.get("warnings"), len(blocks))


def _validate_anchor(
    anchor: Mapping[str, Any], request: SandboxRequest, profile_hash: str, text: str
) -> None:
    _require_exact_keys(
        anchor,
        {
            "schema_version",
            "kind",
            "source_sha256",
            "extraction_profile_hash",
            "locator",
            "text_fingerprint",
        },
        "anchor",
    )
    if anchor.get("schema_version") != 1:
        raise ValueError("anchor schema version is unsupported")
    expected_kind = _ANCHOR_KIND_BY_MEDIA_TYPE[request.expected_media_type]
    if anchor.get("kind") != expected_kind:
        raise ValueError("anchor kind is incompatible with the media type")
    if anchor.get("source_sha256") != hashlib.sha256(request.input_bytes).hexdigest():
        raise ValueError("anchor source does not match the staged snapshot")
    if anchor.get("extraction_profile_hash") != profile_hash:
        raise ValueError("anchor profile does not match the extraction result")
    fingerprint = _require_sha256(
        anchor.get("text_fingerprint"), "anchor text fingerprint"
    )
    if fingerprint != hashlib.sha256(_normalize_text(text).encode("utf-8")).hexdigest():
        raise ValueError("anchor fingerprint does not match the block text")
    locator = _require_mapping(anchor.get("locator"), "anchor locator")
    _validate_locator(
        expected_kind,
        locator,
        parser=request.expected_parser,
    )


def _validate_locator(
    kind: str, locator: Mapping[str, Any], *, parser: ParserIdentity
) -> None:
    if kind == "text_line":
        _require_exact_keys(locator, {"line", "start", "end"}, "text locator")
        _require_index(locator.get("line"), "text line", minimum=1)
        start = _require_index(locator.get("start"), "text start")
        end = _require_index(locator.get("end"), "text end")
        if end <= start:
            raise ValueError("text locator end must follow start")
        return
    if kind == "pdf_block":
        _require_exact_keys(locator, {"page", "block_id", "bbox"}, "PDF locator")
        _require_index(locator.get("page"), "PDF page")
        _require_normalized_text(locator.get("block_id"), "PDF block id")
        _validate_bbox(locator.get("bbox"))
        return
    if kind == "image_bbox":
        _require_exact_keys(locator, {"image_id", "bbox"}, "image locator")
        _require_normalized_text(locator.get("image_id"), "image id")
        _validate_bbox(locator.get("bbox"))
        return
    if kind == "docx_paragraph":
        allowed = {"paragraph", "table"}
        if not set(locator) <= allowed or "paragraph" not in locator:
            raise ValueError("DOCX locator has invalid fields")
        _require_index(locator.get("paragraph"), "DOCX paragraph")
        if "table" in locator:
            table = _require_mapping(locator["table"], "DOCX table path")
            _require_exact_keys(
                table, {"index", "row", "cell", "paragraph"}, "DOCX table path"
            )
            for field in ("index", "row", "cell", "paragraph"):
                _require_index(table.get(field), f"DOCX table {field}")
        return
    if kind == "xlsx_cell":
        _require_exact_keys(
            locator,
            {"sheet", "cell", "row", "column"},
            "XLSX locator",
        )
        _require_normalized_text(locator.get("sheet"), "XLSX sheet")
        _require_normalized_text(locator.get("cell"), "XLSX cell")
        _require_index(locator.get("row"), "XLSX row", minimum=1)
        _require_index(locator.get("column"), "XLSX column", minimum=1)
        return
    if kind != "hwp_paragraph":
        raise ValueError("anchor kind is unsupported")
    allowed = {"parser", "parser_version", "section", "paragraph", "table", "footnote"}
    if not {"parser", "parser_version", "section", "paragraph"} <= set(locator):
        raise ValueError("HWP locator is missing its structural base")
    if not set(locator) <= allowed:
        raise ValueError("HWP locator has unknown fields")
    if (
        locator.get("parser") != parser.name
        or locator.get("parser_version") != parser.version
    ):
        raise ValueError("HWP locator parser identity does not match the request")
    _require_index(locator.get("section"), "HWP section")
    _require_index(locator.get("paragraph"), "HWP paragraph")
    if "table" in locator and "footnote" in locator:
        raise ValueError("HWP table and footnote paths are mutually exclusive")
    if "table" in locator:
        table = _require_mapping(locator["table"], "HWP table path")
        _require_exact_keys(
            table,
            {"index", "block", "row", "cell", "paragraph"},
            "HWP table path",
        )
        for field in ("index", "block", "row", "cell", "paragraph"):
            _require_index(table.get(field), f"HWP table {field}")
    if "footnote" in locator:
        footnote = _require_mapping(locator["footnote"], "HWP footnote path")
        _require_exact_keys(footnote, {"index", "paragraph"}, "HWP footnote path")
        _require_index(footnote.get("index"), "HWP footnote index")
        _require_index(footnote.get("paragraph"), "HWP footnote paragraph")


def _validate_bbox(value: object) -> None:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("bbox must contain four coordinates")
    coordinates: list[float] = []
    for coordinate in value:
        if (
            isinstance(coordinate, bool)
            or not isinstance(coordinate, (int, float))
            or not math.isfinite(coordinate)
            or not 0 <= coordinate <= 1
        ):
            raise ValueError("bbox coordinate is outside [0, 1]")
        coordinates.append(float(coordinate))
    if coordinates[0] >= coordinates[2] or coordinates[1] >= coordinates[3]:
        raise ValueError("bbox must have positive area")


def _validate_confidence(value: object) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError("block confidence is invalid")


def _validate_warnings(value: object, block_count: int) -> None:
    if not isinstance(value, list):
        raise ValueError("warnings must be an array")
    for index, warning_value in enumerate(value):
        warning = _require_mapping(warning_value, f"warnings[{index}]")
        _require_exact_keys(warning, {"code", "message", "block_ordinal"}, "warning")
        if warning.get("code") not in _WARNING_CODES:
            raise ValueError("warning code is unsupported")
        _require_normalized_text(warning.get("message"), "warning message", maximum=512)
        block_ordinal = warning.get("block_ordinal")
        if block_ordinal is not None:
            if _require_index(block_ordinal, "warning block ordinal") >= block_count:
                raise ValueError("warning references an unknown block")


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any], expected: set[str], label: str
) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} fields do not match the protocol")


def _require_normalized_text(value: object, label: str, *, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{label} must be bounded non-empty text")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError(f"{label} must contain Unicode scalar values") from error
    if _normalize_text(value) != value:
        raise ValueError(f"{label} must use NFC/LF normalization")
    return value


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")
    return value


def _require_index(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def _canonicalize_json(value: object) -> JsonValue:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON numbers must be finite")
        rounded = round(value, 6)
        if rounded == 0:
            return 0
        return int(rounded) if rounded.is_integer() else rounded
    if isinstance(value, str):
        return _normalize_text(value)
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("canonical JSON keys must be strings")
            normalized_key = _normalize_text(key)
            if normalized_key in result:
                raise ValueError("canonical JSON has colliding normalized keys")
            result[normalized_key] = _canonicalize_json(child)
        return result
    if isinstance(value, Sequence) and not isinstance(
        value, (bytes, bytearray, memoryview)
    ):
        return [_canonicalize_json(child) for child in value]
    raise ValueError("canonical JSON value type is unsupported")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _canonicalize_json(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _reject_non_scalar_unicode(value: object) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise ValueError(
                "parser result contains a non-scalar Unicode value"
            ) from error
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _reject_non_scalar_unicode(key)
            _reject_non_scalar_unicode(child)
        return
    if isinstance(value, list):
        for child in value:
            _reject_non_scalar_unicode(child)
