"""Ownership-safe lifecycle for the isolated notification/audit N4 stack.

Only ``compose config`` is intrinsically read-only.  Start/stop operations are
therefore guarded by a persisted manifest and exact Docker object identity.
The command runner is injectable so all lifecycle contracts can be tested
without changing live Docker state.
"""

from __future__ import annotations

import argparse
import json
import locale
import os
import random
import re
import shutil
import socket
import string
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID


PROJECT_PREFIX = "axit-n4-"
PROTECTED_PROJECT = "axit-phase0"
ACTIVE_STATUSES = frozenset(
    {"starting", "running", "start_failed", "cleanup_pending", "cleanup_failed"}
)
MANIFEST_SCHEMA = "axit.n4-compose-run"
MANIFEST_VERSION = 1
EXPECTED_SERVICES = frozenset({"postgres", "migrate", "api", "orchestrator", "web"})
PROJECT_PATTERN = re.compile(r"^axit-n4-\d{8}t\d{6}z-\d+-[a-z0-9]{8}$")
MAX_DIAGNOSTIC_LINES = 12
MAX_DIAGNOSTIC_LINE_CHARS = 240
MAX_SERVICE_LOG_LINES = 40
MAX_STALE_PROBE_OUTPUT_CHARS = 256
STALE_PROBE_KEYS = frozenset({"stale", "in_app_rows", "outbox_rows"})
_DIAGNOSTIC_MARKERS = (
    "error", "fail", "unhealthy", "exited", "denied", "not found", "cannot", "timeout"
)
_SECRET_VALUE = re.compile(
    r"(?i)\b((?:[a-z0-9]+[_-])*(?:password|passwd|secret|token|api[_-]?key|authorization|cookie))"
    r"(\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s;,]+)"
)
_URI_CREDENTIALS = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@")
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SUBST_ROW = re.compile(r"^\s*([a-z]:)\\?:\s*=>\s*(.*?)\s*$", re.IGNORECASE)
CommandRunner = Callable[[Sequence[str], Mapping[str, str] | None], subprocess.CompletedProcess[str]]
PortSelector = Callable[[int, set[int] | None], int]
SubstRecorder = Callable[[Mapping[str, Any] | None], None]


