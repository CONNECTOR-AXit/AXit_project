from __future__ import annotations

import json
import hashlib
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Mapping, TypedDict

from axit_ingestion_spike.media import inspect_input
from axit_ingestion_spike.models import ExtractionException, ExtractionPolicy
from parser_protocol import ProtocolBounds, validate_parser_payload


ALLOWED_PROBES = frozenset({"network", "secret", "filesystem", "timeout", "output"})
SAFE_CONTAINER_ENV = (
    "HOME=/tmp",
    "LANG=C.UTF-8",
    "LC_ALL=C.UTF-8",
    "PYTHONHASHSEED=0",
    "TMPDIR=/tmp",
)
RESOURCE_METRICS_FIELD = "_axit_resource_metrics"
RESOURCE_METRICS_NONCE_BYTES = 16


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    wall_timeout_seconds: float
    stop_grace_seconds: float
    memory_bytes: int
    memory_swap_bytes: int
    pids: int
    cpus: float
    tmpfs_bytes: int
    uid: int
    gid: int
    max_stdout_bytes: int
    max_stderr_bytes: int
    max_blocks: int
    max_block_chars: int
    max_total_chars: int
    max_input_bytes: int = 20 * 1024 * 1024

    @classmethod
    def from_json(cls, path: Path) -> "SandboxPolicy":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != 1:
            raise ValueError("unsupported policy schema_version")
        sandbox = raw["sandbox"]
        result = raw["result"]
        policy = cls(
            wall_timeout_seconds=float(sandbox["wall_timeout_seconds"]),
            stop_grace_seconds=float(sandbox["stop_grace_seconds"]),
            memory_bytes=int(sandbox["memory_bytes"]),
            memory_swap_bytes=int(sandbox["memory_swap_bytes"]),
            pids=int(sandbox["pids"]),
            cpus=float(sandbox["cpus"]),
            tmpfs_bytes=int(sandbox["tmpfs_bytes"]),
            uid=int(sandbox["uid"]),
            gid=int(sandbox["gid"]),
            max_stdout_bytes=int(result["max_stdout_bytes"]),
            max_stderr_bytes=int(result["max_stderr_bytes"]),
            max_blocks=int(result["max_blocks"]),
            max_block_chars=int(result["max_block_chars"]),
            max_total_chars=int(result["max_total_chars"]),
            max_input_bytes=int(raw["input"]["max_bytes"]),
        )
        policy._validate()
        return policy

    def _validate(self) -> None:
        positive = {
            "wall_timeout_seconds": self.wall_timeout_seconds,
            "stop_grace_seconds": self.stop_grace_seconds,
            "memory_bytes": self.memory_bytes,
            "memory_swap_bytes": self.memory_swap_bytes,
            "pids": self.pids,
            "cpus": self.cpus,
            "tmpfs_bytes": self.tmpfs_bytes,
            "max_stdout_bytes": self.max_stdout_bytes,
            "max_stderr_bytes": self.max_stderr_bytes,
            "max_blocks": self.max_blocks,
            "max_block_chars": self.max_block_chars,
            "max_total_chars": self.max_total_chars,
            "max_input_bytes": self.max_input_bytes,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.memory_bytes != self.memory_swap_bytes:
            raise ValueError("memory and memory-swap must match")
        if self.uid == 0 or self.gid == 0:
            raise ValueError("sandbox user must be non-root")
        if self.wall_timeout_seconds > 120:
            raise ValueError("wall_timeout_seconds exceeds approved spike ceiling")


@dataclass(frozen=True, slots=True)
class SandboxRequest:
    image: str
    input_bytes: bytes
    original_filename: str
    container_name: str | None = None
    probe: str | None = None
    network_probe_host: str = "1.1.1.1"
    network_probe_port: int = 53
    collect_resource_usage: bool = False


@dataclass(frozen=True, slots=True)
class SandboxExecution:
    ok: bool
    error_code: str | None
    payload: Mapping[str, Any] | None
    exit_code: int | None
    duration_ms: int
    stdout_bytes: int
    stderr_bytes: int
    killed: bool
    source_sha256: str | None = None
    peak_memory_bytes: int | None = None
    peak_pids: int | None = None


class InputTooLargeError(ValueError):
    """The host-owned immutable input snapshot exceeds the approved bound."""


def _validate_request(request: SandboxRequest) -> None:
    if not isinstance(request.input_bytes, bytes):
        raise ValueError("input_bytes must be immutable bytes")
    if request.probe not in ALLOWED_PROBES | {None}:
        raise ValueError("probe is not allowlisted")
    if not request.original_filename or any(
        character in request.original_filename for character in ("/", "\\", "\0")
    ):
        raise ValueError("original_filename must be a basename")
    if not request.image or any(character.isspace() for character in request.image):
        raise ValueError("image must be one token")
    if request.container_name is not None and not request.container_name.startswith("axit-g0-"):
        raise ValueError("container_name must use the axit-g0 prefix")
    if (
        not isinstance(request.network_probe_host, str)
        or not request.network_probe_host
        or len(request.network_probe_host) > 253
        or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for character in request.network_probe_host)
    ):
        raise ValueError("network probe host is invalid")
    if (
        isinstance(request.network_probe_port, bool)
        or not isinstance(request.network_probe_port, int)
        or not 1 <= request.network_probe_port <= 65_535
    ):
        raise ValueError("network probe port is invalid")
    if not isinstance(request.collect_resource_usage, bool):
        raise ValueError("collect_resource_usage must be boolean")


