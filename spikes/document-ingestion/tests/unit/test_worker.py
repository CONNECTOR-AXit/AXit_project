from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from axit_ingestion_spike import worker
from axit_ingestion_spike.models import ExtractionPolicy, load_spike_policy


def test_shared_policy_loader_matches_committed_g0_bounds() -> None:
    policy = load_spike_policy()

    assert policy == ExtractionPolicy()
    assert policy.max_image_pixels == 25_000_000
    assert policy.max_output_bytes == 1_048_576
    assert policy.max_blocks == 10_000


def test_worker_accepts_sandbox_runner_flags_and_emits_one_safe_json(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"%PDF-1.7\nsecret raw fixture text")

    serialized, status = worker.run(
        ["--input", str(source), "--filename", "spoofed.png"]
    )
    payload = json.loads(serialized)

    assert status == 2
    assert payload["schema_version"] == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "TYPE_MISMATCH"
    assert str(source) not in serialized
    assert "secret raw fixture text" not in serialized


def test_opt_in_runtime_metrics_attach_kernel_peaks_without_changing_normal_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nonce = "a" * 32
    monkeypatch.setattr(
        worker,
        "_read_cgroup_peak",
        lambda *paths: 12_345 if paths == worker._CGROUP_MEMORY_PEAK_PATHS else 6,
    )
    monkeypatch.setattr(
        worker,
        "_outbound_network_reachable",
        lambda _host, _port: False,
    )

    serialized, status = worker.run(
        [
            "--probe",
            "network",
            "--network-probe-host",
            "g0-probe",
            "--network-probe-port",
            "18080",
            "--resource-metrics-nonce",
            nonce,
        ]
    )
    payload = json.loads(serialized)

    assert status == 0
    assert payload[worker._RESOURCE_METRICS_FIELD] == {
        "schema_version": 1,
        "nonce": nonce,
        "peak_memory_bytes": 12_345,
        "peak_pids": 6,
    }

    regular_serialized, regular_status = worker.run(
        [
            "--probe",
            "network",
            "--network-probe-host",
            "g0-probe",
            "--network-probe-port",
            "18080",
        ]
    )
    assert regular_status == 0
    assert worker._RESOURCE_METRICS_FIELD not in json.loads(regular_serialized)


def test_runtime_metrics_reject_invalid_nonce_without_echoing_it() -> None:
    invalid_nonce = "not-a-safe-nonce"

    serialized, status = worker.run(
        ["--probe", "secret", "--resource-metrics-nonce", invalid_nonce]
    )

    assert status == 2
    assert json.loads(serialized)["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert invalid_nonce not in serialized


def test_worker_rejects_conflicting_input_forms_without_leaking_paths(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    serialized, status = worker.run([str(first), "--input", str(second)])

    assert status == 2
    assert json.loads(serialized)["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert str(first) not in serialized
    assert str(second) not in serialized


def test_cli_probes_are_allowlisted_and_return_bounded_structured_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        worker, "_outbound_network_reachable", lambda host, port: False
    )
    source = tmp_path / "source"
    source.write_bytes(b"x")

    serialized, status = worker.run(
        [
            "--input",
            str(source),
            "--filename",
            "source.pdf",
            "--probe",
            "network",
            "--network-probe-host",
            "g0-probe",
            "--network-probe-port",
            "18080",
        ]
    )
    payload = json.loads(serialized)

    assert status == 0
    assert payload == {
        "schema_version": 1,
        "ok": True,
        "probe": {
            "kind": "network",
            "outbound_network_reachable": False,
            "target_host": "g0-probe",
            "target_port": 18080,
        },
    }


def test_output_probe_exceeds_shared_host_capture_bound(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"x")

    serialized, status = worker.run(
        ["--input", str(source), "--filename", "source.pdf", "--probe", "output"]
    )

    assert status == 0
    assert len(serialized.encode("utf-8")) == load_spike_policy().max_output_bytes + 1


def test_secret_probe_detects_positive_control_names_without_echoing_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "g0-do-not-leak-this-value"
    monkeypatch.setenv("DATABASE_URL", canary)
    monkeypatch.setattr(
        worker,
        "_SECRET_MOUNT_CANDIDATES",
        (Path("/definitely-absent-g0-secret-mount"),),
    )

    serialized, status = worker.run(["--probe", "secret"])
    payload = json.loads(serialized)

    assert status == 0
    assert payload["probe"] == {
        "kind": "secret",
        "secret_mount_present": False,
        "sensitive_environment_present": True,
    }
    assert canary not in serialized
    assert "DATABASE_URL" not in serialized


def test_temporary_mount_evidence_is_bounded_and_reports_capacity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeMountInfo:
        def __enter__(self) -> "FakeMountInfo":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, maximum: int) -> str:
            assert maximum == 65_537
            return "36 25 0:32 / /tmp rw,nosuid,nodev,noexec - tmpfs tmpfs rw,size=131072k\n"

    original_open = Path.open

    def fake_open(path: Path, *args: object, **kwargs: object) -> object:
        if path == Path("/proc/self/mountinfo"):
            return FakeMountInfo()
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fake_open)
    monkeypatch.setattr(
        worker.os,
        "statvfs",
        lambda _path: SimpleNamespace(f_frsize=4096, f_blocks=32_768),
        raising=False,
    )
    filesystem_type, options, capacity = worker._temporary_mount_evidence(Path("/tmp"))

    assert filesystem_type == "tmpfs"
    assert options == ["nodev", "noexec", "nosuid", "rw", "size=131072k"]
    assert capacity == 134_217_728
