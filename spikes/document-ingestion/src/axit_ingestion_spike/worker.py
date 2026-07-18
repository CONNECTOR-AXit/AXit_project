"""One-input/one-JSON worker entry point for the isolated G0 container."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import socket
import stat
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from axit_ingestion_spike.models import (
    ErrorCode,
    ExtractionEnvelope,
    ExtractionException,
    ExtractionPolicy,
    extraction_failure,
    load_spike_policy,
)
from axit_ingestion_spike.normalization import canonical_json
from axit_ingestion_spike.pipeline import extract_document


_PROBES = ("network", "secret", "filesystem", "timeout", "output")
_SENSITIVE_ENVIRONMENT_NAME = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API_KEY|DATABASE_URL|DB_URL|"
    r"POSTGRES|SESSION|COOKIE|AWS_|AZURE_|GOOGLE_)",
    re.IGNORECASE,
)
_SECRET_MOUNT_CANDIDATES = (
    Path("/run/secrets"),
    Path("/var/run/secrets"),
    Path("/host"),
    Path("/workspace/.env"),
)
_RESOURCE_METRICS_FIELD = "_axit_resource_metrics"
_RESOURCE_METRICS_NONCE = re.compile(r"[a-f0-9]{32}")
_CGROUP_MEMORY_PEAK_PATHS = ("/sys/fs/cgroup/memory.peak",)
_CGROUP_PIDS_PEAK_PATHS = ("/sys/fs/cgroup/pids.peak",)


class _DiscardText(io.TextIOBase):
    def writable(self) -> bool:
        return True

    def write(self, value: str) -> int:
        return len(value)


def _failure(code: ErrorCode, message: str) -> ExtractionEnvelope:
    return ExtractionEnvelope.failure(extraction_failure(code, message).error)


def _read_regular_file(path: Path, *, policy: ExtractionPolicy) -> bytes:
    try:
        file_stat = path.stat()
        if not stat.S_ISREG(file_stat.st_mode):
            raise extraction_failure(
                ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                "worker input must be a regular file",
            )
        if file_stat.st_size > policy.max_input_bytes:
            raise extraction_failure(
                ErrorCode.INPUT_TOO_LARGE,
                "input exceeds configured byte limit",
            )
        with path.open("rb") as input_file:
            data = input_file.read(policy.max_input_bytes + 1)
        if len(data) > policy.max_input_bytes:
            raise extraction_failure(
                ErrorCode.INPUT_TOO_LARGE,
                "input exceeds configured byte limit",
            )
        return data
    except PermissionError:
        raise extraction_failure(
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            "worker cannot read the input file",
        ) from None
    except FileNotFoundError:
        raise extraction_failure(
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            "worker input file does not exist",
        ) from None


def _root_filesystem_writable() -> bool:
    probe_path = Path("/.axit-g0-write-probe")
    try:
        descriptor = os.open(
            probe_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except OSError:
        return False
    os.close(descriptor)
    try:
        probe_path.unlink()
    except OSError:
        pass
    return True


def _input_is_writable(path: Path) -> bool:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
    except OSError:
        return False
    os.close(descriptor)
    return True


def _process_security_status() -> tuple[bool | None, bool | None]:
    try:
        status_lines = (
            Path("/proc/self/status")
            .read_text(
                encoding="utf-8",
                errors="strict",
            )
            .splitlines()
        )
    except (OSError, UnicodeError):
        return None, None
    fields = {
        key: value.strip()
        for line in status_lines
        if ":" in line
        for key, value in (line.split(":", 1),)
    }
    try:
        capabilities_zero = int(fields["CapEff"], 16) == 0
        no_new_privileges = fields["NoNewPrivs"] == "1"
    except (KeyError, ValueError):
        return None, None
    return capabilities_zero, no_new_privileges


def _read_first_cgroup_value(*paths: str) -> str | None:
    for raw_path in paths:
        try:
            value = Path(raw_path).read_text(encoding="ascii", errors="strict").strip()
        except (OSError, UnicodeError):
            continue
        if value and len(value) <= 128:
            return value
    return None


def _read_cgroup_peak(*paths: str) -> int | None:
    """Read a kernel-owned cgroup peak counter without exposing its source path.

    The G0 runtime uses cgroup v2, where ``memory.peak`` and ``pids.peak`` are
    monotonic for the life of the container.  We intentionally do not fall back
    to a current-usage value: a current value after parser children exit would
    turn a peak-evidence claim into a race.
    """

    raw = _read_first_cgroup_value(*paths)
    if raw is None or not raw.isdecimal():
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value <= 0 or value > (1 << 63) - 1:
        return None
    return value


def _resource_metrics_nonce(value: str | None) -> str | None:
    """Accept a host-generated nonce only when runtime evidence was requested."""

    if value is None:
        return None
    if _RESOURCE_METRICS_NONCE.fullmatch(value) is None:
        raise extraction_failure(
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            "worker resource metrics arguments are invalid",
        )
    return value


def _attach_resource_metrics(
    serialized: str, *, nonce: str, max_output_bytes: int
) -> str:
    """Attach kernel cgroup peaks to an opt-in, bounded host-only envelope field.

    The runner strips and validates this exact field before parser-protocol
    validation, so normal parser payloads and captured fixture payloads retain
    their schema.  It is deliberately unavailable without a fresh host nonce.
    """

    peak_memory_bytes = _read_cgroup_peak(*_CGROUP_MEMORY_PEAK_PATHS)
    peak_pids = _read_cgroup_peak(*_CGROUP_PIDS_PEAK_PATHS)
    if peak_memory_bytes is None or peak_pids is None:
        return serialized
    try:
        payload = json.loads(serialized)
        if not isinstance(payload, dict) or _RESOURCE_METRICS_FIELD in payload:
            return serialized
        payload[_RESOURCE_METRICS_FIELD] = {
            "nonce": nonce,
            "peak_memory_bytes": peak_memory_bytes,
            "peak_pids": peak_pids,
            "schema_version": 1,
        }
        candidate = canonical_json(payload)
        if not isinstance(candidate, str) or len(candidate.encode("utf-8")) > max_output_bytes:
            return serialized
        return candidate
    except (TypeError, ValueError, json.JSONDecodeError):
        return serialized


def _temporary_mount_evidence(path: Path) -> tuple[str | None, list[str], int | None]:
    filesystem_type: str | None = None
    options: set[str] = set()
    try:
        with Path("/proc/self/mountinfo").open(
            "r", encoding="utf-8", errors="strict"
        ) as mountinfo:
            payload = mountinfo.read(65_537)
        if len(payload) <= 65_536:
            expected = path.as_posix().replace(" ", "\\040")
            for line in payload.splitlines():
                before, separator, after = line.partition(" - ")
                fields = before.split()
                trailing = after.split()
                if separator and len(fields) >= 6 and len(trailing) >= 3:
                    if fields[4] == expected:
                        filesystem_type = trailing[0]
                        options.update(fields[5].split(","))
                        options.update(trailing[2].split(","))
                        break
    except (OSError, UnicodeError):
        pass
    try:
        statvfs = getattr(os, "statvfs", None)
        if statvfs is None:
            raise OSError
        filesystem = statvfs(path)
        capacity = filesystem.f_frsize * filesystem.f_blocks
    except (AttributeError, OSError):
        capacity = None
    return filesystem_type, sorted(option for option in options if option), capacity


def _outbound_network_reachable(host: str, port: int) -> bool:
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.settimeout(0.25)
    try:
        return connection.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        connection.close()


def _probe_payload(kind: str, values: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "ok": True,
        "probe": {"kind": kind, **values},
    }


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, exit_on_error=False)
    parser.add_argument("positional_input", nargs="?", help="sandbox-mounted input")
    parser.add_argument("--input", dest="option_input", help="sandbox-mounted input")
    parser.add_argument("--filename", help="original filename used for type agreement")
    parser.add_argument("--probe", choices=_PROBES)
    parser.add_argument("--network-probe-host")
    parser.add_argument("--network-probe-port", type=int)
    parser.add_argument("--resource-metrics-nonce")
    try:
        return parser.parse_args(argv)
    except (argparse.ArgumentError, SystemExit) as error:
        raise extraction_failure(
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            "worker arguments are invalid",
        ) from error


def _execute_probe(
    probe: str,
    *,
    input_path: Path | None,
    policy: ExtractionPolicy,
    network_probe_host: str,
    network_probe_port: int,
) -> tuple[str, int]:
    if probe == "timeout":
        time.sleep(max(policy.ocr_timeout_seconds * 10, 60))
        raise AssertionError("timeout probe must be terminated by the host boundary")
    if probe == "output":
        # Deliberately violate the host cap; the sandbox runner must stop capture.
        return "x" * (policy.max_output_bytes + 1), 0
    if probe == "network":
        if (
            not network_probe_host
            or len(network_probe_host) > 253
            or any(
                character
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"
                for character in network_probe_host
            )
            or not 1 <= network_probe_port <= 65_535
        ):
            envelope = _failure(
                ErrorCode.UNSUPPORTED_MEDIA_TYPE, "network probe target is invalid"
            )
            return envelope.to_json(max_bytes=policy.max_output_bytes), 2
        payload = _probe_payload(
            probe,
            {
                "outbound_network_reachable": _outbound_network_reachable(
                    network_probe_host, network_probe_port
                ),
                "target_host": network_probe_host,
                "target_port": network_probe_port,
            },
        )
    elif probe == "secret":
        payload = _probe_payload(
            probe,
            {
                "sensitive_environment_present": any(
                    _SENSITIVE_ENVIRONMENT_NAME.search(name) is not None
                    for name in os.environ
                ),
                "secret_mount_present": any(
                    path.exists() for path in _SECRET_MOUNT_CANDIDATES
                ),
            },
        )
    elif probe == "filesystem":
        if input_path is None:
            envelope = _failure(
                ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                "filesystem probe requires the mounted input",
            )
            return envelope.to_json(max_bytes=policy.max_output_bytes), 2
        capabilities_zero, no_new_privileges = _process_security_status()
        temporary_path = Path(os.environ.get("TMPDIR", "/tmp"))
        temporary_type, temporary_options, temporary_capacity = (
            _temporary_mount_evidence(temporary_path)
        )
        payload = _probe_payload(
            probe,
            {
                "capabilities_zero": capabilities_zero,
                "cgroup_cpu_max": _read_first_cgroup_value(
                    "/sys/fs/cgroup/cpu.max",
                    "/sys/fs/cgroup/cpu/cpu.cfs_quota_us",
                ),
                "cgroup_memory_max": _read_first_cgroup_value(
                    "/sys/fs/cgroup/memory.max",
                    "/sys/fs/cgroup/memory/memory.limit_in_bytes",
                ),
                "cgroup_pids_max": _read_first_cgroup_value(
                    "/sys/fs/cgroup/pids.max",
                    "/sys/fs/cgroup/pids/pids.max",
                ),
                "docker_socket_present": Path("/var/run/docker.sock").exists(),
                "effective_uid": os.geteuid() if hasattr(os, "geteuid") else None,
                "input_writable": _input_is_writable(input_path),
                "no_new_privileges": no_new_privileges,
                "root_filesystem_writable": _root_filesystem_writable(),
                "temporary_directory_writable": os.access(
                    temporary_path, os.W_OK
                ),
                "temporary_filesystem_type": temporary_type,
                "temporary_mount_options": temporary_options,
                "temporary_capacity_bytes": temporary_capacity,
            },
        )
    else:  # pragma: no cover - argparse owns the allowlist
        envelope = _failure(ErrorCode.UNSUPPORTED_MEDIA_TYPE, "unknown probe mode")
        return envelope.to_json(max_bytes=policy.max_output_bytes), 2
    serialized = canonical_json(payload)
    if len(serialized.encode("utf-8")) > policy.max_output_bytes:
        envelope = _failure(
            ErrorCode.OUTPUT_TOO_LARGE, "probe output exceeds byte limit"
        )
        return envelope.to_json(max_bytes=policy.max_output_bytes), 2
    return serialized, 0


def run(argv: Sequence[str] | None = None) -> tuple[str, int]:
    """Return one bounded JSON document, except deliberate host-boundary probes."""

    try:
        policy = load_spike_policy()
    except ValueError:
        policy = ExtractionPolicy()
        envelope = _failure(
            ErrorCode.INTERNAL_ERROR,
            "worker policy is unavailable or invalid",
        )
        return envelope.to_json(max_bytes=policy.max_output_bytes), 2

    metrics_nonce: str | None = None
    try:
        arguments = _parse_arguments(argv)
        metrics_nonce = _resource_metrics_nonce(arguments.resource_metrics_nonce)
        if (
            arguments.positional_input is not None
            and arguments.option_input is not None
            and arguments.positional_input != arguments.option_input
        ):
            raise extraction_failure(
                ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                "worker received conflicting input arguments",
            )
        input_value = arguments.option_input or arguments.positional_input
        input_path = Path(input_value) if input_value is not None else None
        if arguments.probe is not None:
            serialized, status = _execute_probe(
                arguments.probe,
                input_path=input_path,
                policy=policy,
                network_probe_host=arguments.network_probe_host or "1.1.1.1",
                network_probe_port=arguments.network_probe_port or 53,
            )
        else:
            if input_path is None:
                raise extraction_failure(
                    ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                    "worker requires one input file",
                )
            data = _read_regular_file(input_path, policy=policy)
            filename = arguments.filename or input_path.name
            discarded_output = _DiscardText()
            with (
                contextlib.redirect_stdout(discarded_output),
                contextlib.redirect_stderr(discarded_output),
            ):
                envelope = extract_document(
                    data,
                    filename=filename,
                    policy=policy,
                )
            try:
                serialized = envelope.to_json(max_bytes=policy.max_output_bytes)
            except Exception:
                serialized = _failure(
                    ErrorCode.OUTPUT_TOO_LARGE,
                    "serialized extraction output exceeds configured byte limit",
                ).to_json(max_bytes=policy.max_output_bytes)
                status = 2
            else:
                status = 0 if envelope.ok else 2
    except ExtractionException as error:
        serialized = ExtractionEnvelope.failure(error.error).to_json(
            max_bytes=policy.max_output_bytes
        )
        status = 2
    except Exception:
        serialized = _failure(
            ErrorCode.INTERNAL_ERROR,
            "worker failed without a safe typed result",
        ).to_json(max_bytes=policy.max_output_bytes)
        status = 2
    finally:
        if metrics_nonce is not None:
            serialized = _attach_resource_metrics(
                serialized,
                nonce=metrics_nonce,
                max_output_bytes=policy.max_output_bytes,
            )
    return serialized, status


def main(argv: Sequence[str] | None = None) -> int:
    serialized, status = run(argv)
    sys.stdout.write(serialized)
    sys.stdout.write("\n")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