def build_docker_command(
    request: SandboxRequest,
    policy: SandboxPolicy,
    *,
    staged_input_path: Path,
    resource_metrics_nonce: str | None = None,
) -> list[str]:
    _validate_request(request)
    if request.collect_resource_usage != (resource_metrics_nonce is not None):
        raise ValueError("resource metrics nonce must match collection request")
    if resource_metrics_nonce is not None and not _is_resource_metrics_nonce(
        resource_metrics_nonce
    ):
        raise ValueError("resource metrics nonce is invalid")
    if staged_input_path.is_symlink() or not staged_input_path.is_file():
        raise ValueError("staged_input_path must be a regular file")
    name = request.container_name or f"axit-g0-{uuid.uuid4().hex}"
    source = staged_input_path.resolve()
    command = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--log-driver=none",
        f"--name={name}",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true",
        "--ipc=none",
        f"--pids-limit={policy.pids}",
        f"--cpus={policy.cpus}",
        f"--memory={policy.memory_bytes}",
        f"--memory-swap={policy.memory_swap_bytes}",
        "--ulimit=nofile=256:256",
        f"--user={policy.uid}:{policy.gid}",
        "--mount",
        f"type=bind,src={source},dst=/input/source,readonly",
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size={policy.tmpfs_bytes}",
    ]
    for value in SAFE_CONTAINER_ENV:
        command.extend(("--env", value))
    command.extend(
        (
            request.image,
            "python",
            "-m",
            "axit_ingestion_spike.worker",
            "--input",
            "/input/source",
            "--filename",
            request.original_filename,
        )
    )
    if request.probe is not None:
        command.extend(("--probe", request.probe))
    if request.probe == "network":
        command.extend(
            (
                "--network-probe-host",
                request.network_probe_host,
                "--network-probe-port",
                str(request.network_probe_port),
            )
        )
    if resource_metrics_nonce is not None:
        command.extend(("--resource-metrics-nonce", resource_metrics_nonce))
    return command


def _kill_container(container_name: str, *, docker_binary: str = "docker") -> None:
    subprocess.run(
        [docker_binary, "rm", "--force", container_name],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )


