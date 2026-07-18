from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import sandbox_runner
from sandbox_runner import (
    InputTooLargeError,
    RESOURCE_METRICS_FIELD,
    SandboxPolicy,
    SandboxRequest,
    _bounded_capture,
    _safe_json_object,
    _stage_bounded_input,
    _strip_resource_metrics,
    build_docker_command,
    execute_sandbox,
)


SPIKE_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def policy() -> SandboxPolicy:
    return SandboxPolicy.from_json(SPIKE_ROOT / "policy.v1.json")


def _request(
    *,
    probe: str | None = None,
    network_probe_host: str = "1.1.1.1",
    network_probe_port: int = 53,
    input_bytes: bytes = b"%PDF-1.7\n",
    collect_resource_usage: bool = False,
) -> SandboxRequest:
    return SandboxRequest(
        image="axit-ingestion-g0@sha256:" + "a" * 64,
        input_bytes=input_bytes,
        original_filename="meeting.pdf",
        container_name="axit-g0-test",
        probe=probe,
        network_probe_host=network_probe_host,
        network_probe_port=network_probe_port,
        collect_resource_usage=collect_resource_usage,
    )


def _staged_path(tmp_path: Path, contents: bytes) -> Path:
    staged = tmp_path / "host-owned-stage"
    staged.write_bytes(contents)
    return staged


def test_command_enforces_the_complete_static_sandbox_contract(
    tmp_path: Path, policy: SandboxPolicy
) -> None:
    request = _request()
    command = build_docker_command(
        request,
        policy,
        staged_input_path=_staged_path(tmp_path, request.input_bytes),
    )

    assert command[:2] == ["docker", "run"]
    for exact in (
        "--rm",
        "--pull=never",
        "--log-driver=none",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true",
        "--ipc=none",
        "--pids-limit=64",
        "--cpus=1.0",
        "--memory=805306368",
        "--memory-swap=805306368",
        "--ulimit=nofile=256:256",
        "--user=10001:10001",
    ):
        assert exact in command

    assert "--security-opt=seccomp=unconfined" not in command
    assert all("docker.sock" not in value for value in command)
    assert all("DATABASE_URL" not in value for value in command)
    assert all("API_KEY" not in value for value in command)
    assert all("SESSION" not in value for value in command)

    mount = command[command.index("--mount") + 1]
    assert mount.startswith("type=bind,src=")
    assert mount.endswith(",dst=/input/source,readonly")
    assert command[command.index("--tmpfs") + 1] == (
        "/tmp:rw,noexec,nosuid,nodev,size=134217728"
    )

    env_values = [
        command[index + 1]
        for index, item in enumerate(command)
        if item == "--env"
    ]
    assert env_values == [
        "HOME=/tmp",
        "LANG=C.UTF-8",
        "LC_ALL=C.UTF-8",
        "PYTHONHASHSEED=0",
        "TMPDIR=/tmp",
    ]


def test_probe_is_an_allowlisted_cli_argument_not_host_environment(
    tmp_path: Path, policy: SandboxPolicy
) -> None:
    request = _request(
        probe="network",
        network_probe_host="g0-probe",
        network_probe_port=18_080,
    )
    command = build_docker_command(
        request,
        policy,
        staged_input_path=_staged_path(tmp_path, request.input_bytes),
    )

    assert command[-6:] == [
        "--probe",
        "network",
        "--network-probe-host",
        "g0-probe",
        "--network-probe-port",
        "18080",
    ]
    assert all("AXIT_G0_PROBE" not in value for value in command)


def test_opt_in_resource_telemetry_uses_a_fresh_cli_nonce(
    tmp_path: Path, policy: SandboxPolicy
) -> None:
    request = _request(collect_resource_usage=True)
    nonce = "a" * 32
    command = build_docker_command(
        request,
        policy,
        staged_input_path=_staged_path(tmp_path, request.input_bytes),
        resource_metrics_nonce=nonce,
    )

    assert command[-2:] == ["--resource-metrics-nonce", nonce]
    assert all("resource-metrics-path" not in value for value in command)

    with pytest.raises(ValueError, match="nonce must match"):
        build_docker_command(
            request,
            policy,
            staged_input_path=_staged_path(tmp_path, request.input_bytes),
        )

    with pytest.raises(ValueError, match="nonce is invalid"):
        build_docker_command(
            request,
            policy,
            staged_input_path=_staged_path(tmp_path, request.input_bytes),
            resource_metrics_nonce="invalid",
        )


