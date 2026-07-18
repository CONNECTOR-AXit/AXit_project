from __future__ import annotations

from copy import deepcopy

from gate_evaluator import evaluate_g0


def _manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "fixtures": [
            {
                "path": "images/korean-clean.png",
                "classification": "golden",
                "sha256": "e" * 64,
                "expected": {
                    "anchor_kind": "image_bbox",
                    "min_ocr_accuracy": 0.9,
                },
            },
            {
                "path": "malicious/xxe.hwpx",
                "classification": "malicious",
                "sha256": "f" * 64,
                "expected": {"error_code": "XML_DTD_FORBIDDEN"},
            },
        ],
    }


def _passing_evidence() -> dict[str, object]:
    stable_hash = "a" * 64
    return {
        "schema_version": 1,
        "test_counts": {
            "collected": 42,
            "passed": 42,
            "skipped": 0,
            "xfailed": 0,
            "failed": 0,
        },
        "browser_proof": {"fresh_attested": True, "error": None},
        "golden": {
            "images/korean-clean.png": {
                "status": "passed",
                "cold_anchor_set_hashes": [stable_hash, stable_hash, stable_hash],
                "warm_anchor_set_hashes": [stable_hash, stable_hash, stable_hash],
                "cold_source_sha256s": ["e" * 64] * 3,
                "warm_source_sha256s": ["e" * 64] * 3,
                "source_snapshot_matches": True,
                "structure_verified": True,
                "warm_execution_mode": "isolated_short_lived",
                "ocr_accuracy": 0.97,
                "duration_ms": [100, 80, 75, 73, 72, 70],
                "browser": {
                    "selected_count": 1,
                    "target_anchor_set_hash": stable_hash,
                    "deep_link_match": True,
                    "geometry_match": True,
                    "external_requests": 0,
                },
            }
        },
        "malicious": {
            "malicious/xxe.hwpx": {
                "error_code": "XML_DTD_FORBIDDEN",
                "duration_ms": 50,
                "source_sha256": "f" * 64,
                "recovery_source_sha256": "e" * 64,
                "recovery_passed": True,
                "orphan_processes": 0,
            }
        },
        "sandbox": {
            "non_root": True,
            "read_only_rootfs": True,
            "cap_eff_zero": True,
            "no_new_privileges": True,
            "network_none": True,
            "network_control_cleaned": True,
            "input_read_only": True,
            "tmpfs_bounded": True,
            "cpu_limit_applied": True,
            "memory_limit_applied": True,
            "pid_limit_applied": True,
            "wall_limit_applied": True,
            "output_limit_applied": True,
            "docker_socket_absent": True,
            "secrets_absent": True,
            "log_driver_none": True,
        },
        "positive_control": {
            "network_enabled_control_reachable": True,
            "orchestrator_secret_present": True,
        },
        "oversized_input": {
            "error_code": "INPUT_TOO_LARGE",
            "duration_ms": 1,
            "source_sha256": "d" * 64,
        },
        "artifact_integrity": {
            "manifest_unchanged": True,
            "policy_unchanged": True,
            "browser_provenance_unchanged": True,
            "image_unchanged": True,
        },
        "runtime": {
            "image_id": "sha256:" + "d" * 64,
            "image_size_bytes": 500_000_000,
            "cold_start_ms": 850,
            "peak_memory_bytes": 123_000_000,
            "peak_pids": 18,
            "hardware": {
                "os": "linux",
                "architecture": "x86_64",
                "cpu_model": "fixture CPU",
                "docker_server_version": "29.2.1",
                "logical_cpus": 8,
                "memory_bytes": 16_000_000_000,
            },
        },
        "licenses": [
            {
                "component": "parser",
                "version": "1.2.3",
                "spdx": "Apache-2.0",
                "source_url": "https://example.invalid/parser",
                "redistributable": True,
            },
            {
                "component": "ocr-model",
                "version": "sha256:" + "b" * 64,
                "spdx": "Apache-2.0",
                "source_url": "https://example.invalid/model",
                "redistributable": True,
            },
        ],
        "leak_scan": {"secret_matches": 0, "raw_content_matches": 0},
    }


def test_all_blocking_rows_produce_go() -> None:
    decision = evaluate_g0(_manifest(), _passing_evidence(), wall_limit_seconds=20)

    assert decision.status == "GO"
    assert decision.blockers == ()


def test_120_second_demo_metric_is_a_warning_not_a_functional_failure() -> None:
    evidence = _passing_evidence()
    evidence["golden"]["images/korean-clean.png"]["duration_ms"] = [121_000] * 6  # type: ignore[index]

    decision = evaluate_g0(_manifest(), evidence, wall_limit_seconds=130)

    assert decision.status == "GO"
    assert decision.warnings == ("demo processing time exceeds the 120 second warning threshold",)


def test_every_security_and_quality_regression_is_a_no_go_blocker() -> None:
    mutations = [
        ("ocr", lambda value: value["golden"]["images/korean-clean.png"].update(ocr_accuracy=0.89)),
        (
            "cold hash drift",
            lambda value: value["golden"]["images/korean-clean.png"].update(
                cold_anchor_set_hashes=["a" * 64, "c" * 64, "a" * 64]
            ),
        ),
        (
            "non-hash repeat token",
            lambda value: value["golden"]["images/korean-clean.png"].update(
                cold_anchor_set_hashes=["stable", "stable", "stable"]
            ),
        ),
        (
            "browser mismatch",
            lambda value: value["golden"]["images/korean-clean.png"]["browser"].update(
                selected_count=2
            ),
        ),
        (
            "wrong attack code",
            lambda value: value["malicious"]["malicious/xxe.hwpx"].update(
                error_code="CORRUPT_DOCUMENT"
            ),
        ),
        ("escape", lambda value: value["sandbox"].update(network_none=False)),
        (
            "missing positive control",
            lambda value: value["positive_control"].update(
                network_enabled_control_reachable=False
            ),
        ),
        ("unknown license", lambda value: value.update(licenses=[])),
        (
            "secret leak",
            lambda value: value["leak_scan"].update(secret_matches=1),
        ),
        (
            "skipped test",
            lambda value: value["test_counts"].update(skipped=1),
        ),
        (
            "zero collected tests",
            lambda value: value["test_counts"].update(collected=0, passed=0),
        ),
        (
            "boolean OCR metric",
            lambda value: value["golden"]["images/korean-clean.png"].update(
                ocr_accuracy=True
            ),
        ),
        (
            "boolean duration metric",
            lambda value: value["malicious"]["malicious/xxe.hwpx"].update(
                duration_ms=True
            ),
        ),
        (
            "missing runtime resource observation",
            lambda value: value["runtime"].update(peak_memory_bytes=None),
        ),
    ]

    for label, mutate in mutations:
        evidence = deepcopy(_passing_evidence())
        mutate(evidence)
        decision = evaluate_g0(_manifest(), evidence, wall_limit_seconds=20)
        assert decision.status == "NO_GO", label
        assert decision.blockers, label