def _bounded_capture(
    process: subprocess.Popen[bytes],
    *,
    stdout_limit: int,
    stderr_limit: int,
    timeout_seconds: float,
) -> tuple[bytes, bytes, str | None]:
    if process.stdout is None or process.stderr is None:
        raise RuntimeError("process pipes are unavailable")
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": stdout_limit, "stderr": stderr_limit}
    overflow = threading.Event()
    completed = {"stdout": threading.Event(), "stderr": threading.Event()}
    overflow_code: list[str] = []

    def read_bounded(stream_name: str, stream: BinaryIO) -> None:
        try:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    return
                buffer = buffers[stream_name]
                remaining_capacity = limits[stream_name] - len(buffer)
                if len(chunk) > remaining_capacity:
                    buffer.extend(chunk[: max(remaining_capacity, 0)])
                    overflow_code.append(
                        "PARSER_OUTPUT_LIMIT"
                        if stream_name == "stdout"
                        else "PARSER_LOG_LIMIT"
                    )
                    overflow.set()
                    return
                buffer.extend(chunk)
        finally:
            completed[stream_name].set()

    threads = [
        threading.Thread(
            target=read_bounded,
            args=("stdout", process.stdout),
            name="g0-stdout-reader",
            daemon=True,
        ),
        threading.Thread(
            target=read_bounded,
            args=("stderr", process.stderr),
            name="g0-stderr-reader",
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()

    deadline = time.monotonic() + timeout_seconds
    while True:
        if overflow.is_set():
            return bytes(buffers["stdout"]), bytes(buffers["stderr"]), overflow_code[0]
        if all(event.is_set() for event in completed.values()):
            for thread in threads:
                thread.join(timeout=0.1)
            return bytes(buffers["stdout"]), bytes(buffers["stderr"]), None
        if time.monotonic() >= deadline:
            return bytes(buffers["stdout"]), bytes(buffers["stderr"]), "PARSER_TIMEOUT"
        time.sleep(0.01)


def _safe_json_object(raw: bytes) -> Mapping[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("parser output contains duplicate JSON keys")
            result[key] = value
        return result

    try:
        text = raw.decode("utf-8")
        parsed = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("parser output contains a non-finite number")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ValueError("parser output must be one UTF-8 JSON value") from exc
    if not isinstance(parsed, dict):
        raise ValueError("parser output must be a JSON object")
    _reject_non_scalar_unicode(parsed)
    if parsed.get("schema_version") != 1:
        raise ValueError("unsupported parser output schema_version")
    if not isinstance(parsed.get("ok"), bool):
        raise ValueError("parser output is missing boolean ok")
    return parsed


def _reject_non_scalar_unicode(value: object) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise ValueError("parser output contains a non-scalar Unicode value") from error
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _reject_non_scalar_unicode(key)
            _reject_non_scalar_unicode(child)
        return
    if isinstance(value, list):
        for child in value:
            _reject_non_scalar_unicode(child)


@dataclass(frozen=True, slots=True)
class StagedInput:
    path: Path
    source_sha256: str
    data: bytes


@contextmanager
def _stage_bounded_input(
    source_bytes: bytes,
    *,
    max_bytes: int,
) -> Any:
    """Write one caller-owned immutable byte snapshot and bind only that copy."""

    if isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if not isinstance(source_bytes, bytes):
        raise ValueError("source_bytes must be immutable bytes")
    if len(source_bytes) > max_bytes:
        raise InputTooLargeError("input exceeds configured byte limit")
    directory = Path(tempfile.mkdtemp(prefix="axit-g0-stage-"))
    staged_path = directory / "source"
    digest = hashlib.sha256(source_bytes)
    try:
        with staged_path.open("xb") as staged_file:
            staged_file.write(source_bytes)
            staged_file.flush()
            os.fsync(staged_file.fileno())
        staged_path.chmod(0o444)
        yield StagedInput(staged_path, digest.hexdigest(), source_bytes)
    finally:
        try:
            staged_path.chmod(0o600)
        except OSError:
            pass
        shutil.rmtree(directory, ignore_errors=True)


def _validate_probe_payload(payload: Mapping[str, Any], expected_probe: str) -> None:
    if set(payload) != {"schema_version", "ok", "probe"}:
        raise ValueError("probe envelope fields do not match the protocol")
    if payload.get("schema_version") != 1 or payload.get("ok") is not True:
        raise ValueError("probe envelope header is invalid")
    probe = payload.get("probe")
    if not isinstance(probe, Mapping) or probe.get("kind") != expected_probe:
        raise ValueError("probe result kind does not match the request")


@dataclass(frozen=True, slots=True)
class _ResourceUsage:
    peak_memory_bytes: int
    peak_pids: int


class _ExecutionMetadata(TypedDict):
    source_sha256: str
    peak_memory_bytes: int | None
    peak_pids: int | None


def _is_resource_metrics_nonce(value: str) -> bool:
    return len(value) == RESOURCE_METRICS_NONCE_BYTES * 2 and all(
        character in "0123456789abcdef" for character in value
    )


def _strip_resource_metrics(
    payload: Mapping[str, Any],
    *,
    expected_nonce: str | None,
    policy: SandboxPolicy,
) -> tuple[Mapping[str, Any], _ResourceUsage | None]:
    """Remove one opt-in cgroup telemetry field before protocol validation.

    The parser protocol continues to receive its exact original envelope.  A
    collection request requires a fresh, bounded schema with a host-generated
    nonce; stale, forged-shape, or out-of-policy telemetry therefore becomes a
    typed invalid parser result rather than silent evidence loss.
    """

    stripped = dict(payload)
    missing = object()
    telemetry = stripped.pop(RESOURCE_METRICS_FIELD, missing)
    if expected_nonce is None:
        if telemetry is not missing:
            raise ValueError("unexpected resource metrics telemetry")
        return stripped, None
    if not isinstance(telemetry, Mapping) or set(telemetry) != {
        "schema_version",
        "nonce",
        "peak_memory_bytes",
        "peak_pids",
    }:
        raise ValueError("resource metrics telemetry is missing or malformed")
    if telemetry.get("schema_version") != 1 or telemetry.get("nonce") != expected_nonce:
        raise ValueError("resource metrics telemetry does not bind this execution")
    peak_memory = telemetry.get("peak_memory_bytes")
    peak_pids = telemetry.get("peak_pids")
    if (
        isinstance(peak_memory, bool)
        or not isinstance(peak_memory, int)
        or not 0 < peak_memory <= policy.memory_bytes
        or isinstance(peak_pids, bool)
        or not isinstance(peak_pids, int)
        or not 0 < peak_pids <= policy.pids
    ):
        raise ValueError("resource metrics telemetry is outside sandbox limits")
    return stripped, _ResourceUsage(
        peak_memory_bytes=peak_memory,
        peak_pids=peak_pids,
    )


def execute_sandbox(
    request: SandboxRequest,
    policy: SandboxPolicy,
    *,
    docker_binary: str = "docker",
) -> SandboxExecution:
    _validate_request(request)
    start = time.monotonic()
    source_sha256 = hashlib.sha256(request.input_bytes).hexdigest()
    try:
        with _stage_bounded_input(
            request.input_bytes,
            max_bytes=policy.max_input_bytes,
        ) as staged:
            try:
                media = inspect_input(
                    staged.data,
                    request.original_filename,
                    ExtractionPolicy(max_input_bytes=policy.max_input_bytes),
                )
            except ExtractionException as error:
                return SandboxExecution(
                    ok=False,
                    error_code=error.error.code.value,
                    payload=None,
                    exit_code=None,
                    duration_ms=round((time.monotonic() - start) * 1000),
                    stdout_bytes=0,
                    stderr_bytes=0,
                    killed=False,
                    source_sha256=staged.source_sha256,
                )
            return _execute_staged_sandbox(
                request,
                policy,
                staged=staged,
                expected_media_type=media.media_type.value,
                start=start,
                docker_binary=docker_binary,
            )
    except InputTooLargeError:
        return SandboxExecution(
            ok=False,
            error_code="INPUT_TOO_LARGE",
            payload=None,
            exit_code=None,
            duration_ms=round((time.monotonic() - start) * 1000),
            stdout_bytes=0,
            stderr_bytes=0,
            killed=False,
            source_sha256=source_sha256,
        )


def _execute_staged_sandbox(
    request: SandboxRequest,
    policy: SandboxPolicy,
    *,
    staged: StagedInput,
    expected_media_type: str,
    start: float,
    docker_binary: str,
) -> SandboxExecution:
    container_name = request.container_name or f"axit-g0-{uuid.uuid4().hex}"
    concrete_request = SandboxRequest(
        image=request.image,
        input_bytes=request.input_bytes,
        original_filename=request.original_filename,
        container_name=container_name,
        probe=request.probe,
        network_probe_host=request.network_probe_host,
        network_probe_port=request.network_probe_port,
        collect_resource_usage=request.collect_resource_usage,
    )
    resource_metrics_nonce = (
        secrets.token_hex(RESOURCE_METRICS_NONCE_BYTES)
        if request.collect_resource_usage
        else None
    )
    command = build_docker_command(
        concrete_request,
        policy,
        staged_input_path=staged.path,
        resource_metrics_nonce=resource_metrics_nonce,
    )
    command[0] = docker_binary
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr, boundary_error = _bounded_capture(
        process,
        stdout_limit=policy.max_stdout_bytes,
        stderr_limit=policy.max_stderr_bytes,
        timeout_seconds=policy.wall_timeout_seconds,
    )
    killed = boundary_error is not None
    if killed:
        _kill_container(container_name, docker_binary=docker_binary)
        process.kill()
    try:
        exit_code = process.wait(timeout=policy.stop_grace_seconds + 10)
    except subprocess.TimeoutExpired:
        _kill_container(container_name, docker_binary=docker_binary)
        process.kill()
        exit_code = process.wait(timeout=5)
        boundary_error = boundary_error or "PARSER_TIMEOUT"
        killed = True

    duration_ms = round((time.monotonic() - start) * 1000)
    common: _ExecutionMetadata = {
        "source_sha256": staged.source_sha256,
        "peak_memory_bytes": None,
        "peak_pids": None,
    }
    if boundary_error is not None:
        return SandboxExecution(
            ok=False,
            error_code=boundary_error,
            payload=None,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout_bytes=len(stdout),
            stderr_bytes=len(stderr),
            killed=killed,
            **common,
        )
    if exit_code not in (0, 2):
        return SandboxExecution(
            ok=False,
            error_code="PARSER_CRASH",
            payload=None,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout_bytes=len(stdout),
            stderr_bytes=len(stderr),
            killed=exit_code in (-9, 137),
            **common,
        )
    if stderr:
        return SandboxExecution(
            ok=False,
            error_code="PARSER_LOG_OUTPUT",
            payload=None,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout_bytes=len(stdout),
            stderr_bytes=len(stderr),
            killed=False,
            **common,
        )
    try:
        payload = _safe_json_object(stdout)
        payload, usage = _strip_resource_metrics(
            payload,
            expected_nonce=resource_metrics_nonce,
            policy=policy,
        )
        if usage is not None:
            common["peak_memory_bytes"] = usage.peak_memory_bytes
            common["peak_pids"] = usage.peak_pids
        if request.probe is not None:
            _validate_probe_payload(payload, request.probe)
        else:
            validate_parser_payload(
                payload,
                expected_source_sha256=staged.source_sha256,
                expected_media_type=expected_media_type,
                bounds=ProtocolBounds(
                    max_blocks=policy.max_blocks,
                    max_block_chars=policy.max_block_chars,
                    max_total_chars=policy.max_total_chars,
                ),
            )
    except ValueError:
        return SandboxExecution(
            ok=False,
            error_code="INVALID_PARSER_OUTPUT",
            payload=None,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout_bytes=len(stdout),
            stderr_bytes=len(stderr),
            killed=False,
            **common,
        )
    expected_exit_code = 0 if payload.get("ok") is True else 2
    if exit_code != expected_exit_code:
        return SandboxExecution(
            ok=False,
            error_code="PARSER_CRASH",
            payload=None,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout_bytes=len(stdout),
            stderr_bytes=len(stderr),
            killed=False,
            **common,
        )
    return SandboxExecution(
        ok=bool(payload["ok"]),
        error_code=None if payload["ok"] else str(payload.get("error", {}).get("code")),
        payload=payload,
        exit_code=exit_code,
        duration_ms=duration_ms,
        stdout_bytes=len(stdout),
        stderr_bytes=len(stderr),
        killed=False,
        **common,
    )
