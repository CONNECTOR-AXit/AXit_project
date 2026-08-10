"""Pure, mocked contracts for the isolated N4 Compose lifecycle."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from scripts import n4_compose_lifecycle as n4


def completed(
    argv: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def resource(resource_id: str, project: str, service: str | None = None) -> dict[str, Any]:
    labels = {"com.docker.compose.project": project}
    if service is not None:
        labels["com.docker.compose.service"] = service
    return {"id": resource_id, "labels": labels}


def owned_resources(project: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "containers": [
            resource(f"container-{service}", project, service)
            for service in sorted(n4.EXPECTED_SERVICES)
        ],
        "networks": [resource("network-1", project)],
        "volumes": [],
    }


def resolved_config(
    web_port: int, api_port: int, project: str = "axit-n4-20260807t000000z-123-proofabc"
) -> dict[str, Any]:
    return {
        "name": project,
        "services": {
            "postgres": {"ports": [], "volumes": []},
            "migrate": {"volumes": []},
            "orchestrator": {"volumes": []},
            "api": {
                "ports": [
                    {"host_ip": "127.0.0.1", "published": api_port, "target": 8000}
                ],
                "volumes": [],
                "tmpfs": [
                    "/tmp:size=256m,mode=1777",
                    "/var/lib/axit/blobs:size=256m,mode=0700",
                ],
                "environment": {
                    "PUBLIC_HOST": f"127.0.0.1:{web_port}",
                    "PUBLIC_ORIGIN": f"http://127.0.0.1:{web_port}",
                    "AXIT_BLOB_ROOT": "/var/lib/axit/blobs",
                },
            },
            "web": {
                "ports": [
                    {"host_ip": "127.0.0.1", "published": web_port, "target": 3000}
                ],
                "volumes": [],
            },
        }
    }


def manifest(root: Path, project: str = "axit-n4-20260807t000000z-123-proofabc") -> dict[str, Any]:
    return {
        "schema": n4.MANIFEST_SCHEMA,
        "version": n4.MANIFEST_VERSION,
        "status": "running",
        "status_history": ["starting", "running"],
        "project": project,
        "config_paths": [
            str((root / "docker-compose.yml").resolve()),
            str((root / "docker-compose.n4.yml").resolve()),
        ],
        "source_config_paths": [
            str((root / "docker-compose.yml").resolve()),
            str((root / "docker-compose.n4.yml").resolve()),
        ],
        "ports": {"web": 41001, "api": 41002, "postgres": None},
        "web_url": "http://127.0.0.1:41001",
        "phase0_before": {"containers": [], "networks": [], "volumes": []},
        "subst": None,
        "resources": owned_resources(project),
    }


def test_unique_project_and_every_compose_command_has_absolute_configs(tmp_path: Path) -> None:
    first = n4.new_project_name(now=datetime(2026, 8, 7, tzinfo=UTC), pid=10)
    second = n4.new_project_name(now=datetime(2026, 8, 7, tzinfo=UTC), pid=10)
    assert first != second
    assert first.startswith("axit-n4-20260807t000000z-10-")
    target = n4.ComposeTarget(
        first, (tmp_path / "docker-compose.yml").resolve(), (tmp_path / "n4.yml").resolve()
    )
    argv = target.argv("config", "--format", "json")
    assert argv[:4] == ["docker", "compose", "-p", first]
    assert argv.count("-f") == 2
    assert Path(argv[5]).is_absolute() and Path(argv[7]).is_absolute()
    with pytest.raises(n4.LifecycleError):
        n4.ComposeTarget(first, Path("relative.yml"), (tmp_path / "n4.yml").resolve())


def test_dynamic_distinct_loopback_ports_and_collision_rejection() -> None:
    web = n4.select_loopback_port(0)
    api = n4.select_loopback_port(0, excluded={web})
    assert web > 0 and api > 0 and web != api
    with pytest.raises(n4.LifecycleError, match="collision"):
        n4.select_loopback_port(web, excluded={web})
    config = resolved_config(web, api)
    assert config["services"]["postgres"]["ports"] == []
    n4.validate_resolved_config(config, web_port=web, api_port=api)


def test_default_runner_uses_windows_locale_only_for_subst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encodings: list[str] = []

    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        encodings.append(kwargs["encoding"])
        return completed(list(args[0]))

    monkeypatch.setattr(n4.locale, "getpreferredencoding", lambda do_setlocale: "cp949")
    monkeypatch.setattr(n4.subprocess, "run", run)

    n4.default_runner(["subst"])
    n4.default_runner(["docker", "compose", "config"])

    assert encodings == ["cp949", "utf-8"]


def test_resolve_command_uses_windows_cmd_shim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(n4.shutil, "which", lambda name: r"C:\npm\pnpm.CMD")

    assert n4.resolve_command("pnpm") == r"C:\npm\pnpm.CMD"


def test_resolve_command_fails_closed_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(n4.shutil, "which", lambda name: None)

    with pytest.raises(n4.LifecycleError, match="pnpm executable"):
        n4.resolve_command("pnpm")


def test_public_host_origin_must_exactly_match_browser_url() -> None:
    config = resolved_config(41001, 41002)
    n4.validate_resolved_config(config, web_port=41001, api_port=41002)
    config["services"]["api"]["environment"]["PUBLIC_ORIGIN"] = "http://localhost:41001"
    with pytest.raises(n4.LifecycleError, match="PUBLIC_ORIGIN"):
        n4.validate_resolved_config(config, web_port=41001, api_port=41002)


def test_disposable_blob_tmpfs_and_no_bind_mounts() -> None:
    config = resolved_config(41001, 41002)
    n4.validate_resolved_config(config, web_port=41001, api_port=41002)
    config["services"]["api"]["volumes"] = [
        {"type": "bind", "source": "C:/repo/.axit-blobs", "target": "/var/lib/axit/blobs"}
    ]
    with pytest.raises(n4.LifecycleError, match="bind mount"):
        n4.validate_resolved_config(config, web_port=41001, api_port=41002)


def test_manifest_atomic_archive_and_state_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "compose-run.json"
    replacements: list[tuple[Path, Path]] = []
    real_replace = n4.os.replace

    def tracking_replace(source: Path, destination: Path) -> None:
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(n4.os, "replace", tracking_replace)
    n4.atomic_write_json(path, {"status": "starting", "status_history": ["starting"]})
    assert n4.read_manifest(path)["status"] == "starting"
    assert replacements and replacements[0][0] != path
    n4.atomic_write_json(path, {"status": "stopped", "status_history": ["starting", "start_failed", "stopped"]})
    archive = n4.archive_completed_manifest(path)
    assert archive is not None and archive.exists() and not path.exists()
    n4.atomic_write_json(path, {"status": "running"})
    with pytest.raises(n4.LifecycleError, match="active"):
        n4.archive_completed_manifest(path)


def test_start_writes_running_manifest_and_uses_only_targeted_compose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    project = "axit-n4-20260807t000000z-123-fixedabc"
    monkeypatch.setattr(n4, "new_project_name", lambda: project)
    snapshots = iter(
        [
            {"containers": [], "networks": [], "volumes": []},
            {"containers": [], "networks": [], "volumes": []},
            owned_resources(project),
            {"containers": [], "networks": [], "volumes": []},
        ]
    )
    monkeypatch.setattr(n4, "snapshot_project", lambda selected, runner: next(snapshots))
    calls: list[list[str]] = []
    environments: list[Any] = []

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        call = list(argv)
        calls.append(call)
        environments.append(env)
        if "config" in call:
            return completed(call, stdout=json.dumps(resolved_config(41001, 41002, project)))
        return completed(call)

    ports = iter((41001, 41002))
    lifecycle = n4.Lifecycle(
        tmp_path,
        path,
        runner=runner,
        port_selector=lambda requested, excluded: next(ports),
    )
    running = lifecycle.start()
    assert running["status_history"] == ["starting", "running"]
    compose_calls = [call for call in calls if call[:2] == ["docker", "compose"]]
    assert len(compose_calls) == 2
    for call in compose_calls:
        assert call[2:4] == ["-p", project]
        assert Path(call[5]).is_absolute() and Path(call[7]).is_absolute()
        assert n4.PROTECTED_PROJECT not in call
    target = n4.ComposeTarget(
        project,
        (tmp_path / "docker-compose.yml").resolve(),
        (tmp_path / "docker-compose.n4.yml").resolve(),
    )
    assert compose_calls == [
        target.argv("config", "--format", "json"),
        target.argv("up", "--build", "-d", "--wait"),
    ]
    for environment in environments:
        if environment is None:
            continue
        assert environment["N4_WEB_PORT"] == "41001"
        assert environment["N4_API_PORT"] == "41002"
        assert environment["N4_PUBLIC_HOST"] == "127.0.0.1:41001"
        assert environment["N4_PUBLIC_ORIGIN"] == "http://127.0.0.1:41001"
    assert running["schema"] == n4.MANIFEST_SCHEMA
    assert running["version"] == n4.MANIFEST_VERSION


def test_failed_partial_start_is_captured_cleaned_and_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    project = "axit-n4-20260807t000000z-123-failabcd"
    monkeypatch.setattr(n4, "new_project_name", lambda: project)
    empty = {"containers": [], "networks": [], "volumes": []}
    snapshots = iter(
        [empty, empty, owned_resources(project), empty, owned_resources(project), empty, empty, empty]
    )
    monkeypatch.setattr(n4, "snapshot_project", lambda selected, runner: next(snapshots))
    calls: list[list[str]] = []

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        call = list(argv)
        calls.append(call)
        if "config" in call:
            return completed(call, stdout=json.dumps(resolved_config(41001, 41002, project)))
        if "up" in call:
            return completed(
                call,
                returncode=1,
                stdout="web: build failed: TOKEN=stdout-secret\n",
                stderr=(
                    "dependency failed to start: container "
                    f"{project}-api-1 is unhealthy; password=stderr-secret\n"
                ),
            )
        if "logs" in call:
            return completed(
                call,
                stdout="api | migration failed: DB_PASSWORD=log-secret\n",
            )
        return completed(call)

    ports = iter((41001, 41002))
    lifecycle = n4.Lifecycle(
        tmp_path,
        path,
        runner=runner,
        port_selector=lambda requested, excluded: next(ports),
    )
    with pytest.raises(n4.LifecycleError, match="safely removed"):
        lifecycle.start()
    stopped = n4.read_manifest(path)
    assert stopped["status"] == "stopped"
    assert stopped["status_history"] == ["starting", "start_failed", "stopped"]
    assert stopped["start_failure"] == "compose_health_gate_failed"
    assert stopped["start_diagnostic"] == {
        "returncode": 1,
        "failing_services": ["api", "web"],
        "output_excerpt": [
            "web: build failed: TOKEN=[redacted]",
            (
                "dependency failed to start: container "
                "<project>-api-1 is unhealthy; password=[redacted]"
            ),
        ],
        "truncated": False,
    }
    assert stopped["service_log_diagnostic"]["output_excerpt"] == [
        "api | migration failed: DB_PASSWORD=[redacted]"
    ]
    target = n4.ComposeTarget(
        project,
        (tmp_path / "docker-compose.yml").resolve(),
        (tmp_path / "docker-compose.n4.yml").resolve(),
    )
    assert target.argv(
        "logs", "--no-color", "--tail", str(n4.MAX_SERVICE_LOG_LINES), "api", "web"
    ) in calls
    assert sum("down" in call for call in calls) == 1
    persisted = path.read_text(encoding="utf-8")
    assert "stdout-secret" not in persisted
    assert "stderr-secret" not in persisted
    assert "log-secret" not in persisted
    assert project not in json.dumps(stopped["start_diagnostic"])


def test_compose_failure_diagnostic_is_bounded_and_discards_noise() -> None:
    project = "axit-n4-20260807t000000z-123-diagabcd"
    noisy = "\n".join(
        ["ordinary build output"] * 20
        + ["api | sqlalchemy error: decisive failure"]
        + [f"api | traceback context line {index}" for index in range(20)]
    )
    result = completed(["docker", "compose"], returncode=17, stderr=noisy)

    diagnostic = n4.compose_failure_diagnostic(result, project=project, root=Path("C:/repo"))

    assert diagnostic["returncode"] == 17
    assert diagnostic["failing_services"] == ["api"]
    assert diagnostic["truncated"] is True
    assert len(diagnostic["output_excerpt"]) == n4.MAX_DIAGNOSTIC_LINES
    assert all(len(line) <= n4.MAX_DIAGNOSTIC_LINE_CHARS for line in diagnostic["output_excerpt"])
    assert "api | sqlalchemy error: decisive failure" in diagnostic["output_excerpt"]
    assert "ordinary build output" not in json.dumps(diagnostic)


def test_up_failure_without_identified_service_does_not_request_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    project = "axit-n4-20260807t000000z-123-nologsab"
    monkeypatch.setattr(n4, "new_project_name", lambda: project)
    empty = {"containers": [], "networks": [], "volumes": []}
    owned = owned_resources(project)
    snapshots = iter((empty, empty, owned, empty, owned, empty, empty, empty))
    monkeypatch.setattr(n4, "snapshot_project", lambda selected, runner: next(snapshots))
    calls: list[list[str]] = []

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        call = list(argv)
        calls.append(call)
        if "config" in call:
            return completed(call, stdout=json.dumps(resolved_config(41001, 41002, project)))
        if "up" in call:
            return completed(call, returncode=1, stderr="operation failed")
        return completed(call)

    ports = iter((41001, 41002))
    with pytest.raises(n4.LifecycleError, match="safely removed"):
        n4.Lifecycle(
            tmp_path,
            path,
            runner=runner,
            port_selector=lambda requested, excluded: next(ports),
        ).start()

    assert not any("logs" in call for call in calls)


def test_post_up_capture_failure_retries_then_runs_without_stranding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    project = "axit-n4-20260807t000000z-123-retryabc"
    monkeypatch.setattr(n4, "new_project_name", lambda: project)
    calls = 0
    empty = {"containers": [], "networks": [], "volumes": []}

    def snapshot(selected: str, runner: Any) -> dict[str, list[dict[str, Any]]]:
        nonlocal calls
        calls += 1
        if calls in {1, 2, 5}:
            return empty
        if calls == 3:
            raise n4.LifecycleError("injected transient inspect failure")
        return owned_resources(project)

    monkeypatch.setattr(n4, "snapshot_project", snapshot)

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        call = list(argv)
        if "config" in call:
            return completed(call, stdout=json.dumps(resolved_config(41001, 41002, project)))
        return completed(call)

    ports = iter((41001, 41002))
    running = n4.Lifecycle(
        tmp_path,
        path,
        runner=runner,
        port_selector=lambda requested, excluded: next(ports),
    ).start()
    assert running["status"] == "running"
    assert running["resources"] == owned_resources(project)
    assert calls == 5


def test_non_ascii_buildkit_grpc_failure_retries_once_via_owned_subst(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    project = "axit-n4-20260807t000000z-123-upgrpcab"
    monkeypatch.setattr(n4, "new_project_name", lambda: project)
    monkeypatch.setattr(n4, "_contains_non_ascii", lambda value: True)
    empty = {"containers": [], "networks": [], "volumes": []}
    snapshots = iter((empty, empty, empty, empty, owned_resources(project), empty))
    monkeypatch.setattr(n4, "snapshot_project", lambda selected, runner: next(snapshots))
    mapped = False
    compose_configs = 0
    compose_ups = 0

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        nonlocal mapped, compose_configs, compose_ups
        call = list(argv)
        if call[:1] == ["subst"]:
            if len(call) == 3:
                mapped = True
                return completed(call)
            return completed(
                call,
                stdout=f"Z:\\: => {tmp_path}\\\n" if mapped else "",
                returncode=0 if mapped else 1,
            )
        if "config" in call:
            compose_configs += 1
            return completed(call, stdout=json.dumps(resolved_config(41001, 41002, project)))
        if "up" in call:
            compose_ups += 1
            if compose_ups == 1:
                return completed(
                    call,
                    returncode=1,
                    stderr=(
                        "failed to dial gRPC: header key "
                        '"x-docker-expose-session-sharedkey" contains value with '
                        "non-printable ASCII characters"
                    ),
                )
        return completed(call)

    ports = iter((41001, 41002))
    running = n4.Lifecycle(
        tmp_path,
        path,
        runner=runner,
        port_selector=lambda requested, excluded: next(ports),
    ).start()

    assert compose_configs == 2
    assert compose_ups == 2
    assert running["status"] == "running"
    assert running["subst_retry"] == "up_non_ascii_buildkit_grpc_failure"
    assert running["subst"] == {
        "drive": "Z:",
        "target": str(tmp_path.resolve()).rstrip("\\"),
        "created_by_run": True,
    }
    assert running["config_paths"] == [
        "Z:\\docker-compose.yml",
        "Z:\\docker-compose.n4.yml",
    ]


def test_non_ascii_grpc_failure_with_owned_resources_does_not_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    project = "axit-n4-20260807t000000z-123-noretrya"
    monkeypatch.setattr(n4, "new_project_name", lambda: project)
    monkeypatch.setattr(n4, "_contains_non_ascii", lambda value: True)
    empty = {"containers": [], "networks": [], "volumes": []}
    owned = owned_resources(project)
    snapshots = iter((empty, empty, owned, empty, owned, empty, empty, empty))
    monkeypatch.setattr(n4, "snapshot_project", lambda selected, runner: next(snapshots))
    calls: list[list[str]] = []

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        call = list(argv)
        calls.append(call)
        if "config" in call:
            return completed(call, stdout=json.dumps(resolved_config(41001, 41002, project)))
        if "up" in call:
            return completed(
                call,
                returncode=1,
                stderr=(
                    "failed to dial gRPC: x-docker-expose-session-sharedkey contains "
                    "non-printable ASCII characters"
                ),
            )
        return completed(call)

    ports = iter((41001, 41002))
    with pytest.raises(n4.LifecycleError, match="safely removed"):
        n4.Lifecycle(
            tmp_path,
            path,
            runner=runner,
            port_selector=lambda requested, excluded: next(ports),
        ).start()

    assert sum("up" in call for call in calls) == 1
    assert not any(call[:1] == ["subst"] for call in calls)
    assert n4.read_manifest(path)["status"] == "stopped"


def test_subst_retry_config_failure_is_sanitized_and_cleans_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    project = "axit-n4-20260807t000000z-123-retrycfg"
    monkeypatch.setattr(n4, "new_project_name", lambda: project)
    monkeypatch.setattr(n4, "_contains_non_ascii", lambda value: True)
    empty = {"containers": [], "networks": [], "volumes": []}
    snapshots = iter((empty, empty, empty, empty, empty, empty, empty))
    monkeypatch.setattr(n4, "snapshot_project", lambda selected, runner: next(snapshots))
    mapped = False
    configs = 0

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        nonlocal mapped, configs
        call = list(argv)
        if call[:1] == ["subst"]:
            if call[-1:] == ["/D"]:
                mapped = False
                return completed(call)
            if len(call) == 3:
                mapped = True
                return completed(call)
            return completed(
                call,
                stdout=f"Z:\\: => {tmp_path}\\\n" if mapped else "",
            )
        if "config" in call:
            configs += 1
            if configs == 1:
                return completed(call, stdout=json.dumps(resolved_config(41001, 41002, project)))
            return completed(
                call,
                returncode=1,
                stderr="web config failed: API_TOKEN=retry-secret",
            )
        if "up" in call:
            return completed(
                call,
                returncode=1,
                stderr=(
                    "failed to dial gRPC: x-docker-expose-session-sharedkey contains "
                    "non-printable ASCII characters"
                ),
            )
        return completed(call)

    ports = iter((41001, 41002))
    with pytest.raises(n4.LifecycleError, match="safely removed"):
        n4.Lifecycle(
            tmp_path,
            path,
            runner=runner,
            port_selector=lambda requested, excluded: next(ports),
        ).start()

    stopped = n4.read_manifest(path)
    assert stopped["status"] == "stopped"
    assert stopped["start_failure"] == "subst_retry_preflight_failed"
    assert stopped["subst"] is None
    assert stopped["subst_retry_diagnostic"]["output_excerpt"] == [
        "web config failed: API_TOKEN=[redacted]"
    ]
    assert "retry-secret" not in path.read_text(encoding="utf-8")


def test_korean_path_grpc_failure_creates_owned_subst_and_effective_configs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    project = "axit-n4-20260807t000000z-123-substabc"
    monkeypatch.setattr(n4, "new_project_name", lambda: project)
    monkeypatch.setattr(n4, "_contains_non_ascii", lambda value: True)
    empty = {"containers": [], "networks": [], "volumes": []}
    snapshots = iter((empty, empty, owned_resources(project), empty))
    monkeypatch.setattr(n4, "snapshot_project", lambda selected, runner: next(snapshots))
    mapped = False
    compose_configs = 0

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        nonlocal mapped, compose_configs
        call = list(argv)
        if call[:1] == ["subst"]:
            if len(call) == 3:
                mapped = True
                return completed(call)
            return completed(
                call,
                stdout=f"Z:\\: => {tmp_path}\\\n" if mapped else "",
                returncode=0 if mapped else 1,
            )
        if "config" in call:
            compose_configs += 1
            if compose_configs == 1:
                return completed(
                    call,
                    returncode=1,
                    stderr=(
                        "failed to dial gRPC: header key "
                        '"x-docker-expose-session-sharedkey" contains value with '
                        "non-printable ASCII characters"
                    ),
                )
            return completed(call, stdout=json.dumps(resolved_config(41001, 41002, project)))
        return completed(call)

    ports = iter((41001, 41002))
    running = n4.Lifecycle(
        tmp_path,
        path,
        runner=runner,
        port_selector=lambda requested, excluded: next(ports),
    ).start()
    assert running["subst"] == {
        "drive": "Z:",
        "target": str(tmp_path.resolve()).rstrip("\\"),
        "created_by_run": True,
    }
    assert running["source_config_paths"] == [
        str((tmp_path / "docker-compose.yml").resolve()),
        str((tmp_path / "docker-compose.n4.yml").resolve()),
    ]
    assert running["config_paths"] == ["Z:\\docker-compose.yml", "Z:\\docker-compose.n4.yml"]
    assert compose_configs == 2


def test_generic_config_grpc_failure_does_not_create_subst(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    project = "axit-n4-20260807t000000z-123-genericg"
    monkeypatch.setattr(n4, "new_project_name", lambda: project)
    monkeypatch.setattr(n4, "_contains_non_ascii", lambda value: True)
    empty = {"containers": [], "networks": [], "volumes": []}
    snapshots = iter((empty, empty))
    monkeypatch.setattr(n4, "snapshot_project", lambda selected, runner: next(snapshots))
    calls: list[list[str]] = []

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        call = list(argv)
        calls.append(call)
        if "config" in call:
            return completed(call, returncode=1, stderr="generic gRPC transport failure")
        return completed(call)

    ports = iter((41001, 41002))
    with pytest.raises(n4.LifecycleError, match="compose config failed"):
        n4.Lifecycle(
            tmp_path,
            path,
            runner=runner,
            port_selector=lambda requested, excluded: next(ports),
        ).start()

    assert not any(call[:1] == ["subst"] for call in calls)
    assert not any("up" in call for call in calls)


def test_cleanup_pending_retries_subst_without_second_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    value = manifest(tmp_path, "axit-n4-20260807t000000z-123-cleanabc")
    value.update(
        status="cleanup_pending",
        cleanup_status="compose_down_succeeded",
        removed_resources=value["resources"],
        subst={"drive": "Z:", "target": str(tmp_path), "created_by_run": True},
    )
    value["config_paths"] = ["Z:\\docker-compose.yml", "Z:\\docker-compose.n4.yml"]
    n4.atomic_write_json(path, value)
    monkeypatch.setattr(n4, "snapshot_project", lambda selected, runner: value["phase0_before"])
    commands: list[list[str]] = []
    exact = False

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        nonlocal exact
        call = list(argv)
        commands.append(call)
        if call == ["subst"]:
            return completed(call, stdout=f"Z:\\: => {tmp_path}\\\n" if exact else "Z:\\: => C:\\foreign\\\n")
        if call[-1:] == ["/D"]:
            return completed(call)
        return completed(call)

    lifecycle = n4.Lifecycle(tmp_path, path, runner=runner)
    with pytest.raises(n4.LifecycleError, match="subst ownership mismatch"):
        lifecycle.stop()
    assert n4.read_manifest(path)["status"] == "cleanup_pending"
    exact = True
    stopped = lifecycle.stop()
    assert stopped["status"] == "stopped"
    assert not any("down" in command for command in commands)


def test_all_non_web_api_published_ports_and_project_name_are_rejected() -> None:
    project = "axit-n4-20260807t000000z-123-configab"
    config = resolved_config(41001, 41002, project)
    config["services"]["orchestrator"]["ports"] = [
        {"host_ip": "127.0.0.1", "published": 49999, "target": 9000}
    ]
    with pytest.raises(n4.LifecycleError, match="unexpected published port"):
        n4.validate_resolved_config(
            config, web_port=41001, api_port=41002, project=project
        )
    config = resolved_config(41001, 41002, "axit-n4-20260807t000000z-123-wrongabc")
    with pytest.raises(n4.LifecycleError, match="project"):
        n4.validate_resolved_config(
            config, web_port=41001, api_port=41002, project=project
        )
    with pytest.raises(n4.LifecycleError, match="unique"):
        n4.ComposeTarget("axit-n4-loose", Path("C:/base.yml"), Path("C:/n4.yml"))


def test_capture_exhausted_manifest_adopts_later_exact_resources_and_cleans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    project = "axit-n4-20260807t000000z-123-adoptabc"
    value = manifest(tmp_path, project)
    value.update(
        status="start_failed",
        status_history=["starting", "start_failed"],
        start_failure="resource_capture_failed",
        cleanup_status="capture_retry_exhausted",
        resources={"containers": [], "networks": [], "volumes": []},
    )
    n4.atomic_write_json(path, value)
    empty = {"containers": [], "networks": [], "volumes": []}
    snapshots = iter(
        [owned_resources(project), empty, empty, empty, empty]
    )
    monkeypatch.setattr(n4, "snapshot_project", lambda selected, runner: next(snapshots))
    calls: list[list[str]] = []

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return completed(list(argv))

    stopped = n4.Lifecycle(tmp_path, path, runner=runner).stop()
    assert stopped["status"] == "stopped"
    assert stopped["removed_resources"] == owned_resources(project)
    assert stopped["status_history"] == ["starting", "start_failed", "stopped"]
    assert sum("down" in call for call in calls) == 1


def test_capture_exhausted_recovery_label_mismatch_blocks_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    project = "axit-n4-20260807t000000z-123-badlabel"
    value = manifest(tmp_path, project)
    value.update(
        status="start_failed",
        status_history=["starting", "start_failed"],
        cleanup_status="capture_retry_exhausted",
        resources={"containers": [], "networks": [], "volumes": []},
    )
    n4.atomic_write_json(path, value)
    recovered = owned_resources(project)
    recovered["containers"][0]["labels"]["com.docker.compose.project"] = "foreign"
    monkeypatch.setattr(n4, "snapshot_project", lambda selected, runner: recovered)
    calls: list[list[str]] = []

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return completed(list(argv))

    with pytest.raises(n4.LifecycleError, match="project label"):
        n4.Lifecycle(tmp_path, path, runner=runner).stop()
    assert not any("down" in call for call in calls)
    blocked = n4.read_manifest(path)
    assert blocked["cleanup_status"] == "ownership_mismatch"
    assert blocked["resources"] == {"containers": [], "networks": [], "volumes": []}


def test_subst_create_success_query_failure_is_atomically_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    project = "axit-n4-20260807t000000z-123-orphanab"
    monkeypatch.setattr(n4, "new_project_name", lambda: project)
    monkeypatch.setattr(n4, "_contains_non_ascii", lambda value: True)
    empty = {"containers": [], "networks": [], "volumes": []}
    snapshots = iter((empty, empty))
    monkeypatch.setattr(n4, "snapshot_project", lambda selected, runner: next(snapshots))
    created = False
    deletes = 0

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        nonlocal created, deletes
        call = list(argv)
        if call[:1] == ["subst"]:
            if call[-1:] == ["/D"]:
                deletes += 1
                return completed(call)
            if len(call) == 3:
                created = True
                return completed(call)
            return completed(call, returncode=1)
        if "config" in call:
            return completed(
                call,
                returncode=1,
                stderr=(
                    "failed to dial gRPC: x-docker-expose-session-sharedkey "
                    "contains value with non-printable ASCII characters"
                ),
            )
        return completed(call)

    ports = iter((41001, 41002))
    with pytest.raises(n4.LifecycleError, match="subst ownership mismatch"):
        n4.Lifecycle(
            tmp_path,
            path,
            runner=runner,
            port_selector=lambda requested, excluded: next(ports),
        ).start()
    assert created and deletes == 0
    recorded = n4.read_manifest(path)
    assert recorded["status"] == "start_failed"
    assert recorded["cleanup_status"] == "subst_cleanup_blocked"
    assert recorded["subst"] == {
        "drive": "Z:",
        "target": str(tmp_path.resolve()).rstrip("\\"),
        "created_by_run": True,
    }
    assert recorded["config_paths"] == [
        "Z:\\docker-compose.yml",
        "Z:\\docker-compose.n4.yml",
    ]


@pytest.mark.parametrize(
    "mutation,error",
    [
        (lambda rows: rows["containers"].append(resource("extra", "axit-n4-20260807t000000z-123-proofabc", "web")), "ID set"),
        (lambda rows: rows["containers"][0]["labels"].update({"com.docker.compose.project": "foreign"}), "project label"),
        (lambda rows: rows["containers"][0]["labels"].pop("com.docker.compose.service"), "service label"),
    ],
)
def test_exact_id_and_label_ownership_required(
    tmp_path: Path, mutation: Any, error: str
) -> None:
    expected = manifest(tmp_path)
    current = json.loads(json.dumps(expected["resources"]))
    mutation(current)
    with pytest.raises(n4.LifecycleError, match=error):
        n4.assert_resource_ownership(
            expected,
            current,
            expected_configs=(tmp_path / "docker-compose.yml", tmp_path / "docker-compose.n4.yml"),
        )


def test_mismatch_blocks_all_destructive_compose_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "manifest.json"
    value = manifest(tmp_path)
    n4.atomic_write_json(path, value)
    calls: list[list[str]] = []

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return completed(list(argv))

    monkeypatch.setattr(n4, "snapshot_project", lambda project, runner: {**owned_resources(project), "containers": []})
    lifecycle = n4.Lifecycle(tmp_path, path, runner=runner)
    with pytest.raises(n4.LifecycleError, match="ID set mismatch"):
        lifecycle.stop()
    destructive = {"down", "stop", "rm"}
    assert not any(destructive.intersection(call) for call in calls)
    assert n4.read_manifest(path)["cleanup_status"] == "ownership_mismatch"


def test_partial_start_recovery_preserves_failure_and_stops_when_owned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    value = manifest(tmp_path)
    value.update(status="start_failed", status_history=["starting", "start_failed"], start_failure="api_health_failed")
    n4.atomic_write_json(path, value)
    snapshots = iter(
        [
            owned_resources(value["project"]),
            value["phase0_before"],
            {"containers": [], "networks": [], "volumes": []},
            value["phase0_before"],
        ]
    )
    monkeypatch.setattr(n4, "snapshot_project", lambda project, runner: next(snapshots))
    calls: list[list[str]] = []

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return completed(list(argv))

    stopped = n4.Lifecycle(tmp_path, path, runner=runner).stop()
    assert stopped["status_history"] == ["starting", "start_failed", "stopped"]
    assert stopped["start_failure"] == "api_health_failed"
    assert sum("down" in call for call in calls) == 1


@pytest.mark.parametrize(
    "subst,current,removes",
    [
        ({"drive": "X:", "target": "C:\\repo", "created_by_run": True}, "X:\\: => C:\\repo\\\n", 1),
        ({"drive": "X:", "target": "C:\\repo", "created_by_run": False}, "X:\\: => C:\\repo\\\n", 0),
        ({"drive": "X:", "target": "C:\\repo", "created_by_run": True}, "X:\\: => C:\\other\\\n", 0),
    ],
)
def test_subst_removal_requires_exact_run_owned_mapping(
    subst: dict[str, Any], current: str, removes: int
) -> None:
    calls: list[list[str]] = []

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return completed(list(argv), stdout=current)

    if removes:
        n4.remove_owned_subst(subst, runner)
    else:
        with pytest.raises(n4.LifecycleError, match="ownership mismatch"):
            n4.remove_owned_subst(subst, runner)
    assert sum(call[-1:] == ["/D"] for call in calls) == removes


def test_phase0_invariant_and_wrapper_invocation_contract() -> None:
    before = {"containers": [{"id": "phase0", "status": "running"}]}
    n4._phase0_equal(before, json.loads(json.dumps(before)))
    with pytest.raises(n4.LifecycleError, match="axit-phase0"):
        n4._phase0_equal(before, {"containers": [{"id": "phase0", "status": "exited"}]})
    wrapper = Path("scripts/run-notification-audit-n4.ps1").read_text(encoding="utf-8")
    assert "'run', 'python', 'scripts/n4_compose_lifecycle.py'" in wrapper
    assert "docker compose" not in wrapper.casefold()
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".g007-pytest-cache/" in dockerignore
    assert ".g007-pytest-tmp/" in dockerignore


def test_mock_only_suite_and_read_only_proof_command_boundary(tmp_path: Path) -> None:
    target = n4.ComposeTarget(
        "axit-n4-20260807t000000z-123-proofabc", (tmp_path / "base.yml").resolve(), (tmp_path / "n4.yml").resolve()
    )
    allowed = target.argv("config", "--format", "json")
    assert allowed[-3:] == ["config", "--format", "json"]
    assert "up" not in allowed and "down" not in allowed and "stop" not in allowed and "rm" not in allowed


@pytest.mark.parametrize("mismatch", ["config", "ownership", "phase0"])
def test_stale_probe_mismatch_blocks_compose_exec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    path = tmp_path / "manifest.json"
    value = manifest(tmp_path)
    if mismatch == "config":
        value["config_paths"] = [str(tmp_path / "foreign.yml"), str(tmp_path / "n4.yml")]
    n4.atomic_write_json(path, value)
    calls: list[list[str]] = []

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return completed(list(argv), stdout='{"stale":true,"in_app_rows":0,"outbox_rows":0}')

    if mismatch == "ownership":
        snapshots = iter(({**value["resources"], "containers": []}, value["phase0_before"]))
        monkeypatch.setattr(n4, "snapshot_project", lambda project, runner: next(snapshots))
    elif mismatch == "phase0":
        changed = {"containers": [{"id": "protected-changed"}], "networks": [], "volumes": []}
        snapshots = iter((value["resources"], changed))
        monkeypatch.setattr(n4, "snapshot_project", lambda project, runner: next(snapshots))

    with pytest.raises(n4.LifecycleError):
        n4.Lifecycle(tmp_path, path, runner=runner).probe_stale(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            ["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "cccccccc-cccc-4ccc-8ccc-cccccccccccc"],
        )
    assert not any("exec" in call for call in calls)


def test_stale_probe_uses_fixed_compose_exec_argv_and_bounded_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    value = manifest(tmp_path)
    n4.atomic_write_json(path, value)
    monkeypatch.setattr(
        n4,
        "snapshot_project",
        lambda project, runner: value["resources"] if project == value["project"] else value["phase0_before"],
    )
    calls: list[tuple[list[str], Any]] = []

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        calls.append((list(argv), env))
        return completed(list(argv), stdout='{"stale":true,"in_app_rows":0,"outbox_rows":0}')

    result = n4.Lifecycle(tmp_path, path, runner=runner).probe_stale(
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        ["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "cccccccc-cccc-4ccc-8ccc-cccccccccccc"],
    )
    assert result == {"stale": True, "in_app_rows": 0, "outbox_rows": 0}
    target = n4.ComposeTarget(
        value["project"],
        (tmp_path / "docker-compose.yml").resolve(),
        (tmp_path / "docker-compose.n4.yml").resolve(),
    )
    assert calls == [(
        target.argv(
            "exec", "-T", "api", "python", "-m", "app.n4_stale_probe",
            "--session-id", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "--recipient-id", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "--recipient-id", "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        ),
        None,
    )]

    calls.clear()
    with pytest.raises(n4.LifecycleError, match="UUID"):
        n4.Lifecycle(tmp_path, path, runner=runner).probe_stale(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa;docker",
            ["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "cccccccc-cccc-4ccc-8ccc-cccccccccccc"],
        )
    assert calls == []


def test_stale_probe_rejects_unbounded_container_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    value = manifest(tmp_path)
    n4.atomic_write_json(path, value)
    monkeypatch.setattr(
        n4,
        "snapshot_project",
        lambda project, runner: value["resources"] if project == value["project"] else value["phase0_before"],
    )

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        return completed(
            list(argv),
            stdout='{"stale":true,"in_app_rows":0,"outbox_rows":0,"leak":"forbidden"}',
        )

    with pytest.raises(n4.LifecycleError, match="unsupported result"):
        n4.Lifecycle(tmp_path, path, runner=runner).probe_stale(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            ["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "cccccccc-cccc-4ccc-8ccc-cccccccccccc"],
        )


def test_verify_exports_absolute_owned_probe_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "manifest.json"
    value = manifest(tmp_path)
    n4.atomic_write_json(path, value)
    monkeypatch.setattr(
        n4,
        "snapshot_project",
        lambda project, runner: value["resources"] if project == value["project"] else value["phase0_before"],
    )
    commands = {
        "pnpm": str((tmp_path / "pnpm.CMD").resolve()),
        "uv": str((tmp_path / "uv.exe").resolve()),
    }
    monkeypatch.setattr(n4, "resolve_command", lambda name: commands[name])
    captured_env: dict[str, str] = {}

    def runner(argv: Any, env: Any) -> subprocess.CompletedProcess[str]:
        captured_env.update(env)
        return completed(list(argv))

    n4.Lifecycle(tmp_path, path, runner=runner).verify()
    assert captured_env["AXIT_N4_ROOT"] == str(tmp_path.resolve())
    assert captured_env["AXIT_N4_MANIFEST"] == str(path.resolve())
    assert captured_env["AXIT_N4_PROBE_UV"] == commands["uv"]
    assert Path(captured_env["AXIT_N4_PROBE_SCRIPT"]).is_absolute()