@pytest.mark.parametrize("probe", ["unknown", "secret=leak", "../network", ""])
def test_unrecognized_probe_is_rejected_before_docker(
    tmp_path: Path, policy: SandboxPolicy, probe: str
) -> None:
    with pytest.raises(ValueError, match="probe"):
        request = _request(probe=probe)
        build_docker_command(
            request,
            policy,
            staged_input_path=_staged_path(tmp_path, request.input_bytes),
        )


@pytest.mark.parametrize(
    ("host", "port"),
    [
        ("", 18_080),
        ("g0/probe", 18_080),
        ("g0-probe", 0),
        ("g0-probe", 65_536),
    ],
)
def test_invalid_controlled_network_target_is_rejected_before_docker(
    tmp_path: Path, policy: SandboxPolicy, host: str, port: int
) -> None:
    request = _request(
        probe="network", network_probe_host=host, network_probe_port=port
    )

    with pytest.raises(ValueError, match="network probe"):
        build_docker_command(
            request,
            policy,
            staged_input_path=_staged_path(tmp_path, request.input_bytes),
        )


def test_mutable_input_is_rejected_before_staging(
    tmp_path: Path, policy: SandboxPolicy
) -> None:
    request = SandboxRequest(
        image="axit-ingestion-g0@sha256:" + "a" * 64,
        input_bytes=bytearray(b"%PDF-1.7\n"),  # type: ignore[arg-type]
        original_filename="meeting.pdf",
        container_name="axit-g0-test",
    )

    with pytest.raises(ValueError, match="immutable bytes"):
        build_docker_command(
            request,
            policy,
            staged_input_path=_staged_path(tmp_path, b"%PDF-1.7\n"),
        )


def test_policy_parser_rejects_unknown_or_unbounded_values(tmp_path: Path) -> None:
    raw = json.loads((SPIKE_ROOT / "policy.v1.json").read_text(encoding="utf-8"))
    raw["sandbox"]["wall_timeout_seconds"] = 0
    broken = tmp_path / "policy.json"
    broken.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="wall_timeout_seconds"):
        SandboxPolicy.from_json(broken)


