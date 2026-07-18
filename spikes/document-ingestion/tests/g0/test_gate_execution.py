from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from gate import GateConfig, GateExecutionError, _load_browser_proofs, run_gate
from sandbox_runner import SandboxExecution, SandboxPolicy, SandboxRequest


SPIKE_ROOT = Path(__file__).resolve().parents[2]
STABLE_HASH = "a" * 64


def _source_sha(request: SandboxRequest) -> str:
    return hashlib.sha256(request.input_bytes).hexdigest()


def _success(
    request: SandboxRequest,
    *,
    anchor_hash: str = STABLE_HASH,
    duration_ms: int = 7,
    source_sha256: str | None = None,
) -> SandboxExecution:
    return SandboxExecution(
        ok=True,
        error_code=None,
        payload={
            "schema_version": 1,
            "ok": True,
            "result": {
                "anchor_set_hash": anchor_hash,
                "media_type": "image/png",
                "normalization_profile": "nfc-lf-v1",
                "blocks": [
                    {
                        "text": "회의 안건",
                        "block_type": "image_ocr",
                        "anchor": {"kind": "image_bbox", "locator": {}},
                    }
                ],
                "warnings": [],
            },
        },
        exit_code=0,
        duration_ms=duration_ms,
        stdout_bytes=256,
        stderr_bytes=0,
        killed=False,
        source_sha256=source_sha256 or _source_sha(request),
        peak_memory_bytes=32 * 1024 * 1024,
        peak_pids=3,
    )


class _FakeExecutor:
    def __init__(
        self,
        *,
        secret_present: bool = False,
        warm_hashes: list[str] | None = None,
        source_mismatch: bool = False,
    ) -> None:
        self.secret_present = secret_present
        self.warm_hashes = iter(warm_hashes or [STABLE_HASH] * 3)
        self.source_mismatch = source_mismatch
        self.requests: list[SandboxRequest] = []

    def __call__(
        self, request: SandboxRequest, policy: SandboxPolicy
    ) -> SandboxExecution:
        self.requests.append(request)
        source_sha256 = "f" * 64 if self.source_mismatch else _source_sha(request)
        if len(request.input_bytes) > policy.max_input_bytes:
            return SandboxExecution(
                False,
                "INPUT_TOO_LARGE",
                None,
                None,
                1,
                0,
                0,
                False,
                source_sha256=_source_sha(request),
            )
        if request.probe == "network":
            return self._probe(
                request,
                "network",
                {
                    "outbound_network_reachable": False,
                    "target_host": request.network_probe_host,
                    "target_port": request.network_probe_port,
                },
                source_sha256,
            )
        if request.probe == "secret":
            return self._probe(
                request,
                "secret",
                {
                    "sensitive_environment_present": self.secret_present,
                    "secret_mount_present": False,
                },
                source_sha256,
            )
        if request.probe == "filesystem":
            return self._probe(
                request,
                "filesystem",
                {
                    "capabilities_zero": True,
                    "cgroup_cpu_max": "100000 100000",
                    "cgroup_memory_max": str(policy.memory_bytes),
                    "cgroup_pids_max": str(policy.pids),
                    "docker_socket_present": False,
                    "effective_uid": policy.uid,
                    "input_writable": False,
                    "no_new_privileges": True,
                    "root_filesystem_writable": False,
                    "temporary_directory_writable": True,
                    "temporary_filesystem_type": "tmpfs",
                    "temporary_mount_options": ["nodev", "noexec", "nosuid", "rw"],
                    "temporary_capacity_bytes": policy.tmpfs_bytes,
                },
                source_sha256,
            )
        if request.probe == "timeout":
            return SandboxExecution(
                False,
                "PARSER_TIMEOUT",
                None,
                -9,
                100,
                0,
                0,
                True,
                source_sha256=source_sha256,
            )
        if request.probe == "output":
            return SandboxExecution(
                False,
                "PARSER_OUTPUT_LIMIT",
                None,
                -9,
                10,
                policy.max_stdout_bytes,
                0,
                True,
                source_sha256=source_sha256,
            )
        if request.original_filename == "corrupt.pdf":
            return SandboxExecution(
                False,
                "CORRUPT_DOCUMENT",
                {
                    "schema_version": 1,
                    "ok": False,
                    "error": {
                        "code": "CORRUPT_DOCUMENT",
                        "message": "document is corrupt",
                        "retryable": False,
                    },
                },
                2,
                4,
                128,
                0,
                False,
                source_sha256=source_sha256,
            )
        anchor_hash = (
            next(self.warm_hashes)
            if request.container_name is not None and "-w0-" in request.container_name
            else STABLE_HASH
        )
        return _success(request, anchor_hash=anchor_hash, source_sha256=source_sha256)

    @staticmethod
    def _probe(
        request: SandboxRequest,
        kind: str,
        fields: Mapping[str, object],
        source_sha256: str,
    ) -> SandboxExecution:
        return SandboxExecution(
            True,
            None,
            {"schema_version": 1, "ok": True, "probe": {"kind": kind, **fields}},
            0,
            3,
            128,
            0,
            False,
            source_sha256=source_sha256,
        )