class LifecycleError(RuntimeError):
    """A blocking lifecycle or ownership validation failure."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def new_project_name(*, now: datetime | None = None, pid: int | None = None) -> str:
    instant = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = "".join(random.SystemRandom().choices(string.ascii_lowercase + string.digits, k=8))
    return f"{PROJECT_PREFIX}{instant.lower()}-{pid or os.getpid()}-{suffix}"


def select_loopback_port(requested: int, *, excluded: set[int] | None = None) -> int:
    excluded = excluded or set()
    if requested < 0 or requested > 65535:
        raise LifecycleError(f"invalid port: {requested}")
    if requested and requested in excluded:
        raise LifecycleError(f"port collision: {requested}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", requested))
        selected = int(probe.getsockname()[1])
    if selected in excluded:
        return select_loopback_port(0, excluded=excluded)
    return selected


def default_port_selector(requested: int, excluded: set[int] | None = None) -> int:
    return select_loopback_port(requested, excluded=excluded)


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError(f"cannot read manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LifecycleError("manifest must be a JSON object")
    return value


def validate_manifest_identity(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("version") != MANIFEST_VERSION:
        raise LifecycleError("unsupported N4 manifest schema")


def archive_completed_manifest(path: Path) -> Path | None:
    if not path.exists():
        return None
    manifest = read_manifest(path)
    if manifest.get("status") in ACTIVE_STATUSES:
        raise LifecycleError("an active N4 manifest already exists")
    archive = path.with_name(f"{path.stem}.{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json")
    os.replace(path, archive)
    return archive


def default_runner(
    argv: Sequence[str], env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    encoding = (
        locale.getpreferredencoding(False)
        if argv and str(argv[0]).casefold() == "subst"
        else "utf-8"
    )
    return subprocess.run(
        list(argv),
        check=False,
        capture_output=True,
        text=True,
        encoding=encoding,
        errors="replace",
        env=dict(env) if env is not None else None,
    )


def resolve_command(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise LifecycleError(f"{name} executable was not found on PATH")
    return executable


def canonical_uuid(value: str, label: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise LifecycleError(f"{label} must be a UUID") from exc


def validate_stale_probe_output(value: Any) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != STALE_PROBE_KEYS:
        raise LifecycleError("stale probe returned an unsupported result")
    if value.get("stale") is not True:
        raise LifecycleError("stale probe did not observe StaleLeaseError")
    for key in ("in_app_rows", "outbox_rows"):
        if type(value.get(key)) is not int or value[key] != 0:
            raise LifecycleError("stale probe effect escaped the queue fence")
    return {"stale": True, "in_app_rows": 0, "outbox_rows": 0}


def compose_failure_diagnostic(
    result: subprocess.CompletedProcess[str], *, project: str, root: Path
) -> dict[str, Any]:
    """Return a bounded, secret-redacted compose failure summary."""
    selected: list[tuple[str, bool]] = []
    services: set[str] = set()
    root_text = str(root.resolve())
    for raw_line in (*result.stdout.splitlines(), *result.stderr.splitlines()):
        line = _ANSI_ESCAPE.sub("", raw_line).strip()
        folded = line.casefold()
        mentioned = {
            service
            for service in EXPECTED_SERVICES
            if re.search(rf"(?<![a-z0-9]){re.escape(service)}(?![a-z0-9])", folded)
        }
        has_failure_marker = any(marker in folded for marker in _DIAGNOSTIC_MARKERS)
        if not mentioned and not has_failure_marker:
            continue
        if has_failure_marker:
            services.update(mentioned)
        line = line.replace(root_text, "<repo>").replace(project, "<project>")
        line = _URI_CREDENTIALS.sub(r"\1[redacted]@", line)
        line = _SECRET_VALUE.sub(r"\1\2[redacted]", line)
        selected.append((line[:MAX_DIAGNOSTIC_LINE_CHARS], has_failure_marker))
    truncated = len(selected) > MAX_DIAGNOSTIC_LINES
    chosen_indices = {
        index for index, (_, important) in enumerate(selected) if important
    }
    if len(chosen_indices) > MAX_DIAGNOSTIC_LINES:
        chosen_indices = set(sorted(chosen_indices)[-MAX_DIAGNOSTIC_LINES:])
    for index in range(len(selected) - 1, -1, -1):
        if len(chosen_indices) >= MAX_DIAGNOSTIC_LINES:
            break
        chosen_indices.add(index)
    return {
        "returncode": int(result.returncode),
        "failing_services": sorted(services),
        "output_excerpt": [selected[index][0] for index in sorted(chosen_indices)],
        "truncated": truncated,
    }


def _is_non_ascii_buildkit_grpc_failure(
    result: subprocess.CompletedProcess[str], root: Path
) -> bool:
    output = f"{result.stdout}\n{result.stderr}".casefold()
    return (
        result.returncode != 0
        and _contains_non_ascii(str(root))
        and "failed to dial grpc" in output
        and "x-docker-expose-session-sharedkey" in output
        and "non-printable ascii" in output
    )


@dataclass(frozen=True)
class ComposeTarget:
    project: str
    base_config: Path
    n4_config: Path

    def __post_init__(self) -> None:
        if not PROJECT_PATTERN.fullmatch(self.project) or self.project == PROTECTED_PROJECT:
            raise LifecycleError("N4 project must have the unique axit-n4- prefix")
        if not self.base_config.is_absolute() or not self.n4_config.is_absolute():
            raise LifecycleError("compose config paths must be absolute")

    def argv(self, *arguments: str) -> list[str]:
        return [
            "docker",
            "compose",
            "-p",
            self.project,
            "-f",
            str(self.base_config),
            "-f",
            str(self.n4_config),
            *arguments,
        ]


def compose_environment(web_port: int, api_port: int) -> dict[str, str]:
    web_url = f"http://127.0.0.1:{web_port}"
    return {
        **os.environ,
        "N4_WEB_PORT": str(web_port),
        "N4_API_PORT": str(api_port),
        "N4_PUBLIC_HOST": f"127.0.0.1:{web_port}",
        "N4_PUBLIC_ORIGIN": web_url,
    }


def _published_ports(service: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    ports = service.get("ports", [])
    return [item for item in ports if isinstance(item, dict)] if isinstance(ports, list) else []


def validate_resolved_config(
    config: Mapping[str, Any], *, web_port: int, api_port: int, project: str | None = None
) -> None:
    if project is not None and config.get("name") != project:
        raise LifecycleError("resolved compose project does not match the proof project")
    services = config.get("services")
    if not isinstance(services, dict):
        raise LifecycleError("resolved compose config has no services")
    for name, service in services.items():
        if not isinstance(service, dict):
            raise LifecycleError(f"invalid service config: {name}")
        volumes = service.get("volumes", [])
        if isinstance(volumes, list):
            for volume in volumes:
                if isinstance(volume, dict) and volume.get("type") == "bind":
                    raise LifecycleError(f"host bind mount is forbidden: {name}")
                if isinstance(volume, dict) and ".axit-blobs" in str(volume.get("source", "")):
                    raise LifecycleError("workspace blob storage leaked into N4")
        if name not in {"web", "api"} and _published_ports(service):
            raise LifecycleError(f"unexpected published port: {name}")

    postgres = services.get("postgres", {})
    if not isinstance(postgres, dict) or _published_ports(postgres):
        raise LifecycleError("PostgreSQL must not publish a host port")
    expected = {"web": (web_port, 3000), "api": (api_port, 8000)}
    for name, (published, target) in expected.items():
        service = services.get(name)
        if not isinstance(service, dict):
            raise LifecycleError(f"missing {name} service")
        ports = _published_ports(service)
        if len(ports) != 1:
            raise LifecycleError(f"{name} must publish exactly one port")
        port = ports[0]
        if (
            port.get("host_ip") != "127.0.0.1"
            or int(port.get("published", -1)) != published
            or int(port.get("target", -1)) != target
        ):
            raise LifecycleError(f"{name} publish does not match selected loopback port")

    api = services["api"]
    environment = api.get("environment", {})
    expected_origin = f"http://127.0.0.1:{web_port}"
    if not isinstance(environment, dict) or environment.get("PUBLIC_HOST") != f"127.0.0.1:{web_port}":
        raise LifecycleError("API PUBLIC_HOST does not match isolated browser URL")
    if environment.get("PUBLIC_ORIGIN") != expected_origin:
        raise LifecycleError("API PUBLIC_ORIGIN does not match isolated browser URL")
    if environment.get("AXIT_BLOB_ROOT") != "/var/lib/axit/blobs":
        raise LifecycleError("API blob root is not disposable")
    tmpfs = api.get("tmpfs", [])
    if not isinstance(tmpfs, list) or not any(str(item).startswith("/var/lib/axit/blobs") for item in tmpfs):
        raise LifecycleError("API disposable blob tmpfs is missing")


def _json_output(result: subprocess.CompletedProcess[str], purpose: str) -> Any:
    if result.returncode != 0:
        raise LifecycleError(f"{purpose} failed: {result.stderr.strip()}")
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise LifecycleError(f"{purpose} returned invalid JSON") from exc


def snapshot_project(project: str, runner: CommandRunner = default_runner) -> dict[str, list[dict[str, Any]]]:
    resources: dict[str, list[dict[str, Any]]] = {"containers": [], "networks": [], "volumes": []}
    commands = {
        "containers": ["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={project}", "--format", "{{json .}}"],
        "networks": ["docker", "network", "ls", "--filter", f"label=com.docker.compose.project={project}", "--format", "{{json .}}"],
        "volumes": ["docker", "volume", "ls", "--filter", f"label=com.docker.compose.project={project}", "--format", "{{json .}}"],
    }
    for kind, argv in commands.items():
        result = runner(argv, None)
        if result.returncode != 0:
            raise LifecycleError(f"cannot snapshot {project} {kind}: {result.stderr.strip()}")
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            resource_id = row.get("ID") or row.get("Id") or row.get("Name")
            inspect_kind = "container" if kind == "containers" else kind[:-1]
            inspected = _json_output(runner(["docker", inspect_kind, "inspect", str(resource_id)], None), f"inspect {kind}")
            detail = inspected[0]
            labels = detail.get("Config", {}).get("Labels", {}) if kind == "containers" else detail.get("Labels", {})
            item: dict[str, Any] = {
                "id": str(detail.get("Id") or detail.get("ID") or detail.get("Name")),
                "labels": labels or {},
            }
            if kind == "containers":
                item["status"] = detail.get("State", {}).get("Status")
            resources[kind].append(item)
    for values in resources.values():
        values.sort(key=lambda value: value["id"])
    return resources


def assert_resource_ownership(
    manifest: Mapping[str, Any], current: Mapping[str, Any], *, expected_configs: Sequence[Path]
) -> None:
    expected_config_strings = [str(path) for path in expected_configs]
    if manifest.get("config_paths") != expected_config_strings:
        raise LifecycleError("manifest compose config paths changed")
    project = manifest.get("project")
    if not isinstance(project, str) or not project.startswith(PROJECT_PREFIX):
        raise LifecycleError("manifest project is not an owned N4 project")
    expected_resources = manifest.get("resources")
    if not isinstance(expected_resources, dict):
        raise LifecycleError("manifest resources are missing")
    for kind in ("containers", "networks", "volumes"):
        expected_rows = expected_resources.get(kind, [])
        current_rows = current.get(kind, [])
        if not isinstance(expected_rows, list) or not isinstance(current_rows, list):
            raise LifecycleError(f"invalid {kind} ownership data")
        if {row.get("id") for row in expected_rows} != {row.get("id") for row in current_rows}:
            raise LifecycleError(f"{kind} ID set mismatch")
        expected_by_id = {row.get("id"): row for row in expected_rows}
        for row in current_rows:
            labels = row.get("labels", {})
            if labels.get("com.docker.compose.project") != project:
                raise LifecycleError(f"wrong project label on {kind}")
            if kind == "containers" and not labels.get("com.docker.compose.service"):
                raise LifecycleError("container service label is missing")
            if kind == "containers" and labels.get(
                "com.docker.compose.service"
            ) not in EXPECTED_SERVICES:
                raise LifecycleError("container service label is not an expected N4 service")
            expected_labels = expected_by_id[row.get("id")].get("labels", {})
            if labels.get("com.docker.compose.project") != expected_labels.get(
                "com.docker.compose.project"
            ):
                raise LifecycleError(f"manifest project label mismatch on {kind}")
            if kind == "containers" and labels.get(
                "com.docker.compose.service"
            ) != expected_labels.get("com.docker.compose.service"):
                raise LifecycleError("manifest container service label mismatch")


def _has_resources(resources: Mapping[str, Any]) -> bool:
    return any(bool(resources.get(kind)) for kind in ("containers", "networks", "volumes"))


def assert_expected_services(resources: Mapping[str, Any]) -> None:
    containers = resources.get("containers", [])
    services = {
        row.get("labels", {}).get("com.docker.compose.service")
        for row in containers
        if isinstance(row, dict)
    }
    if services != EXPECTED_SERVICES:
        raise LifecycleError("owned container service set is incomplete")


def _contains_non_ascii(value: str) -> bool:
    return not value.isascii()


def create_subst_mapping(
    root: Path, recorder: SubstRecorder, runner: CommandRunner = default_runner
) -> dict[str, Any]:
    target = str(root.resolve()).rstrip("\\")
    for letter in reversed(string.ascii_uppercase[3:]):
        drive = f"{letter}:"
        if subst_mapping(drive, runner) is not None:
            continue
        recorder(
            {
                "drive": drive,
                "target": target,
                "created_by_run": False,
                "creation_pending": True,
            }
        )
        result = runner(["subst", drive, target], None)
        if result.returncode != 0:
            recorder(None)
            continue
        record = {"drive": drive, "target": target, "created_by_run": True}
        recorder(record)
        validate_subst_ownership(record, runner)
        return record
    raise LifecycleError("no unused subst drive is available")


def _phase0_equal(before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    if before != after:
        raise LifecycleError(f"{PROTECTED_PROJECT} changed during isolated lifecycle")


def subst_mapping(drive: str, runner: CommandRunner = default_runner) -> str | None:
    result = runner(["subst"], None)
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        match = _SUBST_ROW.fullmatch(line)
        if match is not None and match.group(1).casefold() == drive.casefold():
            return match.group(2).rstrip("\\").casefold()
    return None


def remove_owned_subst(subst: Mapping[str, Any], runner: CommandRunner = default_runner) -> None:
    validate_subst_ownership(subst, runner)
    drive = str(subst.get("drive", ""))
    result = runner(["subst", drive, "/D"], None)
    if result.returncode != 0:
        raise LifecycleError(f"subst removal failed: {result.stderr.strip()}")


def validate_subst_ownership(
    subst: Mapping[str, Any], runner: CommandRunner = default_runner
) -> None:
    drive = str(subst.get("drive", ""))
    target = str(subst.get("target", "")).rstrip("\\").casefold()
    if not subst.get("created_by_run") or subst_mapping(drive, runner) != target:
        raise LifecycleError("subst ownership mismatch")


class Lifecycle:
    def __init__(
        self,
        root: Path,
        manifest_path: Path,
        *,
        runner: CommandRunner = default_runner,
        port_selector: PortSelector | None = None,
    ) -> None:
        self.root = root.resolve()
        self.manifest_path = manifest_path.resolve()
        self.runner = runner
        self.port_selector = port_selector or default_port_selector
        self.base = (self.root / "docker-compose.yml").resolve()
        self.override = (self.root / "docker-compose.n4.yml").resolve()

    def _capture(self, project: str, attempts: int = 3) -> dict[str, list[dict[str, Any]]]:
        last_error: LifecycleError | None = None
        for _ in range(attempts):
            try:
                return snapshot_project(project, self.runner)
            except LifecycleError as exc:
                last_error = exc
        raise LifecycleError("resource capture retry exhausted") from last_error

    def _target_from_manifest(self, manifest: Mapping[str, Any]) -> ComposeTarget:
        source_paths = manifest.get("source_config_paths")
        if source_paths != [str(self.base), str(self.override)]:
            raise LifecycleError("manifest source config paths changed")
        subst = manifest.get("subst")
        if subst is None:
            expected = [str(self.base), str(self.override)]
        else:
            drive = str(subst.get("drive", ""))
            expected = [
                str(Path(f"{drive}\\docker-compose.yml")),
                str(Path(f"{drive}\\docker-compose.n4.yml")),
            ]
        if manifest.get("config_paths") != expected:
            raise LifecycleError("manifest effective config paths changed")
        return ComposeTarget(str(manifest.get("project", "")), Path(expected[0]), Path(expected[1]))

    def _finish_failed_start(self, manifest: dict[str, Any], failure: str) -> NoReturn:
        manifest.update(status="start_failed", start_failure=failure)
        manifest["status_history"].append("start_failed")
        atomic_write_json(self.manifest_path, manifest)
        try:
            self.stop()
        except LifecycleError as cleanup_error:
            raise LifecycleError(
                f"{failure}; partial-start cleanup blocked: {cleanup_error}"
            ) from cleanup_error
        raise LifecycleError(f"{failure}; partial-start resources safely removed")

    def start(self, web_port: int = 0, api_port: int = 0) -> dict[str, Any]:
        archive_completed_manifest(self.manifest_path)
        project = new_project_name()
        target = ComposeTarget(project, self.base, self.override)
        selected_web = self.port_selector(web_port, None)
        selected_api = self.port_selector(api_port, {selected_web})
        if selected_web == selected_api:
            raise LifecycleError("web and API ports must be distinct")
        env = compose_environment(selected_web, selected_api)
        if any(snapshot_project(project, self.runner).values()):
            raise LifecycleError("unique proof project is unexpectedly nonempty")
        phase0_before = snapshot_project(PROTECTED_PROJECT, self.runner)
        manifest: dict[str, Any] = {
            "schema": MANIFEST_SCHEMA,
            "version": MANIFEST_VERSION,
            "status": "starting",
            "status_history": ["starting"],
            "project": project,
            "source_config_paths": [str(self.base), str(self.override)],
            "config_paths": [str(self.base), str(self.override)],
            "started_at": utc_now(),
            "ports": {"web": selected_web, "api": selected_api, "postgres": None},
            "web_url": f"http://127.0.0.1:{selected_web}",
            "public_host": f"127.0.0.1:{selected_web}",
            "public_origin": f"http://127.0.0.1:{selected_web}",
            "subst": None,
            "resources": {"containers": [], "networks": [], "volumes": []},
            "phase0_before": phase0_before,
        }

        def record_subst(record: Mapping[str, Any] | None) -> None:
            manifest["subst"] = dict(record) if record is not None else None
            drive = str(record["drive"]) if record is not None else ""
            manifest["config_paths"] = (
                [
                    str(Path(f"{drive}\\docker-compose.yml")),
                    str(Path(f"{drive}\\docker-compose.n4.yml")),
                ]
                if record is not None
                else [str(self.base), str(self.override)]
            )
            atomic_write_json(self.manifest_path, manifest)

        subst: dict[str, Any] | None = None
        config_result = self.runner(target.argv("config", "--format", "json"), env)
        if (
            config_result.returncode != 0
            and _is_non_ascii_buildkit_grpc_failure(config_result, self.root)
        ):
            try:
                subst = create_subst_mapping(self.root, record_subst, self.runner)
            except LifecycleError:
                manifest.update(
                    status="start_failed",
                    start_failure="subst_validation_failed",
                    cleanup_status="subst_cleanup_blocked",
                    cleanup_error_code="subst_mapping_query_failed",
                )
                manifest["status_history"].append("start_failed")
                atomic_write_json(self.manifest_path, manifest)
                raise
            target = ComposeTarget(
                project,
                Path(f"{subst['drive']}\\docker-compose.yml"),
                Path(f"{subst['drive']}\\docker-compose.n4.yml"),
            )
            config_result = self.runner(target.argv("config", "--format", "json"), env)
        try:
            resolved = _json_output(config_result, "compose config")
            validate_resolved_config(
                resolved, web_port=selected_web, api_port=selected_api, project=project
            )
        except LifecycleError:
            if subst is not None:
                try:
                    remove_owned_subst(subst, self.runner)
                except LifecycleError:
                    manifest.update(
                        status="start_failed",
                        start_failure="compose_config_validation_failed",
                        cleanup_status="subst_cleanup_blocked",
                        cleanup_error_code="subst_ownership_validation_failed",
                    )
                    manifest["status_history"].append("start_failed")
                    atomic_write_json(self.manifest_path, manifest)
                    raise
                record_subst(None)
            raise
        manifest["subst"] = subst
        manifest["config_paths"] = [str(target.base_config), str(target.n4_config)]
        atomic_write_json(self.manifest_path, manifest)
        up = self.runner(target.argv("up", "--build", "-d", "--wait"), env)
        try:
            resources = self._capture(project)
        except LifecycleError:
            manifest.update(
                status="start_failed",
                start_failure="resource_capture_failed",
                cleanup_status="capture_retry_exhausted",
            )
            manifest["status_history"].append("start_failed")
            atomic_write_json(self.manifest_path, manifest)
            raise
        manifest["resources"] = resources
        if (
            subst is None
            and not _has_resources(resources)
            and _is_non_ascii_buildkit_grpc_failure(up, self.root)
        ):
            manifest["start_diagnostic"] = compose_failure_diagnostic(
                up, project=project, root=self.root
            )
            try:
                _phase0_equal(
                    phase0_before, snapshot_project(PROTECTED_PROJECT, self.runner)
                )
                subst = create_subst_mapping(self.root, record_subst, self.runner)
                target = ComposeTarget(
                    project,
                    Path(f"{subst['drive']}\\docker-compose.yml"),
                    Path(f"{subst['drive']}\\docker-compose.n4.yml"),
                )
                retry_config = self.runner(target.argv("config", "--format", "json"), env)
                if retry_config.returncode != 0:
                    manifest["subst_retry_diagnostic"] = compose_failure_diagnostic(
                        retry_config, project=project, root=self.root
                    )
                retry_resolved = _json_output(retry_config, "compose config")
                validate_resolved_config(
                    retry_resolved,
                    web_port=selected_web,
                    api_port=selected_api,
                    project=project,
                )
            except LifecycleError:
                manifest["resources"] = resources
                self._finish_failed_start(manifest, "subst_retry_preflight_failed")
            manifest["subst_retry"] = "up_non_ascii_buildkit_grpc_failure"
            atomic_write_json(self.manifest_path, manifest)
            up = self.runner(target.argv("up", "--build", "-d", "--wait"), env)
            try:
                resources = self._capture(project)
            except LifecycleError:
                manifest.update(
                    status="start_failed",
                    start_failure="resource_capture_failed",
                    cleanup_status="capture_retry_exhausted",
                )
                manifest["status_history"].append("start_failed")
                atomic_write_json(self.manifest_path, manifest)
                raise
            manifest["resources"] = resources
        try:
            _phase0_equal(phase0_before, snapshot_project(PROTECTED_PROJECT, self.runner))
        except LifecycleError:
            manifest.update(
                status="start_failed",
                start_failure="phase0_invariant_failed",
                cleanup_status="ownership_mismatch",
                cleanup_error_code="protected_project_changed",
            )
            manifest["status_history"].append("start_failed")
            atomic_write_json(self.manifest_path, manifest)
            raise
        if up.returncode != 0:
            manifest["start_diagnostic"] = compose_failure_diagnostic(
                up, project=project, root=self.root
            )
            failing_services = manifest["start_diagnostic"]["failing_services"]
            if failing_services:
                service_logs = self.runner(
                    target.argv(
                        "logs",
                        "--no-color",
                        "--tail",
                        str(MAX_SERVICE_LOG_LINES),
                        *failing_services,
                    ),
                    env,
                )
                manifest["service_log_diagnostic"] = compose_failure_diagnostic(
                    service_logs, project=project, root=self.root
                )
            self._finish_failed_start(manifest, "compose_health_gate_failed")
        try:
            assert_expected_services(resources)
        except LifecycleError:
            self._finish_failed_start(manifest, "expected_services_incomplete")
        manifest["status"] = "running"
        manifest["status_history"].append("running")
        atomic_write_json(self.manifest_path, manifest)
        return manifest

    def _validated_running_target(
        self, purpose: str
    ) -> tuple[dict[str, Any], ComposeTarget]:
        manifest = read_manifest(self.manifest_path)
        validate_manifest_identity(manifest)
        if manifest.get("status") != "running":
            raise LifecycleError(f"{purpose} requires a running manifest")
        target = self._target_from_manifest(manifest)
        current = snapshot_project(str(manifest.get("project")), self.runner)
        assert_resource_ownership(
            manifest,
            current,
            expected_configs=(target.base_config, target.n4_config),
        )
        _phase0_equal(manifest.get("phase0_before", {}), snapshot_project(PROTECTED_PROJECT, self.runner))
        return manifest, target

    def verify(self) -> dict[str, Any]:
        manifest, _ = self._validated_running_target("Verify")
        env = {
            **os.environ,
            "AXIT_N4_BASE_URL": str(manifest["web_url"]),
            "AXIT_N4_ROOT": str(self.root),
            "AXIT_N4_MANIFEST": str(self.manifest_path),
            "AXIT_N4_PROBE_UV": resolve_command("uv"),
            "AXIT_N4_PROBE_SCRIPT": str(Path(__file__).resolve()),
        }
        argv = [
            resolve_command("pnpm"), "--dir", "spikes/document-ingestion/viewer", "exec", "playwright", "test",
            "--config", "axit-app-e2e/playwright.config.mjs",
        ]
        result = self.runner(argv, env)
        if result.returncode != 0:
            raise LifecycleError("N4 browser verification failed")
        return manifest

    def probe_stale(
        self, session_id: str, recipient_ids: Sequence[str]
    ) -> dict[str, object]:
        canonical_session = canonical_uuid(session_id, "session id")
        canonical_recipients = [
            canonical_uuid(value, "recipient id") for value in recipient_ids
        ]
        if len(canonical_recipients) != 2 or len(set(canonical_recipients)) != 2:
            raise LifecycleError("stale probe requires two distinct recipients")
        _, target = self._validated_running_target("Probe-stale")
        argv = target.argv(
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "app.n4_stale_probe",
            "--session-id",
            canonical_session,
            "--recipient-id",
            canonical_recipients[0],
            "--recipient-id",
            canonical_recipients[1],
        )
        result = self.runner(argv, None)
        if result.returncode != 0:
            raise LifecycleError("stale probe failed")
        if len(result.stdout) > MAX_STALE_PROBE_OUTPUT_CHARS:
            raise LifecycleError("stale probe returned an unsupported result")
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise LifecycleError("stale probe returned invalid JSON") from exc
        return validate_stale_probe_output(output)

    def stop(self) -> dict[str, Any]:
        manifest = read_manifest(self.manifest_path)
        validate_manifest_identity(manifest)
        project = str(manifest.get("project", ""))
        try:
            target = self._target_from_manifest(manifest)
        except LifecycleError:
            manifest["cleanup_status"] = "ownership_mismatch"
            manifest["cleanup_error_code"] = "config_ownership_validation_failed"
            atomic_write_json(self.manifest_path, manifest)
            raise
        cleanup_pending = manifest.get("status") == "cleanup_pending"
        if cleanup_pending:
            current = manifest.get("removed_resources", {})
        else:
            current = snapshot_project(project, self.runner)
            try:
                if (
                    manifest.get("status") == "start_failed"
                    and manifest.get("cleanup_status") == "capture_retry_exhausted"
                ):
                    recovered = dict(manifest)
                    recovered["resources"] = current
                    assert_resource_ownership(
                        recovered,
                        current,
                        expected_configs=(target.base_config, target.n4_config),
                    )
                    _phase0_equal(
                        manifest.get("phase0_before", {}),
                        snapshot_project(PROTECTED_PROJECT, self.runner),
                    )
                    manifest["resources"] = current
                    manifest["cleanup_status"] = "recovery_captured"
                    atomic_write_json(self.manifest_path, manifest)
                assert_resource_ownership(
                    manifest,
                    current,
                    expected_configs=(target.base_config, target.n4_config),
                )
                _phase0_equal(
                    manifest.get("phase0_before", {}),
                    snapshot_project(PROTECTED_PROJECT, self.runner),
                )
                if manifest.get("subst") is not None:
                    validate_subst_ownership(manifest["subst"], self.runner)
            except LifecycleError:
                manifest["cleanup_status"] = "ownership_mismatch"
                manifest["cleanup_error_code"] = "ownership_validation_failed"
                atomic_write_json(self.manifest_path, manifest)
                raise
        argv = target.argv("down", "-v", "--remove-orphans")
        if not cleanup_pending and _has_resources(current):
            result = self.runner(
                argv,
                compose_environment(
                    int(manifest["ports"]["web"]), int(manifest["ports"]["api"])
                ),
            )
            if result.returncode != 0:
                manifest["cleanup_status"] = "compose_down_failed"
                atomic_write_json(self.manifest_path, manifest)
                raise LifecycleError("compose down failed")
            remaining = self._capture(project)
            if _has_resources(remaining):
                manifest["cleanup_status"] = "resources_remain"
                atomic_write_json(self.manifest_path, manifest)
                raise LifecycleError("owned resources remain after compose down")
            manifest["status"] = "cleanup_pending"
            manifest["cleanup_status"] = "compose_down_succeeded"
            manifest["removed_resources"] = current
            manifest["teardown_argv"] = argv
            atomic_write_json(self.manifest_path, manifest)
        else:
            remaining = {"containers": [], "networks": [], "volumes": []}
            if not cleanup_pending:
                manifest["status"] = "cleanup_pending"
                manifest["cleanup_status"] = "compose_down_succeeded"
                manifest["removed_resources"] = current
                manifest["teardown_argv"] = None
                atomic_write_json(self.manifest_path, manifest)
        if manifest.get("subst") is not None:
            try:
                removed_subst = manifest["subst"]
                remove_owned_subst(removed_subst, self.runner)
            except LifecycleError:
                manifest["cleanup_status"] = "subst_cleanup_blocked"
                manifest["cleanup_error_code"] = "subst_ownership_validation_failed"
                atomic_write_json(self.manifest_path, manifest)
                raise
            manifest["removed_subst"] = removed_subst
            manifest["subst"] = None
            atomic_write_json(self.manifest_path, manifest)
        try:
            _phase0_equal(
                manifest.get("phase0_before", {}),
                snapshot_project(PROTECTED_PROJECT, self.runner),
            )
        except LifecycleError:
            manifest["cleanup_status"] = "phase0_invariant_failed"
            manifest["cleanup_error_code"] = "protected_project_changed"
            atomic_write_json(self.manifest_path, manifest)
            raise
        manifest["status"] = "stopped"
        manifest.setdefault("status_history", []).append("stopped")
        manifest["cleanup_status"] = "stopped"
        manifest["stopped_at"] = utc_now()
        atomic_write_json(self.manifest_path, manifest)
        return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "verify", "probe-stale", "stop"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--web-port", type=int, default=0)
    parser.add_argument("--api-port", type=int, default=0)
    parser.add_argument("--session-id")
    parser.add_argument("--recipient-id", action="append", default=[])
    return parser


def _abort(message: str) -> NoReturn:
    print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(2)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    lifecycle = Lifecycle(args.root, args.manifest)
    try:
        if args.action == "start":
            manifest = lifecycle.start(args.web_port, args.api_port)
        elif args.action == "verify":
            manifest = lifecycle.verify()
        elif args.action == "probe-stale":
            if args.session_id is None:
                raise LifecycleError("probe-stale requires a session id")
            manifest = lifecycle.probe_stale(args.session_id, args.recipient_id)
        else:
            manifest = lifecycle.stop()
    except LifecycleError as exc:
        _abort(str(exc))
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
