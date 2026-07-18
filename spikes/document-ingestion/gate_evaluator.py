from __future__ import annotations

from dataclasses import dataclass
import math
import re
from statistics import median
from typing import Any, Mapping, Sequence


REQUIRED_SANDBOX_CHECKS = (
    "non_root",
    "read_only_rootfs",
    "cap_eff_zero",
    "no_new_privileges",
    "network_none",
    "network_control_cleaned",
    "input_read_only",
    "tmpfs_bounded",
    "cpu_limit_applied",
    "memory_limit_applied",
    "pid_limit_applied",
    "wall_limit_applied",
    "output_limit_applied",
    "docker_socket_absent",
    "secrets_absent",
    "log_driver_none",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class GateDecision:
    status: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def _mapping(value: object, label: str, blockers: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        blockers.append(f"{label} is missing or invalid")
        return {}
    return value


def _sequence(value: object) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _stable_repeats(values: object, *, minimum: int = 3) -> bool:
    sequence = _sequence(values)
    return (
        len(sequence) >= minimum
        and all(isinstance(value, str) and _SHA256.fullmatch(value) for value in sequence)
        and len(set(sequence)) == 1
    )


def _source_snapshots_match(values: object, expected_sha256: object) -> bool:
    sequence = _sequence(values)
    return (
        isinstance(expected_sha256, str)
        and _SHA256.fullmatch(expected_sha256) is not None
        and len(sequence) >= 3
        and all(value == expected_sha256 for value in sequence)
    )


def _finite_number(value: object, *, minimum: float = 0) -> bool:
    parsed = _finite_value(value)
    return parsed is not None and parsed >= minimum


def _finite_value(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _positive_integer(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def evaluate_g0(
    manifest: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    wall_limit_seconds: float,
) -> GateDecision:
    blockers: list[str] = []
    warnings: list[str] = []
    if manifest.get("schema_version") != 1:
        blockers.append("fixture manifest schema_version is not 1")
    if evidence.get("schema_version") != 1:
        blockers.append("evidence schema_version is not 1")
    if not _finite_number(wall_limit_seconds, minimum=0) or wall_limit_seconds <= 0:
        blockers.append("wall limit must be positive")

    test_counts = _mapping(evidence.get("test_counts"), "test_counts", blockers)
    collected = test_counts.get("collected")
    passed = test_counts.get("passed")
    if (
        isinstance(collected, bool)
        or not isinstance(collected, int)
        or collected <= 0
        or passed != collected
    ):
        blockers.append("test_counts must prove collected == passed > 0")
    for outcome in ("skipped", "xfailed", "failed"):
        if test_counts.get(outcome) != 0:
            blockers.append(f"test_counts.{outcome} must be zero")

    golden_evidence = _mapping(evidence.get("golden"), "golden", blockers)
    malicious_evidence = _mapping(evidence.get("malicious"), "malicious", blockers)
    browser_proof = _mapping(evidence.get("browser_proof"), "browser_proof", blockers)
    if browser_proof.get("fresh_attested") is not True:
        blockers.append("browser proof is not a fresh attested run")
    recovery_sha256: str | None = None
    for fixture in _sequence(manifest.get("fixtures")):
        if isinstance(fixture, Mapping) and fixture.get("classification") == "golden":
            candidate = fixture.get("sha256")
            if isinstance(candidate, str) and _SHA256.fullmatch(candidate) is not None:
                recovery_sha256 = candidate
            break
    total_duration_ms = 0.0

    for raw_fixture in _sequence(manifest.get("fixtures")):
        fixture = _mapping(raw_fixture, "manifest fixture", blockers)
        path = fixture.get("path")
        classification = fixture.get("classification")
        expected = _mapping(fixture.get("expected"), f"{path}.expected", blockers)
        if not isinstance(path, str) or not path:
            blockers.append("manifest fixture path is invalid")
            continue

        if classification == "golden":
            actual = _mapping(golden_evidence.get(path), f"golden.{path}", blockers)
            if actual.get("status") != "passed":
                blockers.append(f"{path}: extraction did not pass")
            cold = actual.get("cold_anchor_set_hashes")
            warm = actual.get("warm_anchor_set_hashes")
            if not _stable_repeats(cold):
                blockers.append(f"{path}: cold anchor hash drift or insufficient repeats")
            if not _stable_repeats(warm):
                blockers.append(f"{path}: warm anchor hash drift or insufficient repeats")
            if _stable_repeats(cold) and _stable_repeats(warm):
                if _sequence(cold)[0] != _sequence(warm)[0]:
                    blockers.append(f"{path}: cold and warm anchor hashes differ")
            if actual.get("warm_execution_mode") != "isolated_short_lived":
                blockers.append(f"{path}: warm repetitions did not use isolated short-lived execution")
            if actual.get("source_snapshot_matches") is not True:
                blockers.append(f"{path}: source snapshot identity is not proven")
            if not _source_snapshots_match(actual.get("cold_source_sha256s"), fixture.get("sha256")):
                blockers.append(f"{path}: cold source snapshots do not match manifest")
            if not _source_snapshots_match(actual.get("warm_source_sha256s"), fixture.get("sha256")):
                blockers.append(f"{path}: warm source snapshots do not match manifest")
            if actual.get("structure_verified") is not True:
                blockers.append(f"{path}: manifest extraction structure is not proven")

            minimum_ocr = expected.get("min_ocr_accuracy")
            if minimum_ocr is not None:
                actual_ocr = actual.get("ocr_accuracy")
                actual_ocr_value = _finite_value(actual_ocr)
                minimum_ocr_value = _finite_value(minimum_ocr)
                if (
                    actual_ocr_value is None
                    or actual_ocr_value > 1
                    or minimum_ocr_value is None
                    or minimum_ocr_value > 1
                    or actual_ocr_value < minimum_ocr_value
                ):
                    blockers.append(f"{path}: OCR accuracy is below {minimum_ocr}")
            required_warning = expected.get("required_warning")
            if required_warning is not None and required_warning not in _sequence(
                actual.get("warnings")
            ):
                blockers.append(f"{path}: required warning {required_warning} is absent")

            browser = _mapping(actual.get("browser"), f"{path}.browser", blockers)
            if browser.get("selected_count") != 1:
                blockers.append(f"{path}: browser must highlight exactly one target")
            if browser.get("deep_link_match") is not True:
                blockers.append(f"{path}: browser deep-link target differs")
            if browser.get("geometry_match") is not True:
                blockers.append(f"{path}: browser locator geometry/path differs")
            if browser.get("external_requests") != 0:
                blockers.append(f"{path}: browser made external requests")
            cold_values = _sequence(cold)
            if cold_values and browser.get("target_anchor_set_hash") != cold_values[0]:
                blockers.append(f"{path}: browser proof used a different extraction")

            durations = _sequence(actual.get("duration_ms"))
            if not durations or any(
                not _finite_number(duration)
                for duration in durations
            ):
                blockers.append(f"{path}: duration evidence is missing or invalid")
            else:
                total_duration_ms += median(float(duration) for duration in durations)
        elif classification == "malicious":
            actual = _mapping(malicious_evidence.get(path), f"malicious.{path}", blockers)
            if actual.get("error_code") != expected.get("error_code"):
                blockers.append(f"{path}: wrong typed rejection")
            duration_ms = actual.get("duration_ms")
            duration_value = _finite_value(duration_ms)
            if (
                duration_value is None
                or duration_value > wall_limit_seconds * 1000
            ):
                blockers.append(f"{path}: rejection exceeded the wall limit")
            if actual.get("recovery_passed") is not True:
                blockers.append(f"{path}: clean recovery did not pass")
            if actual.get("orphan_processes") != 0:
                blockers.append(f"{path}: orphan parser process/container remains")
            if actual.get("source_sha256") != fixture.get("sha256"):
                blockers.append(f"{path}: malicious source snapshot does not match manifest")
            if recovery_sha256 is None or actual.get("recovery_source_sha256") != recovery_sha256:
                blockers.append(f"{path}: recovery source snapshot does not match manifest")
        else:
            blockers.append(f"{path}: unknown fixture classification")

    sandbox = _mapping(evidence.get("sandbox"), "sandbox", blockers)
    for check in REQUIRED_SANDBOX_CHECKS:
        if sandbox.get(check) is not True:
            blockers.append(f"sandbox.{check} is not proven")

    positive = _mapping(evidence.get("positive_control"), "positive_control", blockers)
    if positive.get("network_enabled_control_reachable") is not True:
        blockers.append("controlled network positive control failed")
    if positive.get("orchestrator_secret_present") is not True:
        blockers.append("orchestrator secret positive control failed")

    oversized = _mapping(evidence.get("oversized_input"), "oversized_input", blockers)
    if oversized.get("error_code") != "INPUT_TOO_LARGE":
        blockers.append("oversized input did not return INPUT_TOO_LARGE")
    if not _finite_number(oversized.get("duration_ms")):
        blockers.append("oversized input duration is missing or invalid")
    if not isinstance(oversized.get("source_sha256"), str) or _SHA256.fullmatch(
        oversized["source_sha256"]
    ) is None:
        blockers.append("oversized input source snapshot is missing or invalid")

    integrity = _mapping(evidence.get("artifact_integrity"), "artifact_integrity", blockers)
    for field in (
        "manifest_unchanged",
        "policy_unchanged",
        "browser_provenance_unchanged",
        "image_unchanged",
    ):
        if integrity.get(field) is not True:
            blockers.append(f"artifact_integrity.{field} is not proven")

    runtime = _mapping(evidence.get("runtime"), "runtime", blockers)
    if not isinstance(runtime.get("image_id"), str) or not _IMAGE_ID.fullmatch(
        runtime["image_id"]
    ):
        blockers.append("runtime.image_id is not a content-addressed image ID")
    if not _finite_number(runtime.get("cold_start_ms")) or runtime.get(
        "cold_start_ms"
    ) == 0:
        blockers.append("runtime.cold_start_ms is missing or invalid")
    for field in ("image_size_bytes", "peak_memory_bytes", "peak_pids"):
        if not _positive_integer(runtime.get(field)):
            blockers.append(f"runtime.{field} is missing or invalid")
    hardware = _mapping(runtime.get("hardware"), "runtime.hardware", blockers)
    for field in ("os", "architecture", "cpu_model", "docker_server_version"):
        if not isinstance(hardware.get(field), str) or not hardware[field]:
            blockers.append(f"runtime.hardware.{field} is missing")
    for field in ("logical_cpus", "memory_bytes"):
        if not _positive_integer(hardware.get(field)):
            blockers.append(f"runtime.hardware.{field} is missing or invalid")

    licenses = _sequence(evidence.get("licenses"))
    if not licenses:
        blockers.append("license inventory is empty")
    for index, raw_license in enumerate(licenses):
        item = _mapping(raw_license, f"licenses[{index}]", blockers)
        for field in ("component", "version", "spdx", "source_url"):
            if not isinstance(item.get(field), str) or not item[field]:
                blockers.append(f"licenses[{index}].{field} is missing")
        if item.get("redistributable") is not True:
            blockers.append(f"licenses[{index}] is not redistributable")

    leaks = _mapping(evidence.get("leak_scan"), "leak_scan", blockers)
    if leaks.get("secret_matches") != 0:
        blockers.append("secret leakage was detected")
    if leaks.get("raw_content_matches") != 0:
        blockers.append("raw-content leakage was detected")

    if total_duration_ms > 120_000:
        warnings.append("demo processing time exceeds the 120 second warning threshold")

    unique_blockers = tuple(dict.fromkeys(blockers))
    return GateDecision(
        status="GO" if not unique_blockers else "NO_GO",
        blockers=unique_blockers,
        warnings=tuple(warnings),
    )