class _FakeNetworkControl:
    host = "g0-probe"
    port = 18_080
    reachable = True

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeDocker:
    def __init__(self) -> None:
        self.network_controls: list[_FakeNetworkControl] = []

    def image_runtime(self, image: str) -> dict[str, Any]:
        return {
            "image_id": "sha256:" + "b" * 64,
            "image_size_bytes": 100_000_000,
            "repo_digests": ["fixture@sha256:" + "c" * 64],
            "hardware": {
                "os": "test-linux",
                "architecture": "amd64",
                "cpu_model": "test-cpu",
                "docker_server_version": "29.2.1",
                "logical_cpus": 4,
                "memory_bytes": 8_000_000_000,
            },
        }

    def open_network_control(self, image: str, *, prefix: str) -> _FakeNetworkControl:
        assert image.startswith("sha256:")
        assert prefix.startswith("axit-g0-gate-")
        control = _FakeNetworkControl()
        self.network_controls.append(control)
        return control

    def orphan_names(self, prefix: str) -> tuple[str, ...]:
        return ()

    def orphan_network_names(self, prefix: str) -> tuple[str, ...]:
        return ()

    def orchestrator_secret_present(self, compose_path: Path) -> bool:
        return True


def _write_browser_proof(path: Path, attestation: Mapping[str, str]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "attestation": dict(attestation),
                "fixtures": {
                    "images/clean.png": {
                        "selected_count": 1,
                        "target_anchor_set_hash": STABLE_HASH,
                        "deep_link_match": True,
                        "geometry_match": True,
                        "external_requests": 0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _write_contract(tmp_path: Path) -> GateConfig:
    fixture_root = tmp_path / "fixtures"
    (fixture_root / "images").mkdir(parents=True)
    (fixture_root / "malicious").mkdir()
    clean = fixture_root / "images" / "clean.png"
    corrupt = fixture_root / "malicious" / "corrupt.pdf"
    clean.write_bytes(b"fixture-png")
    corrupt.write_bytes(b"fixture-corrupt-pdf")

    def entry(
        path: Path, relative: str, classification: str, expected: object
    ) -> dict[str, object]:
        data = path.read_bytes()
        return {
            "path": relative,
            "classification": classification,
            "expected": expected,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "media_type": "image/png" if path.suffix == ".png" else "application/pdf",
        }

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fixtures": [
                    entry(
                        clean,
                        "images/clean.png",
                        "golden",
                        {
                            "anchor_kind": "image_bbox",
                            "normalization_profile": "nfc-lf-v1",
                            "text_nfc": "회의 안건",
                            "min_ocr_accuracy": 0.9,
                        },
                    ),
                    entry(
                        corrupt,
                        "malicious/corrupt.pdf",
                        "malicious",
                        {"error_code": "CORRUPT_DOCUMENT"},
                    ),
                ],
            }
        ),
        encoding="utf-8",
    )
    licenses = tmp_path / "licenses.json"
    licenses.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "components": [
                    {
                        "name": "parser",
                        "version": "1.0.0",
                        "spdx": "Apache-2.0",
                        "source_url": "https://example.invalid/parser",
                        "redistributable": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return GateConfig(
        image="fixture:local",
        fixture_root=fixture_root,
        manifest_path=manifest,
        output_path=tmp_path / "evidence" / "g0.json",
        policy_path=SPIKE_ROOT / "policy.v1.json",
        licenses_path=licenses,
        compose_path=tmp_path / "compose.yml",
        browser_evidence_path=tmp_path / "browser.json",
    )


def test_gate_collects_immutable_short_lived_execution_shapes(tmp_path: Path) -> None:
    config = _write_contract(tmp_path)
    executor = _FakeExecutor()
    docker = _FakeDocker()

    run = run_gate(
        config,
        executor=executor,
        docker=docker,
        browser_runner=_write_browser_proof,
    )

    assert run.decision.status == "GO"
    assert run.evidence["test_counts"] == {
        "collected": run.evidence["test_counts"]["collected"],  # type: ignore[index]
        "passed": run.evidence["test_counts"]["collected"],  # type: ignore[index]
        "skipped": 0,
        "xfailed": 0,
        "failed": 0,
    }
    persisted = json.loads(config.output_path.read_text(encoding="utf-8"))
    golden = persisted["golden"]["images/clean.png"]
    assert persisted["decision"]["status"] == "GO"
    assert golden["warm_execution_mode"] == "isolated_short_lived"
    assert golden["cold_anchor_set_hashes"] == [STABLE_HASH] * 3
    assert golden["cold_source_sha256s"] == [
        hashlib.sha256(b"fixture-png").hexdigest()
    ] * 3
    names = [request.container_name for request in executor.requests if request.container_name]
    assert len(names) == len(set(names))
    assert all(isinstance(request.input_bytes, bytes) for request in executor.requests)
    assert run.evidence["oversized_input"]["error_code"] == "INPUT_TOO_LARGE"  # type: ignore[index]
    assert all(control.closed for control in docker.network_controls)


def test_missing_actual_browser_proof_is_fail_closed_and_still_atomic(
    tmp_path: Path,
) -> None:
    config = _write_contract(tmp_path)

    run = run_gate(
        config,
        executor=_FakeExecutor(),
        docker=_FakeDocker(),
        browser_runner=lambda _path, _attestation: None,
    )

    assert run.decision.status == "NO_GO"
    assert run.evidence["test_counts"]["failed"] > 0  # type: ignore[index]
    assert any(
        failure["code"] == "BROWSER_PROOF_MISSING"
        for failure in run.evidence["failures"]  # type: ignore[union-attr]
    )
    assert (
        json.loads(config.output_path.read_text(encoding="utf-8"))["decision"]["status"]
        == "NO_GO"
    )


def test_probe_escape_and_warm_hash_drift_are_both_no_go(tmp_path: Path) -> None:
    config = _write_contract(tmp_path)

    run = run_gate(
        config,
        executor=_FakeExecutor(
            secret_present=True,
            warm_hashes=[STABLE_HASH, "d" * 64, STABLE_HASH],
        ),
        docker=_FakeDocker(),
        browser_runner=_write_browser_proof,
    )

    assert run.decision.status == "NO_GO"
    assert run.evidence["sandbox"]["secrets_absent"] is False  # type: ignore[index]
    assert any(
        failure["check"] == "probe:secret:boundary"
        for failure in run.evidence["failures"]  # type: ignore[union-attr]
    )
    assert run.evidence["golden"]["images/clean.png"]["status"] == "failed"  # type: ignore[index]


def test_source_snapshot_mismatch_is_no_go(tmp_path: Path) -> None:
    config = _write_contract(tmp_path)

    run = run_gate(
        config,
        executor=_FakeExecutor(source_mismatch=True),
        docker=_FakeDocker(),
        browser_runner=_write_browser_proof,
    )

    assert run.decision.status == "NO_GO"
    assert run.evidence["golden"]["images/clean.png"]["source_snapshot_matches"] is False  # type: ignore[index]


def test_browser_extra_or_duplicate_contract_data_is_rejected(tmp_path: Path) -> None:
    config = _write_contract(tmp_path)

    def extra_runner(path: Path, attestation: Mapping[str, str]) -> None:
        _write_browser_proof(path, attestation)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["fixtures"]["unexpected.png"] = raw["fixtures"]["images/clean.png"]
        path.write_text(json.dumps(raw), encoding="utf-8")

    run = run_gate(
        config,
        executor=_FakeExecutor(),
        docker=_FakeDocker(),
        browser_runner=extra_runner,
    )
    assert run.decision.status == "NO_GO"

    duplicate = tmp_path / "duplicate-browser.json"
    duplicate.write_text('{"schema_version":2,"schema_version":2}', encoding="utf-8")
    with pytest.raises(GateExecutionError):
        _load_browser_proofs(
            duplicate,
            golden_paths=[],
            expected_attestation={
                "nonce": "x",
                "manifest_sha256": "a" * 64,
                "policy_sha256": "b" * 64,
                "extraction_image_id": "sha256:" + "c" * 64,
                "provenance_sha256": "d" * 64,
            },
        )