def _python_process(source: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", source],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_capture_is_bounded_without_buffering_an_output_flood() -> None:
    process = _python_process("import sys; sys.stdout.buffer.write(b'x' * 1000000)")
    stdout, stderr, error = _bounded_capture(
        process, stdout_limit=1024, stderr_limit=1024, timeout_seconds=5
    )
    process.kill()
    process.wait(timeout=5)

    assert error == "PARSER_OUTPUT_LIMIT"
    assert len(stdout) == 1024
    assert stderr == b""


def test_capture_returns_a_typed_wall_timeout() -> None:
    process = _python_process("import time; time.sleep(10)")
    stdout, stderr, error = _bounded_capture(
        process, stdout_limit=1024, stderr_limit=1024, timeout_seconds=0.05
    )
    process.kill()
    process.wait(timeout=5)

    assert error == "PARSER_TIMEOUT"
    assert stdout == b""
    assert stderr == b""


def test_supervisor_accepts_exactly_one_versioned_json_object() -> None:
    assert _safe_json_object(b'{"schema_version":1,"ok":true}') == {
        "schema_version": 1,
        "ok": True,
    }
    for invalid in (
        b"not-json",
        b"[]",
        b'{"schema_version":2,"ok":true}',
        b'{"schema_version":1}',
        b'{"schema_version":1,"ok":true}\n{}',
        b'{"schema_version":1,"ok":true,"ok":false}',
        b'{"schema_version":1,"ok":true,"value":NaN}',
        b'{"schema_version":1,"ok":true,"value":"\\ud800"}',
        (b'[' * 2000) + (b']' * 2000),
    ):
        with pytest.raises(ValueError):
            _safe_json_object(invalid)


def test_input_is_bounded_and_staged_as_an_immutable_snapshot() -> None:
    original = b"%PDF-1.7\nfirst snapshot"

    with _stage_bounded_input(original, max_bytes=len(original)) as staged:
        assert staged.data == original
        assert staged.path.read_bytes() == original
        assert staged.source_sha256 == hashlib.sha256(original).hexdigest()
        assert staged.path.name == "source"

    assert not staged.path.exists()


def test_oversized_input_is_rejected_before_docker() -> None:
    source = b"%PDF-1.7\n" + b"x" * 20

    with pytest.raises(InputTooLargeError, match="byte limit"):
        with _stage_bounded_input(source, max_bytes=8):
            raise AssertionError("oversized input must not be yielded")


def test_execute_returns_typed_oversized_error_without_starting_docker(
    monkeypatch: pytest.MonkeyPatch, policy: SandboxPolicy
) -> None:
    request = _request(input_bytes=b"%PDF-1.7\n" + b"x" * (policy.max_input_bytes + 1))

    def fail_if_docker_starts(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("oversized input must never start docker")

    monkeypatch.setattr(sandbox_runner.subprocess, "Popen", fail_if_docker_starts)
    execution = execute_sandbox(request, policy)

    assert execution.ok is False
    assert execution.error_code == "INPUT_TOO_LARGE"
    assert execution.payload is None
    assert execution.exit_code is None
    assert execution.source_sha256 == hashlib.sha256(request.input_bytes).hexdigest()
    assert execution.duration_ms >= 0


def test_resource_telemetry_is_strictly_stripped_before_protocol_validation(
    policy: SandboxPolicy,
) -> None:
    payload = {
        "schema_version": 1,
        "ok": True,
        "probe": {"kind": "network"},
        RESOURCE_METRICS_FIELD: {
            "schema_version": 1,
            "nonce": "a" * 32,
            "peak_memory_bytes": 12_345,
            "peak_pids": 6,
        },
    }

    stripped, usage = _strip_resource_metrics(
        payload,
        expected_nonce="a" * 32,
        policy=policy,
    )

    assert stripped == {"schema_version": 1, "ok": True, "probe": {"kind": "network"}}
    assert usage is not None
    assert usage.peak_memory_bytes == 12_345
    assert usage.peak_pids == 6


@pytest.mark.parametrize(
    "telemetry",
    [
        None,
        {},
        {
            "schema_version": 1,
            "nonce": "b" * 32,
            "peak_memory_bytes": 1,
            "peak_pids": 1,
        },
        {
            "schema_version": 1,
            "nonce": "a" * 32,
            "peak_memory_bytes": 0,
            "peak_pids": 1,
        },
        {
            "schema_version": 1,
            "nonce": "a" * 32,
            "peak_memory_bytes": 1,
            "peak_pids": 65,
        },
    ],
)
def test_resource_telemetry_rejects_missing_stale_or_out_of_bounds_values(
    policy: SandboxPolicy, telemetry: object
) -> None:
    payload = {"schema_version": 1, "ok": True, "probe": {"kind": "network"}}
    if telemetry is not None:
        payload[RESOURCE_METRICS_FIELD] = telemetry

    with pytest.raises(ValueError, match="resource metrics telemetry"):
        _strip_resource_metrics(payload, expected_nonce="a" * 32, policy=policy)


def test_non_opt_in_payload_cannot_smuggle_telemetry(policy: SandboxPolicy) -> None:
    with pytest.raises(ValueError, match="unexpected resource metrics"):
        _strip_resource_metrics(
            {
                "schema_version": 1,
                "ok": True,
                RESOURCE_METRICS_FIELD: None,
            },
            expected_nonce=None,
            policy=policy,
        )


def test_execute_exposes_resource_evidence_when_requested(
    monkeypatch: pytest.MonkeyPatch, policy: SandboxPolicy
) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = io.BytesIO(
                (
                    b'{"schema_version":1,"ok":true,"probe":{"kind":"network"},'
                    b'"_axit_resource_metrics":{"schema_version":1,'
                    b'"nonce":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
                    b'"peak_memory_bytes":12345,"peak_pids":6}}'
                )
            )
            self.stderr = io.BytesIO()

        def kill(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return 0

    monkeypatch.setattr(
        sandbox_runner,
        "inspect_input",
        lambda *_args, **_kwargs: SimpleNamespace(
            media_type=SimpleNamespace(value="application/pdf")
        ),
    )
    monkeypatch.setattr(
        sandbox_runner.subprocess,
        "Popen",
        lambda *_args, **_kwargs: FakeProcess(),
    )

    monkeypatch.setattr(sandbox_runner.secrets, "token_hex", lambda _bytes: "a" * 32)
    request = _request(probe="network", collect_resource_usage=True)
    execution = execute_sandbox(request, policy)

    assert execution.ok is True
    assert execution.peak_memory_bytes == 12_345
    assert execution.peak_pids == 6
    assert execution.source_sha256 == hashlib.sha256(request.input_bytes).hexdigest()
    assert execution.payload == {
        "schema_version": 1,
        "ok": True,
        "probe": {"kind": "network"},
    }
