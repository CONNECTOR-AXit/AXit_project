"""Execute the blocking Phase-1 G0 ingestion gate and persist reviewable evidence.

The harness deliberately treats missing browser/runtime/security proof as a failure.
It never turns a synthetic viewer fixture or a parser exception into a GO result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, cast

_SOURCE_ROOT = Path(__file__).resolve().parent / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from gate_evaluator import GateDecision, evaluate_g0  # noqa: E402
from quality import ocr_character_accuracy  # noqa: E402
from sandbox_runner import (  # noqa: E402
    SandboxExecution,
    SandboxPolicy,
    SandboxRequest,
    build_docker_command,
    execute_sandbox,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_MEDIA_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".hwp": "application/x-hwp",
    ".hwpx": "application/x-hwpx",
}
_PROBE_NAMES = ("network", "secret", "filesystem", "timeout", "output")


class GateExecutionError(RuntimeError):
    """A structural/configuration error that prevents a trustworthy gate run."""


@dataclass(frozen=True, slots=True)
class GateConfig:
    image: str
    fixture_root: Path
    manifest_path: Path
    output_path: Path
    policy_path: Path
    licenses_path: Path
    compose_path: Path
    browser_evidence_path: Path | None = None
    viewer_root: Path | None = None
    browser_binary: str = "npm"
    cold_repeats: int = 3
    warm_repeats: int = 3
    docker_binary: str = "docker"


@dataclass(frozen=True, slots=True)
class GateRun:
    decision: GateDecision
    evidence: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _Fixture:
    relative_path: str
    classification: str
    expected: Mapping[str, Any]
    sha256: str
    media_type: str
    source_bytes: bytes


@dataclass(frozen=True, slots=True)
class _Observation:
    anchor_set_hash: str
    text: str
    warnings: tuple[str, ...]
    duration_ms: int


class NetworkControl(Protocol):
    host: str
    port: int
    reachable: bool

    def close(self) -> None: ...


class DockerLayer(Protocol):
    def image_runtime(self, image: str) -> Mapping[str, Any]: ...

    def open_network_control(self, image: str, *, prefix: str) -> NetworkControl: ...

    def orphan_names(self, prefix: str) -> tuple[str, ...]: ...

    def orphan_network_names(self, prefix: str) -> tuple[str, ...]: ...

    def orchestrator_secret_present(self, compose_path: Path) -> bool: ...


SandboxExecutor = Callable[[SandboxRequest, SandboxPolicy], SandboxExecution]
BrowserRunner = Callable[[Path, Mapping[str, str]], None]


class _Ledger:
    def __init__(self) -> None:
        self._checks: dict[str, bool] = {}
        self.failures: list[dict[str, str]] = []

    def record(self, name: str, passed: bool, code: str = "CHECK_FAILED") -> None:
        if name in self._checks:
            raise GateExecutionError(f"duplicate gate check: {name}")
        self._checks[name] = passed
        if not passed:
            self.failures.append({"check": name, "code": code})

    def counts(self) -> dict[str, int]:
        passed = sum(self._checks.values())
        collected = len(self._checks)
        return {
            "collected": collected,
            "passed": passed,
            "skipped": 0,
            "xfailed": 0,
            "failed": collected - passed,
        }


def _json_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        raw = path.read_bytes()
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON number")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        raise GateExecutionError(f"{label} is unavailable or invalid") from error
    if not isinstance(parsed, dict):
        raise GateExecutionError(f"{label} must be a JSON object")
    return cast(dict[str, Any], parsed), raw


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_matches_sha256(path: Path, expected: str) -> bool:
    try:
        return _sha256_path(path) == expected
    except OSError:
        return False


def _load_manifest(
    config: GateConfig,
) -> tuple[dict[str, Any], str, tuple[_Fixture, ...]]:
    manifest, manifest_bytes = _json_object(config.manifest_path, "fixture manifest")
    if manifest.get("schema_version") != 1:
        raise GateExecutionError("fixture manifest schema_version must be 1")
    raw_fixtures = manifest.get("fixtures")
    if not isinstance(raw_fixtures, list) or not raw_fixtures:
        raise GateExecutionError("fixture manifest must contain fixtures")
    root = config.fixture_root.resolve()
    fixtures: list[_Fixture] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_fixtures):
        if not isinstance(raw, dict):
            raise GateExecutionError(f"manifest fixture {index} must be an object")
        relative = raw.get("path")
        classification = raw.get("classification")
        expected = raw.get("expected")
        expected_hash = raw.get("sha256")
        expected_size = raw.get("size_bytes")
        if not isinstance(relative, str) or not relative:
            raise GateExecutionError(f"manifest fixture {index} path is invalid")
        posix = PurePosixPath(relative)
        if (
            posix.is_absolute()
            or ".." in posix.parts
            or "\\" in relative
            or posix.as_posix() != relative
            or relative in seen
        ):
            raise GateExecutionError("fixture paths must be unique safe POSIX paths")
        if classification not in {"golden", "malicious"}:
            raise GateExecutionError(f"{relative}: classification is invalid")
        if not isinstance(expected, dict):
            raise GateExecutionError(f"{relative}: expected contract is invalid")
        if (
            not isinstance(expected_hash, str)
            or _SHA256.fullmatch(expected_hash) is None
        ):
            raise GateExecutionError(f"{relative}: sha256 is invalid")
        if (
            isinstance(expected_size, bool)
            or not isinstance(expected_size, int)
            or expected_size <= 0
        ):
            raise GateExecutionError(f"{relative}: size_bytes is invalid")
        path = (root / Path(*posix.parts)).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise GateExecutionError(
                f"{relative}: path escapes fixture root"
            ) from error
        if path.is_symlink() or not path.is_file():
            raise GateExecutionError(f"{relative}: fixture is not a regular file")
        try:
            source_bytes = path.read_bytes()
        except OSError as error:
            raise GateExecutionError(f"{relative}: fixture is unavailable") from error
        if len(source_bytes) != expected_size or hashlib.sha256(source_bytes).hexdigest() != expected_hash:
            raise GateExecutionError(f"{relative}: fixture bytes differ from manifest")
        media_type = raw.get("media_type")
        if path.suffix.lower() not in _MEDIA_BY_SUFFIX or media_type != _MEDIA_BY_SUFFIX[path.suffix.lower()]:
            raise GateExecutionError(f"{relative}: unsupported fixture suffix")
        seen.add(relative)
        fixtures.append(
            _Fixture(
                relative,
                classification,
                cast(Mapping[str, Any], expected),
                expected_hash,
                cast(str, media_type),
                source_bytes,
            )
        )
    if not any(item.classification == "golden" for item in fixtures):
        raise GateExecutionError("at least one golden recovery fixture is required")
    return manifest, hashlib.sha256(manifest_bytes).hexdigest(), tuple(fixtures)


def _load_licenses(path: Path) -> list[dict[str, object]]:
    raw, _ = _json_object(path, "license inventory")
    if raw.get("schema_version") != 1 or not isinstance(raw.get("components"), list):
        raise GateExecutionError("license inventory contract is invalid")
    result: list[dict[str, object]] = []
    for component in raw["components"]:
        if not isinstance(component, dict):
            raise GateExecutionError("license component must be an object")
        result.append(
            {
                "component": component.get("name"),
                "version": component.get("version"),
                "spdx": component.get("spdx"),
                "source_url": component.get("source_url"),
                "redistributable": component.get("redistributable"),
            }
        )
    return result


def _browser_attestation(
    config: GateConfig,
    *,
    manifest_sha256: str,
    policy_sha256: str,
    image_id: str,
) -> dict[str, str]:
    """Construct the nonce-bound browser proof contract for this exact gate run."""

    viewer_root = (config.viewer_root or Path(__file__).resolve().parent / "viewer").resolve()
    provenance_path = viewer_root / "fixtures" / "provenance.v1.json"
    if not provenance_path.is_file():
        raise GateExecutionError("browser fixture provenance is unavailable")
    return {
        "nonce": uuid.uuid4().hex,
        "manifest_sha256": manifest_sha256,
        "policy_sha256": policy_sha256,
        "extraction_image_id": image_id,
        "provenance_sha256": _sha256_path(provenance_path),
    }


def _run_local_browser(
    config: GateConfig, evidence_path: Path, attestation: Mapping[str, str]
) -> None:
    """Run the browser proof in a fresh path, never accepting a stale JSON file."""

    viewer_root = (config.viewer_root or Path(__file__).resolve().parent / "viewer").resolve()
    if not viewer_root.is_dir():
        raise GateExecutionError("viewer proof workspace is unavailable")
    if not config.browser_binary or any(character.isspace() for character in config.browser_binary):
        raise GateExecutionError("browser binary must be one token")
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment["AXIT_G0_BROWSER_EVIDENCE_PATH"] = str(evidence_path.resolve())
    environment["AXIT_G0_BROWSER_ATTESTATION_JSON"] = json.dumps(
        dict(attestation), ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    resolved_binary = shutil.which(config.browser_binary)
    if resolved_binary is None:
        raise GateExecutionError("browser test command is unavailable")
    completed = subprocess.run(
        [resolved_binary, "test", "--prefix", str(viewer_root)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        timeout=240,
        check=False,
    )
    if completed.returncode != 0 or not evidence_path.is_file():
        raise GateExecutionError("fresh browser proof command failed")


def _load_browser_proofs(
    path: Path | None,
    *,
    golden_paths: Sequence[str],
    expected_attestation: Mapping[str, str],
) -> Mapping[str, Any]:
    if path is None:
        raise GateExecutionError("browser evidence path is required")
    raw, _ = _json_object(path, "browser evidence")
    fixtures = raw.get("fixtures")
    attestation = raw.get("attestation")
    expected_attestation_keys = {
        "nonce",
        "manifest_sha256",
        "policy_sha256",
        "extraction_image_id",
        "provenance_sha256",
    }
    if (
        set(raw) != {"schema_version", "attestation", "fixtures"}
        or raw.get("schema_version") != 2
        or not isinstance(attestation, Mapping)
        or set(attestation) != expected_attestation_keys
        or dict(attestation) != dict(expected_attestation)
        or not isinstance(fixtures, dict)
        or set(fixtures) != set(golden_paths)
    ):
        raise GateExecutionError("browser evidence contract is invalid")
    return cast(Mapping[str, Any], fixtures)


def _browser_proof(raw: object) -> tuple[dict[str, object], bool]:
    fallback: dict[str, object] = {
        "selected_count": 0,
        "target_anchor_set_hash": "",
        "deep_link_match": False,
        "geometry_match": False,
        "external_requests": -1,
    }
    if not isinstance(raw, Mapping):
        return fallback, False
    keys = set(raw)
    if keys != set(fallback):
        return fallback, False
    anchor_hash = raw.get("target_anchor_set_hash")
    valid = (
        raw.get("selected_count") == 1
        and not isinstance(raw.get("selected_count"), bool)
        and isinstance(anchor_hash, str)
        and _SHA256.fullmatch(anchor_hash) is not None
        and raw.get("deep_link_match") is True
        and raw.get("geometry_match") is True
        and raw.get("external_requests") == 0
        and not isinstance(raw.get("external_requests"), bool)
    )
    if not valid:
        return fallback, False
    return {key: cast(object, raw[key]) for key in fallback}, True


def _request(
    *,
    image: str,
    fixture: _Fixture,
    name: str,
    probe: str | None = None,
    network_probe_host: str = "1.1.1.1",
    network_probe_port: int = 53,
    collect_resource_usage: bool = False,
) -> SandboxRequest:
    return SandboxRequest(
        image=image,
        input_bytes=fixture.source_bytes,
        original_filename=PurePosixPath(fixture.relative_path).name,
        container_name=name,
        probe=probe,
        network_probe_host=network_probe_host,
        network_probe_port=network_probe_port,
        collect_resource_usage=collect_resource_usage,
    )


def _observation(execution: SandboxExecution) -> _Observation | None:
    if (
        execution.ok is not True
        or execution.error_code is not None
        or execution.stderr_bytes != 0
        or execution.exit_code != 0
        or execution.killed
        or not isinstance(execution.payload, Mapping)
        or execution.payload.get("ok") is not True
    ):
        return None
    result = execution.payload.get("result")
    if not isinstance(result, Mapping):
        return None
    anchor_hash = result.get("anchor_set_hash")
    blocks = result.get("blocks")
    warnings = result.get("warnings")
    if (
        not isinstance(anchor_hash, str)
        or _SHA256.fullmatch(anchor_hash) is None
        or not isinstance(blocks, Sequence)
        or isinstance(blocks, (str, bytes, bytearray))
        or not blocks
        or not isinstance(warnings, Sequence)
        or isinstance(warnings, (str, bytes, bytearray))
    ):
        return None
    texts: list[str] = []
    warning_codes: list[str] = []
    for block in blocks:
        if not isinstance(block, Mapping) or not isinstance(block.get("text"), str):
            return None
        texts.append(cast(str, block["text"]))
    for warning in warnings:
        if not isinstance(warning, Mapping) or not isinstance(warning.get("code"), str):
            return None
        warning_codes.append(cast(str, warning["code"]))
    return _Observation(
        anchor_set_hash=anchor_hash,
        text="\n".join(texts),
        warnings=tuple(warning_codes),
        duration_ms=execution.duration_ms,
    )


def _anchor_kinds_match(execution: SandboxExecution, expected_kind: object) -> bool:
    if not isinstance(expected_kind, str) or not isinstance(execution.payload, Mapping):
        return False
    result = execution.payload.get("result")
    if not isinstance(result, Mapping) or not isinstance(
        result.get("blocks"), Sequence
    ):
        return False
    blocks = cast(Sequence[object], result["blocks"])
    return bool(blocks) and all(
        isinstance(block, Mapping)
        and isinstance(block.get("anchor"), Mapping)
        and cast(Mapping[str, Any], block["anchor"]).get("kind") == expected_kind
        for block in blocks
    )


def _source_matches(execution: SandboxExecution | None, fixture: _Fixture) -> bool:
    return execution is not None and execution.source_sha256 == fixture.sha256


def _expected_structure_matches(execution: SandboxExecution, fixture: _Fixture) -> bool:
    """Apply manifest assertions that cannot be inferred from hash stability alone."""

    if not isinstance(execution.payload, Mapping):
        return False
    result = execution.payload.get("result")
    if not isinstance(result, Mapping):
        return False
    if result.get("media_type") != fixture.media_type:
        return False
    profile = fixture.expected.get("normalization_profile")
    if profile is not None and result.get("normalization_profile") != profile:
        return False
    blocks = result.get("blocks")
    if not isinstance(blocks, Sequence) or isinstance(blocks, (str, bytes, bytearray)):
        return False
    typed_blocks = [item for item in blocks if isinstance(item, Mapping)]
    if len(typed_blocks) != len(blocks):
        return False
    required_block_types = fixture.expected.get("required_block_types")
    if required_block_types is not None:
        if (
            not isinstance(required_block_types, Sequence)
            or isinstance(required_block_types, (str, bytes, bytearray))
            or any(not isinstance(item, str) or not item for item in required_block_types)
        ):
            return False
        block_types = {item.get("block_type") for item in typed_blocks}
        if not set(cast(Sequence[str], required_block_types)).issubset(block_types):
            return False
    if fixture.expected.get("requires_complete_structural_paths") is True:
        for block in typed_blocks:
            block_type = block.get("block_type")
            anchor = block.get("anchor")
            if not isinstance(anchor, Mapping):
                return False
            locator = anchor.get("locator")
            if not isinstance(locator, Mapping):
                return False
            if block_type == "hwp_table_cell":
                table = locator.get("table")
                if not isinstance(table, Mapping) or set(table) != {
                    "index",
                    "block",
                    "row",
                    "cell",
                    "paragraph",
                }:
                    return False
                if any(
                    isinstance(table.get(field), bool)
                    or not isinstance(table.get(field), int)
                    or table[field] < 0
                    for field in ("index", "block", "row", "cell", "paragraph")
                ):
                    return False
            if block_type == "hwp_footnote":
                footnote = locator.get("footnote")
                if not isinstance(footnote, Mapping) or set(footnote) != {
                    "index",
                    "paragraph",
                }:
                    return False
                if any(
                    isinstance(footnote.get(field), bool)
                    or not isinstance(footnote.get(field), int)
                    or footnote[field] < 0
                    for field in ("index", "paragraph")
                ):
                    return False
    if fixture.expected.get("has_text_layer") is True and not all(
        item.get("block_type") == "pdf_text" for item in typed_blocks
    ):
        return False
    if fixture.expected.get("image_only") is True and not all(
        item.get("block_type") == "pdf_ocr" for item in typed_blocks
    ):
        return False
    required_bbox = fixture.expected.get("required_anchor_bbox")
    if required_bbox is not None:
        if (
            not isinstance(required_bbox, Sequence)
            or isinstance(required_bbox, (str, bytes, bytearray))
            or len(required_bbox) != 4
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in required_bbox)
        ):
            return False
        expected_bbox = [round(float(value), 6) for value in required_bbox]
        observed_bboxes: list[list[float]] = []
        for block in typed_blocks:
            anchor = block.get("anchor")
            locator = anchor.get("locator") if isinstance(anchor, Mapping) else None
            bbox = locator.get("bbox") if isinstance(locator, Mapping) else None
            if (
                isinstance(bbox, Sequence)
                and not isinstance(bbox, (str, bytes, bytearray))
                and len(bbox) == 4
                and all(
                    not isinstance(value, bool) and isinstance(value, (int, float))
                    for value in bbox
                )
            ):
                observed_bboxes.append([round(float(value), 6) for value in bbox])
        if expected_bbox not in observed_bboxes:
            return False
    return True


def _safe_execute(
    executor: SandboxExecutor,
    request: SandboxRequest,
    policy: SandboxPolicy,
) -> SandboxExecution | None:
    try:
        return executor(request, policy)
    except Exception:
        return None


def _stable(values: Sequence[str], expected: int) -> bool:
    return (
        len(values) == expected
        and all(_SHA256.fullmatch(value) is not None for value in values)
        and len(set(values)) == 1
    )


def _strict_probe(
    probe: str,
    execution: SandboxExecution | None,
    policy: SandboxPolicy,
    *,
    network_probe_host: str | None = None,
    network_probe_port: int | None = None,
) -> tuple[bool, dict[str, object]]:
    details: dict[str, object] = {"duration_ms": -1, "recovery_passed": False}
    if execution is None:
        return False, details
    details["duration_ms"] = execution.duration_ms
    if execution.stderr_bytes != 0:
        return False, details
    if probe in {"timeout", "output"}:
        expected = "PARSER_TIMEOUT" if probe == "timeout" else "PARSER_OUTPUT_LIMIT"
        passed = (
            execution.ok is False
            and execution.error_code == expected
            and execution.killed is True
            and execution.payload is None
            and (probe != "output" or execution.stdout_bytes == policy.max_stdout_bytes)
            and (
                probe != "timeout"
                or execution.duration_ms
                <= (policy.wall_timeout_seconds + policy.stop_grace_seconds + 1) * 1000
            )
        )
        return passed, details
    if (
        not execution.ok
        or execution.error_code is not None
        or execution.exit_code != 0
        or execution.killed
        or not isinstance(execution.payload, Mapping)
    ):
        return False, details
    envelope = execution.payload
    result = envelope.get("probe")
    if not isinstance(result, Mapping):
        return False, details
    if probe == "network":
        expected_keys = {
            "kind",
            "outbound_network_reachable",
            "target_host",
            "target_port",
        }
        passed = (
            set(result) == expected_keys
            and result.get("kind") == probe
            and result.get("outbound_network_reachable") is False
            and result.get("target_host") == network_probe_host
            and result.get("target_port") == network_probe_port
        )
    elif probe == "secret":
        expected_keys = {
            "kind",
            "sensitive_environment_present",
            "secret_mount_present",
        }
        passed = (
            set(result) == expected_keys
            and result.get("kind") == probe
            and result.get("sensitive_environment_present") is False
            and result.get("secret_mount_present") is False
        )
    else:
        expected_keys = {
            "kind",
            "capabilities_zero",
            "cgroup_cpu_max",
            "cgroup_memory_max",
            "cgroup_pids_max",
            "docker_socket_present",
            "effective_uid",
            "input_writable",
            "no_new_privileges",
            "root_filesystem_writable",
            "temporary_directory_writable",
            "temporary_filesystem_type",
            "temporary_mount_options",
            "temporary_capacity_bytes",
        }
        passed = (
            set(result) == expected_keys
            and result.get("kind") == probe
            and result.get("capabilities_zero") is True
            and result.get("no_new_privileges") is True
            and result.get("docker_socket_present") is False
            and result.get("effective_uid") == policy.uid
            and result.get("input_writable") is False
            and result.get("root_filesystem_writable") is False
            and result.get("temporary_directory_writable") is True
            and result.get("temporary_filesystem_type") == "tmpfs"
            and isinstance(result.get("temporary_mount_options"), Sequence)
            and not isinstance(
                result.get("temporary_mount_options"), (str, bytes, bytearray)
            )
            and {"rw", "noexec", "nosuid", "nodev"}.issubset(
                set(cast(Sequence[object], result["temporary_mount_options"]))
            )
            and not isinstance(result.get("temporary_capacity_bytes"), bool)
            and isinstance(result.get("temporary_capacity_bytes"), int)
            and 0 < cast(int, result["temporary_capacity_bytes"]) <= policy.tmpfs_bytes
            and _cpu_limit_matches(result.get("cgroup_cpu_max"), policy.cpus)
            and _integer_limit_matches(
                result.get("cgroup_memory_max"), policy.memory_bytes
            )
            and _integer_limit_matches(result.get("cgroup_pids_max"), policy.pids)
        )
        details["cgroup_cpu_max"] = result.get("cgroup_cpu_max")
        details["cgroup_memory_max"] = result.get("cgroup_memory_max")
        details["cgroup_pids_max"] = result.get("cgroup_pids_max")
        details["temporary_filesystem_type"] = result.get("temporary_filesystem_type")
        details["temporary_mount_options"] = result.get("temporary_mount_options")
        details["temporary_capacity_bytes"] = result.get("temporary_capacity_bytes")
    return passed, details


def _integer_limit_matches(raw: object, expected: int) -> bool:
    if not isinstance(raw, str) or not raw.isascii():
        return False
    try:
        return int(raw) == expected
    except ValueError:
        return False


def _cpu_limit_matches(raw: object, expected: float) -> bool:
    if not isinstance(raw, str):
        return False
    parts = raw.split()
    try:
        if len(parts) == 2 and parts[0] != "max":
            quota, period = (int(value) for value in parts)
            return period > 0 and math.isclose(quota / period, expected, rel_tol=0.01)
        if len(parts) == 1:
            return int(parts[0]) > 0
    except ValueError:
        return False
    return False


def _static_sandbox_checks(
    request: SandboxRequest, policy: SandboxPolicy
) -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="axit-g0-static-") as directory:
        staged_path = Path(directory) / "source"
        staged_path.write_bytes(request.input_bytes)
        command = build_docker_command(
            request, policy, staged_input_path=staged_path
        )
    return {
        "network_none": "--network=none" in command,
        "read_only_rootfs": "--read-only" in command,
        "tmpfs_bounded": command[command.index("--tmpfs") + 1]
        == f"/tmp:rw,noexec,nosuid,nodev,size={policy.tmpfs_bytes}",
        "cpu_limit_applied": f"--cpus={policy.cpus}" in command,
        "memory_limit_applied": f"--memory={policy.memory_bytes}" in command
        and f"--memory-swap={policy.memory_swap_bytes}" in command,
        "pid_limit_applied": f"--pids-limit={policy.pids}" in command,
        "log_driver_none": "--log-driver=none" in command,
    }


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    )
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        output.write(serialized)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def _derive_leak_scan(
    evidence_body: Mapping[str, Any], fixtures: Sequence[_Fixture]
) -> dict[str, object]:
    """Scan the bounded evidence body without ever persisting sensitive values."""

    serialized = json.dumps(
        evidence_body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    raw_markers = {
        text
        for fixture in fixtures
        for text in (fixture.expected.get("text_nfc"),)
        if isinstance(text, str) and len(text) >= 4
    }
    raw_matches = sum(serialized.count(marker) for marker in raw_markers)
    secret_patterns = (
        re.compile(r"(?i)postgres(?:ql)?://[^\s\"']+"),
        re.compile(r"(?i)bearer\s+[a-z0-9._~+/-]{12,}"),
        re.compile(r"(?i)(?:sk|xai)-[a-z0-9_-]{12,}"),
    )
    secret_matches = sum(
        len(pattern.findall(serialized)) for pattern in secret_patterns
    )
    return {
        "secret_matches": secret_matches,
        "raw_content_matches": raw_matches,
        "method": "bounded-evidence-marker-scan-v1; stderr must be empty",
    }


class _LocalNetworkControl:
    """A controlled same-image listener used to make the network probe meaningful."""

    host = "g0-probe"
    port = 18_080

    def __init__(self, docker: "LocalDockerLayer", image: str, prefix: str) -> None:
        self._docker = docker
        self._network_name = f"{prefix}-network"
        self._listener_name = f"{prefix}-listener"
        self._network_created = False
        self._listener_started = False
        self.reachable = False
        try:
            created = docker._run(
                (docker.binary, "network", "create", "--internal", self._network_name),
                timeout=30,
            )
            if created.returncode != 0:
                return
            self._network_created = True
            listener = docker._run(
                (
                    docker.binary,
                    "run",
                    "-d",
                    "--rm",
                    "--pull=never",
                    f"--name={self._listener_name}",
                    "--network",
                    self._network_name,
                    "--network-alias",
                    self.host,
                    image,
                    "python",
                    "-m",
                    "http.server",
                    str(self.port),
                    "--bind",
                    "0.0.0.0",
                    "--directory",
                    "/tmp",
                ),
                timeout=30,
            )
            if listener.returncode != 0:
                return
            self._listener_started = True
            for _ in range(10):
                probe = docker._run(
                    (
                        docker.binary,
                        "run",
                        "--rm",
                        "--pull=never",
                        "--network",
                        self._network_name,
                        image,
                        "python",
                        "-c",
                        (
                            "import socket; "
                            f"connection=socket.create_connection(({self.host!r}, {self.port}), timeout=2); "
                            "connection.close()"
                        ),
                    ),
                    timeout=15,
                )
                if probe.returncode == 0:
                    self.reachable = True
                    break
                time.sleep(0.2)
        except (OSError, subprocess.SubprocessError):
            self.reachable = False

    def close(self) -> None:
        if self._listener_started:
            try:
                self._docker._run(
                    (self._docker.binary, "rm", "--force", self._listener_name),
                    timeout=15,
                )
            except (OSError, subprocess.SubprocessError):
                pass
            self._listener_started = False
        if self._network_created:
            try:
                self._docker._run(
                    (self._docker.binary, "network", "rm", self._network_name),
                    timeout=15,
                )
            except (OSError, subprocess.SubprocessError):
                pass
            self._network_created = False


class LocalDockerLayer:
    def __init__(self, docker_binary: str = "docker") -> None:
        self.binary = docker_binary

    def _run(
        self, arguments: Sequence[str], *, timeout: float = 30
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=timeout,
            check=False,
        )

    def image_runtime(self, image: str) -> Mapping[str, Any]:
        inspected = self._run((self.binary, "image", "inspect", image))
        info = self._run((self.binary, "info", "--format", "{{json .}}"))
        if inspected.returncode != 0 or info.returncode != 0:
            raise GateExecutionError("Docker image/runtime inspection failed")
        try:
            images = json.loads(inspected.stdout)
            docker_info = json.loads(info.stdout)
            image_object = images[0]
            image_id = image_object["Id"]
            image_size = image_object["Size"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise GateExecutionError("Docker inspection output is invalid") from error
        if (
            not isinstance(image_id, str)
            or _IMAGE_ID.fullmatch(image_id) is None
            or isinstance(image_size, bool)
            or not isinstance(image_size, int)
            or image_size <= 0
            or not isinstance(docker_info, dict)
        ):
            raise GateExecutionError("Docker runtime metadata is invalid")
        cpu_model = (
            platform.processor()
            or os.environ.get("PROCESSOR_IDENTIFIER")
            or "unknown-host-cpu"
        )
        logical_cpus = docker_info.get("NCPU", os.cpu_count())
        memory_bytes = docker_info.get("MemTotal")
        hardware = {
            "os": str(docker_info.get("OperatingSystem") or platform.system()),
            "architecture": str(docker_info.get("Architecture") or platform.machine()),
            "cpu_model": cpu_model,
            "docker_server_version": str(docker_info.get("ServerVersion") or "unknown"),
            "logical_cpus": logical_cpus,
            "memory_bytes": memory_bytes,
        }
        return {
            "image_id": image_id,
            "image_size_bytes": image_size,
            "repo_digests": sorted(
                item
                for item in image_object.get("RepoDigests", [])
                if isinstance(item, str)
            ),
            "hardware": hardware,
        }

    def open_network_control(self, image: str, *, prefix: str) -> NetworkControl:
        return _LocalNetworkControl(self, image, prefix)

    def orphan_names(self, prefix: str) -> tuple[str, ...]:
        completed = self._run(
            (
                self.binary,
                "ps",
                "--all",
                "--filter",
                f"name={prefix}",
                "--format",
                "{{.Names}}",
            ),
            timeout=15,
        )
        if completed.returncode != 0:
            return ("docker-orphan-scan-failed",)
        return tuple(
            sorted(
                name
                for name in completed.stdout.splitlines()
                if name.startswith(prefix)
            )
        )

    def orphan_network_names(self, prefix: str) -> tuple[str, ...]:
        completed = self._run(
            (
                self.binary,
                "network",
                "ls",
                "--filter",
                f"name={prefix}",
                "--format",
                "{{.Name}}",
            ),
            timeout=15,
        )
        if completed.returncode != 0:
            return ("docker-network-orphan-scan-failed",)
        return tuple(
            sorted(
                name
                for name in completed.stdout.splitlines()
                if name.startswith(prefix)
            )
        )

    def orchestrator_secret_present(self, compose_path: Path) -> bool:
        completed = self._run(
            (
                self.binary,
                "compose",
                "-f",
                str(compose_path),
                "exec",
                "-T",
                "orchestrator",
                "python",
                "-c",
                "import os,sys;sys.exit(0 if os.environ.get('DATABASE_URL') else 1)",
            ),
            timeout=20,
        )
        return completed.returncode == 0


def run_gate(
    config: GateConfig,
    *,
    executor: SandboxExecutor | None = None,
    docker: DockerLayer | None = None,
    browser_runner: BrowserRunner | None = None,
) -> GateRun:
    """Run G0 with a new immutable source snapshot for every execution.

    ``warm`` is intentionally a repeated post-cold execution, not a reused
    container.  This keeps the same host staging and short-lived container
    boundary in force for every sample and makes its wall timeout meaningful.
    """

    if config.cold_repeats < 3 or config.warm_repeats < 3:
        raise GateExecutionError(
            "cold and warm repetitions must each be at least three"
        )
    if not config.image or any(character.isspace() for character in config.image):
        raise GateExecutionError("image reference must be one non-empty token")

    manifest, manifest_sha256, fixtures = _load_manifest(config)
    policy = SandboxPolicy.from_json(config.policy_path)
    policy_sha256 = _sha256_path(config.policy_path)
    licenses = _load_licenses(config.licenses_path)
    active_docker = docker or LocalDockerLayer(config.docker_binary)
    active_executor = executor or (
        lambda request, active_policy: execute_sandbox(
            request, active_policy, docker_binary=config.docker_binary
        )
    )
    runtime = dict(active_docker.image_runtime(config.image))
    image_id = runtime.get("image_id")
    if not isinstance(image_id, str) or _IMAGE_ID.fullmatch(image_id) is None:
        raise GateExecutionError("resolved image ID is not content addressed")

    run_prefix = f"axit-g0-gate-{uuid.uuid4().hex[:12]}"
    golden = tuple(item for item in fixtures if item.classification == "golden")
    malicious = tuple(item for item in fixtures if item.classification == "malicious")
    ledger = _Ledger()

    browser_proofs: Mapping[str, Any] = {}
    browser_error: str | None = None
    browser_attestation: Mapping[str, str] | None = None
    browser_path = (
        config.browser_evidence_path.resolve()
        if config.browser_evidence_path is not None
        else None
    )
    if browser_path is None:
        browser_error = "BROWSER_EVIDENCE_PATH_REQUIRED"
    else:
        try:
            browser_attestation = _browser_attestation(
                config,
                manifest_sha256=manifest_sha256,
                policy_sha256=policy_sha256,
                image_id=image_id,
            )
            browser_path.parent.mkdir(parents=True, exist_ok=True)
            browser_path.unlink(missing_ok=True)
            if browser_runner is None:
                _run_local_browser(config, browser_path, browser_attestation)
            else:
                browser_runner(browser_path, browser_attestation)
            browser_proofs = _load_browser_proofs(
                browser_path,
                golden_paths=[item.relative_path for item in golden],
                expected_attestation=browser_attestation,
            )
        except (
            GateExecutionError,
            OSError,
            ValueError,
            subprocess.SubprocessError,
        ) as error:
            # Persist only a bounded category: browser output and command output
            # may contain content that must never become G0 evidence.
            browser_error = type(error).__name__
            browser_proofs = {}
    ledger.record("browser:fresh-attested-proof", browser_error is None, "BROWSER_PROOF_MISSING")

    peak_memory = 0
    peak_pids = 0
    first_cold_ms = 0

    def record_runtime_sample(execution: SandboxExecution | None) -> None:
        nonlocal peak_memory, peak_pids
        if execution is None:
            return
        memory = execution.peak_memory_bytes
        pids = execution.peak_pids
        if not isinstance(memory, bool) and isinstance(memory, int) and memory > 0:
            peak_memory = max(peak_memory, memory)
        if not isinstance(pids, bool) and isinstance(pids, int) and pids > 0:
            peak_pids = max(peak_pids, pids)

    def source_hash(execution: SandboxExecution | None) -> str | None:
        return execution.source_sha256 if execution is not None else None

    golden_evidence: dict[str, Any] = {}
    observations: dict[str, _Observation] = {}
    for fixture_index, fixture in enumerate(golden):
        cold_hashes: list[str] = []
        warm_hashes: list[str] = []
        cold_sources: list[str | None] = []
        warm_sources: list[str | None] = []
        durations: list[int] = []
        executions: list[SandboxExecution | None] = []

        for phase, repeats, hashes, sources in (
            ("cold", config.cold_repeats, cold_hashes, cold_sources),
            ("warm", config.warm_repeats, warm_hashes, warm_sources),
        ):
            for repeat in range(repeats):
                execution = _safe_execute(
                    active_executor,
                    _request(
                        image=image_id,
                        fixture=fixture,
                        name=f"{run_prefix}-{phase[0]}{fixture_index}-{repeat}",
                        collect_resource_usage=True,
                    ),
                    policy,
                )
                executions.append(execution)
                sources.append(source_hash(execution))
                record_runtime_sample(execution)
                if execution is not None:
                    durations.append(execution.duration_ms)
                    if phase == "cold" and first_cold_ms == 0:
                        first_cold_ms = max(1, execution.duration_ms)
                observation = _observation(execution) if execution is not None else None
                execution_valid = (
                    execution is not None
                    and _source_matches(execution, fixture)
                    and _expected_structure_matches(execution, fixture)
                )
                if observation is not None and execution_valid:
                    hashes.append(observation.anchor_set_hash)
                    if phase == "cold":
                        observations.setdefault(fixture.relative_path, observation)

        baseline = observations.get(fixture.relative_path)
        source_snapshot_matches = (
            len(executions) == config.cold_repeats + config.warm_repeats
            and all(_source_matches(item, fixture) for item in executions)
        )
        structure_verified = (
            len(executions) == config.cold_repeats + config.warm_repeats
            and all(
                item is not None and _expected_structure_matches(item, fixture)
                for item in executions
            )
        )
        kinds_ok = bool(executions) and all(
            item is not None
            and _anchor_kinds_match(item, fixture.expected.get("anchor_kind"))
            for item in executions
        )
        stable = (
            _stable(cold_hashes, config.cold_repeats)
            and _stable(warm_hashes, config.warm_repeats)
            and cold_hashes[0] == warm_hashes[0]
        )
        all_clean = (
            len(executions) == config.cold_repeats + config.warm_repeats
            and all(
                item is not None
                and item.stderr_bytes == 0
                and _observation(item) is not None
                for item in executions
            )
        )
        expected_text = fixture.expected.get("text_nfc")
        text_accuracy: float | None = None
        text_ok = isinstance(expected_text, str) and baseline is not None
        if text_ok and isinstance(expected_text, str) and baseline is not None:
            text_accuracy = ocr_character_accuracy(expected_text, baseline.text)
            minimum = fixture.expected.get("min_ocr_accuracy")
            required_warning = fixture.expected.get("required_warning")
            if minimum is not None:
                text_ok = (
                    not isinstance(minimum, bool)
                    and isinstance(minimum, (int, float))
                    and text_accuracy >= minimum
                )
            elif required_warning is None:
                text_ok = text_accuracy == 1.0
        warnings = tuple(sorted(set(baseline.warnings if baseline else ())))
        warning_expected = fixture.expected.get("required_warning")
        warning_ok = warning_expected is None or warning_expected in warnings
        extraction_ok = (
            stable
            and all_clean
            and source_snapshot_matches
            and structure_verified
            and kinds_ok
            and text_ok
            and warning_ok
        )
        ledger.record(
            f"golden:{fixture.relative_path}:extraction",
            extraction_ok,
            "GOLDEN_EXTRACTION_FAILED",
        )
        browser, browser_valid = _browser_proof(browser_proofs.get(fixture.relative_path))
        browser_valid = (
            browser_valid
            and bool(cold_hashes)
            and browser["target_anchor_set_hash"] == cold_hashes[0]
        )
        ledger.record(
            f"golden:{fixture.relative_path}:browser",
            browser_valid,
            "BROWSER_PROOF_MISSING",
        )
        item: dict[str, Any] = {
            "status": "passed" if extraction_ok else "failed",
            "cold_anchor_set_hashes": cold_hashes,
            "warm_anchor_set_hashes": warm_hashes,
            "cold_source_sha256s": cold_sources,
            "warm_source_sha256s": warm_sources,
            "source_snapshot_matches": source_snapshot_matches,
            "structure_verified": structure_verified,
            "duration_ms": durations,
            "warnings": list(warnings),
            "browser": browser,
            "warm_execution_mode": "isolated_short_lived",
        }
        if fixture.expected.get("min_ocr_accuracy") is not None:
            item["ocr_accuracy"] = text_accuracy
        golden_evidence[fixture.relative_path] = item

    recovery_fixture = golden[0]
    recovery_observation = observations.get(recovery_fixture.relative_path)
    malicious_evidence: dict[str, Any] = {}
    for fixture_index, fixture in enumerate(malicious):
        attack = _safe_execute(
            active_executor,
            _request(
                image=image_id,
                fixture=fixture,
                name=f"{run_prefix}-a{fixture_index}",
            ),
            policy,
        )
        expected_error = fixture.expected.get("error_code")
        attack_ok = (
            attack is not None
            and _source_matches(attack, fixture)
            and attack.ok is False
            and attack.error_code == expected_error
            and attack.stderr_bytes == 0
            and attack.duration_ms <= policy.wall_timeout_seconds * 1000
        )
        ledger.record(
            f"malicious:{fixture.relative_path}:typed",
            attack_ok,
            "ATTACK_REJECTION_FAILED",
        )
        recovery = _safe_execute(
            active_executor,
            _request(
                image=image_id,
                fixture=recovery_fixture,
                name=f"{run_prefix}-ar{fixture_index}",
            ),
            policy,
        )
        recovered = _observation(recovery) if recovery is not None else None
        recovery_ok = (
            recovery is not None
            and _source_matches(recovery, recovery_fixture)
            and _expected_structure_matches(recovery, recovery_fixture)
            and recovered is not None
            and recovery_observation is not None
            and recovered.anchor_set_hash == recovery_observation.anchor_set_hash
        )
        ledger.record(
            f"malicious:{fixture.relative_path}:recovery",
            recovery_ok,
            "RECOVERY_FAILED",
        )
        orphans = active_docker.orphan_names(run_prefix)
        ledger.record(
            f"malicious:{fixture.relative_path}:orphans",
            not orphans,
            "ORPHAN_CONTAINER",
        )
        malicious_evidence[fixture.relative_path] = {
            "error_code": attack.error_code if attack is not None else "HARNESS_EXECUTION_FAILED",
            "duration_ms": attack.duration_ms if attack is not None else -1,
            "source_sha256": source_hash(attack),
            "recovery_source_sha256": source_hash(recovery),
            "recovery_passed": recovery_ok,
            "orphan_processes": len(orphans),
        }

    oversized_prefix = b"%PDF-1.7\n"
    oversized_bytes = oversized_prefix + b"x" * (
        policy.max_input_bytes + 1 - len(oversized_prefix)
    )
    oversized_hash = hashlib.sha256(oversized_bytes).hexdigest()
    oversized = _safe_execute(
        active_executor,
        SandboxRequest(
            image=image_id,
            input_bytes=oversized_bytes,
            original_filename="oversized-input.pdf",
            container_name=f"{run_prefix}-oversized",
        ),
        policy,
    )
    oversized_ok = (
        oversized is not None
        and oversized.ok is False
        and oversized.error_code == "INPUT_TOO_LARGE"
        and oversized.payload is None
        and oversized.stderr_bytes == 0
        and oversized.source_sha256 == oversized_hash
    )
    ledger.record("oversized-input:typed", oversized_ok, "INPUT_SIZE_BOUNDARY_FAILED")
    oversized_evidence = {
        "error_code": oversized.error_code if oversized is not None else "HARNESS_EXECUTION_FAILED",
        "duration_ms": oversized.duration_ms if oversized is not None else -1,
        "source_sha256": source_hash(oversized),
    }

    probe_details: dict[str, Any] = {}
    probe_results: dict[str, bool] = {}
    filesystem_execution: SandboxExecution | None = None
    network_control_reachable = False
    network_control_cleaned = False
    for probe_index, probe in enumerate(_PROBE_NAMES):
        network_control: NetworkControl | None = None
        network_host: str | None = None
        network_port: int | None = None
        if probe == "network":
            try:
                network_control = active_docker.open_network_control(
                    image_id, prefix=run_prefix
                )
                network_control_reachable = network_control.reachable is True
                network_host = network_control.host
                network_port = network_control.port
            except Exception:
                network_control_reachable = False
                network_host = "g0-probe"
                network_port = 18_080
        execution = _safe_execute(
            active_executor,
            _request(
                image=image_id,
                fixture=recovery_fixture,
                name=f"{run_prefix}-p{probe_index}",
                probe=probe,
                network_probe_host=network_host or "1.1.1.1",
                network_probe_port=network_port or 53,
            ),
            policy,
        )
        if probe == "filesystem":
            filesystem_execution = execution
        probe_ok, details = _strict_probe(
            probe,
            execution,
            policy,
            network_probe_host=network_host,
            network_probe_port=network_port,
        )
        probe_ok = probe_ok and _source_matches(execution, recovery_fixture)
        probe_results[probe] = probe_ok
        recovery = _safe_execute(
            active_executor,
            _request(
                image=image_id,
                fixture=recovery_fixture,
                name=f"{run_prefix}-pr{probe_index}",
            ),
            policy,
        )
        recovered = _observation(recovery) if recovery is not None else None
        probe_recovery_ok = (
            recovery is not None
            and _source_matches(recovery, recovery_fixture)
            and _expected_structure_matches(recovery, recovery_fixture)
            and recovered is not None
            and recovery_observation is not None
            and recovered.anchor_set_hash == recovery_observation.anchor_set_hash
        )
        if network_control is not None:
            try:
                network_control.close()
            except Exception:
                pass
        orphans = active_docker.orphan_names(run_prefix)
        network_orphans = (
            active_docker.orphan_network_names(run_prefix)
            if probe == "network"
            else ()
        )
        if probe == "network":
            network_control_cleaned = not network_orphans and not orphans
            details["network_enabled_control_reachable"] = network_control_reachable
            details["network_control_orphans"] = len(network_orphans)
            details["target_host"] = network_host
            details["target_port"] = network_port
        details["source_sha256"] = source_hash(execution)
        details["recovery_source_sha256"] = source_hash(recovery)
        details["recovery_passed"] = probe_recovery_ok
        details["orphan_processes"] = len(orphans)
        ledger.record(f"probe:{probe}:boundary", probe_ok, "PROBE_FAILED")
        ledger.record(
            f"probe:{probe}:recovery", probe_recovery_ok, "PROBE_RECOVERY_FAILED"
        )
        ledger.record(f"probe:{probe}:orphans", not orphans, "ORPHAN_CONTAINER")
        if probe == "network":
            ledger.record(
                "probe:network:network-orphans",
                not network_orphans,
                "ORPHAN_NETWORK",
            )
        probe_details[probe] = details

    static_request = _request(
        image=image_id,
        fixture=recovery_fixture,
        name=f"{run_prefix}-static",
    )
    static = _static_sandbox_checks(static_request, policy)
    filesystem_probe: Mapping[str, Any] = {}
    if filesystem_execution is not None and isinstance(
        filesystem_execution.payload, Mapping
    ):
        candidate = filesystem_execution.payload.get("probe")
        if isinstance(candidate, Mapping):
            filesystem_probe = candidate
    sandbox = {
        "non_root": filesystem_probe.get("effective_uid") == policy.uid,
        "read_only_rootfs": static["read_only_rootfs"]
        and filesystem_probe.get("root_filesystem_writable") is False,
        "cap_eff_zero": filesystem_probe.get("capabilities_zero") is True,
        "no_new_privileges": filesystem_probe.get("no_new_privileges") is True,
        "network_none": static["network_none"]
        and probe_results.get("network") is True
        and network_control_reachable,
        "network_control_cleaned": network_control_cleaned,
        "input_read_only": filesystem_probe.get("input_writable") is False,
        "tmpfs_bounded": static["tmpfs_bounded"]
        and filesystem_probe.get("temporary_directory_writable") is True
        and filesystem_probe.get("temporary_filesystem_type") == "tmpfs"
        and isinstance(filesystem_probe.get("temporary_mount_options"), Sequence)
        and not isinstance(
            filesystem_probe.get("temporary_mount_options"),
            (str, bytes, bytearray),
        )
        and {"rw", "noexec", "nosuid", "nodev"}.issubset(
            set(cast(Sequence[object], filesystem_probe["temporary_mount_options"]))
        )
        and not isinstance(filesystem_probe.get("temporary_capacity_bytes"), bool)
        and isinstance(filesystem_probe.get("temporary_capacity_bytes"), int)
        and 0
        < cast(int, filesystem_probe["temporary_capacity_bytes"])
        <= policy.tmpfs_bytes,
        "cpu_limit_applied": static["cpu_limit_applied"]
        and _cpu_limit_matches(filesystem_probe.get("cgroup_cpu_max"), policy.cpus),
        "memory_limit_applied": static["memory_limit_applied"]
        and _integer_limit_matches(
            filesystem_probe.get("cgroup_memory_max"), policy.memory_bytes
        ),
        "pid_limit_applied": static["pid_limit_applied"]
        and _integer_limit_matches(filesystem_probe.get("cgroup_pids_max"), policy.pids),
        "wall_limit_applied": probe_results.get("timeout") is True,
        "output_limit_applied": probe_results.get("output") is True,
        "docker_socket_absent": filesystem_probe.get("docker_socket_present") is False,
        "secrets_absent": probe_results.get("secret") is True,
        "log_driver_none": static["log_driver_none"],
    }
    for key, value in sandbox.items():
        ledger.record(f"sandbox:{key}", value is True, "SANDBOX_PROOF_FAILED")

    try:
        orchestrator_secret_present = active_docker.orchestrator_secret_present(
            config.compose_path
        )
    except Exception:
        orchestrator_secret_present = False
    ledger.record(
        "positive-control:network",
        network_control_reachable,
        "POSITIVE_CONTROL_FAILED",
    )
    ledger.record(
        "positive-control:secret",
        orchestrator_secret_present,
        "POSITIVE_CONTROL_FAILED",
    )
    positive_control = {
        "network_enabled_control_reachable": network_control_reachable,
        "orchestrator_secret_present": orchestrator_secret_present,
    }

    try:
        final_runtime = active_docker.image_runtime(config.image)
        image_unchanged = final_runtime.get("image_id") == image_id
    except Exception:
        image_unchanged = False
    viewer_root = (config.viewer_root or Path(__file__).resolve().parent / "viewer").resolve()
    provenance_unchanged = (
        browser_attestation is not None
        and _path_matches_sha256(
            viewer_root / "fixtures" / "provenance.v1.json",
            browser_attestation["provenance_sha256"],
        )
    )
    artifact_integrity = {
        "manifest_unchanged": _path_matches_sha256(
            config.manifest_path, manifest_sha256
        ),
        "policy_unchanged": _path_matches_sha256(config.policy_path, policy_sha256),
        "browser_provenance_unchanged": provenance_unchanged,
        "image_unchanged": image_unchanged,
    }
    for key, value in artifact_integrity.items():
        ledger.record(f"artifact:{key}", value is True, "ARTIFACT_CHANGED")

    runtime["cold_start_ms"] = first_cold_ms
    runtime["peak_memory_bytes"] = peak_memory
    runtime["peak_pids"] = peak_pids
    runtime_ok = all(
        not isinstance(runtime.get(field), bool)
        and isinstance(runtime.get(field), (int, float))
        and math.isfinite(cast(float, runtime[field]))
        and cast(float, runtime[field]) > 0
        for field in (
            "image_size_bytes",
            "cold_start_ms",
            "peak_memory_bytes",
            "peak_pids",
        )
    )
    hardware = runtime.get("hardware")
    runtime_ok = (
        runtime_ok
        and isinstance(hardware, Mapping)
        and all(
            isinstance(hardware.get(field), str) and bool(hardware[field])
            for field in ("os", "architecture", "cpu_model", "docker_server_version")
        )
        and all(
            not isinstance(hardware.get(field), bool)
            and isinstance(hardware.get(field), (int, float))
            and math.isfinite(cast(float, hardware[field]))
            and cast(float, hardware[field]) > 0
            for field in ("logical_cpus", "memory_bytes")
        )
    )
    ledger.record("runtime:measured", runtime_ok, "RUNTIME_EVIDENCE_FAILED")
    license_ok = bool(licenses) and all(
        all(
            isinstance(item.get(field), str) and bool(item[field])
            for field in ("component", "version", "spdx", "source_url")
        )
        and item.get("redistributable") is True
        for item in licenses
    )
    ledger.record("licenses:redistributable", license_ok, "LICENSE_INVENTORY_FAILED")

    evidence: dict[str, Any] = {
        "schema_version": 1,
        "manifest_sha256": manifest_sha256,
        "image_reference": config.image,
        "repetitions": {
            "cold": config.cold_repeats,
            "warm": config.warm_repeats,
            "warm_execution_mode": "isolated_short_lived",
        },
        "browser_proof": {
            "fresh_attested": browser_error is None,
            "error": browser_error,
        },
        "golden": golden_evidence,
        "malicious": malicious_evidence,
        "oversized_input": oversized_evidence,
        "sandbox": sandbox,
        "sandbox_details": probe_details,
        "positive_control": positive_control,
        "artifact_integrity": artifact_integrity,
        "runtime": runtime,
        "licenses": licenses,
    }
    leak_scan = _derive_leak_scan(evidence, fixtures)
    leak_free = (
        leak_scan["secret_matches"] == 0 and leak_scan["raw_content_matches"] == 0
    )
    ledger.record("leak-scan:bounded-evidence", leak_free, "EVIDENCE_LEAK_DETECTED")
    evidence["leak_scan"] = leak_scan
    evidence["test_counts"] = ledger.counts()
    evidence["failures"] = ledger.failures
    decision = evaluate_g0(
        manifest, evidence, wall_limit_seconds=policy.wall_timeout_seconds
    )
    evidence["decision"] = {
        "status": decision.status,
        "blockers": list(decision.blockers),
        "warnings": list(decision.warnings),
    }
    _atomic_json(config.output_path, evidence)
    return GateRun(decision, evidence)


def _default_config(arguments: argparse.Namespace) -> GateConfig:
    spike_root = Path(__file__).resolve().parent
    repository_root = spike_root.parents[1]
    return GateConfig(
        image=arguments.image,
        fixture_root=arguments.fixture_root,
        manifest_path=arguments.manifest,
        output_path=arguments.output,
        policy_path=arguments.policy or spike_root / "policy.v1.json",
        licenses_path=arguments.licenses or spike_root / "licenses.lock.json",
        compose_path=arguments.compose or repository_root / "docker-compose.yml",
        browser_evidence_path=arguments.browser_evidence,
        viewer_root=arguments.viewer_root or spike_root / "viewer",
        browser_binary=arguments.browser_binary,
        cold_repeats=arguments.cold_repeats,
        warm_repeats=arguments.warm_repeats,
        docker_binary=arguments.docker_binary,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-evidence", type=Path)
    parser.add_argument("--viewer-root", type=Path)
    parser.add_argument("--browser-binary", default="npm")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--licenses", type=Path)
    parser.add_argument("--compose", type=Path)
    parser.add_argument("--cold-repeats", type=int, default=3)
    parser.add_argument("--warm-repeats", type=int, default=3)
    parser.add_argument("--docker-binary", default="docker")
    arguments = parser.parse_args(argv)
    try:
        run = run_gate(_default_config(arguments))
    except (
        GateExecutionError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {"status": "HARNESS_ERROR", "error": type(error).__name__},
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {"status": run.decision.status, "output": str(arguments.output)},
            sort_keys=True,
        )
    )
    return 0 if run.decision.status == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
