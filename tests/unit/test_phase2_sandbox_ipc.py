"""Unit contracts for the Phase 2 orchestrator-to-parser IPC boundary."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from apps.api.app.sandbox_ipc import (
    ParserIdentity,
    SandboxFailureCode,
    SandboxPolicy,
    SandboxRequest,
    canonical_sha256,
    execute_sandbox,
)


_WRITER = r"""
import argparse
import json
import os
import pathlib
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("payload")
parser.add_argument("--input", required=True)
parser.add_argument("--request", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()

payload = json.loads(args.payload)
mode = payload.pop("_test_mode", "write")
exit_code = payload.pop("_test_exit", 0)
if mode == "timeout":
    time.sleep(2)
elif mode == "huge-output":
    pathlib.Path(args.output).write_bytes(b"x" * payload.pop("_test_bytes"))
elif mode == "crash":
    sys.exit(17)
else:
    request = json.loads(pathlib.Path(args.request).read_text(encoding="utf-8"))
    assert set(request) == {
        "expected_media_type",
        "original_filename",
        "parser",
        "schema_version",
        "source_sha256",
    }
    assert pathlib.Path(args.input).read_bytes() == b"meeting source bytes"
    assert os.environ.get("DATABASE_URL") is None
    assert os.environ.get("XAI_API_KEY") is None
    assert os.environ.get("SESSION_SECRET") is None
    pathlib.Path(args.output).write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
if exit_code:
    sys.exit(exit_code)
"""


def _policy(**overrides: object) -> SandboxPolicy:
    values: dict[str, object] = {
        "max_input_bytes": 1024,
        "max_output_bytes": 16 * 1024,
        "max_stdout_bytes": 1024,
        "max_stderr_bytes": 1024,
        "wall_timeout_seconds": 1.0,
        "max_blocks": 16,
        "max_block_chars": 1024,
        "max_total_chars": 2048,
    }
    values.update(overrides)
    return SandboxPolicy(**values)


def _request() -> SandboxRequest:
    return SandboxRequest(
        input_bytes=b"meeting source bytes",
        original_filename="agenda.txt",
        expected_media_type="text/plain",
        expected_parser=ParserIdentity(name="fixture-parser", version="1.0.0"),
    )


def _success_payload(
    request: SandboxRequest,
    *,
    bbox: list[float] | None = None,
) -> dict[str, object]:
    source_sha256 = hashlib.sha256(request.input_bytes).hexdigest()
    profile_hash = "a" * 64
    text = "회의 안건"
    if bbox is None:
        kind = "text_line"
        locator: dict[str, object] = {"line": 1, "start": 0, "end": len(text)}
    else:
        kind = "pdf_block"
        locator = {"page": 0, "block_id": "block-1", "bbox": bbox}
    anchor = {
        "schema_version": 1,
        "kind": kind,
        "source_sha256": source_sha256,
        "extraction_profile_hash": profile_hash,
        "locator": locator,
        "text_fingerprint": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    anchor_hash = canonical_sha256(anchor)
    block = {
        "ordinal": 0,
        "text": text,
        "block_type": "paragraph",
        "confidence": 1.0,
        "anchor": anchor,
        "anchor_hash": anchor_hash,
    }
    return {
        "schema_version": 1,
        "ok": True,
        "result": {
            "source_sha256": source_sha256,
            "media_type": request.expected_media_type,
            "parser": {
                "name": request.expected_parser.name,
                "version": request.expected_parser.version,
            },
            "normalization_profile": "nfc-lf-v1",
            "config_profile_hash": profile_hash,
            "anchor_set_hash": canonical_sha256(
                {"schema_version": 1, "anchor_hashes": [anchor_hash]}
            ),
            "blocks": [block],
            "warnings": [],
        },
    }


def _command(payload: dict[str, object]) -> tuple[str, ...]:
    return (sys.executable, "-c", _WRITER, json.dumps(payload, ensure_ascii=False))


def test_validates_phase1_style_response_and_scrubs_parent_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://must-not-cross-ipc")
    monkeypatch.setenv("XAI_API_KEY", "must-not-cross-ipc")
    monkeypatch.setenv("SESSION_SECRET", "must-not-cross-ipc")
    request = _request()

    execution = execute_sandbox(
        request,
        _command(_success_payload(request)),
        _policy(),
        staging_root=tmp_path,
    )

    assert execution.ok is True
    assert execution.failure is None
    assert execution.payload == _success_payload(request)
    assert execution.source_sha256 == hashlib.sha256(request.input_bytes).hexdigest()
    assert execution.stdout_bytes == 0
    assert execution.stderr_bytes == 0
    assert list(tmp_path.iterdir()) == []


def test_rejects_invalid_anchor_coordinate_and_cleans_staging(tmp_path: Path) -> None:
    base_request = _request()
    request = SandboxRequest(
        input_bytes=base_request.input_bytes,
        original_filename="agenda.pdf",
        expected_media_type="application/pdf",
        expected_parser=base_request.expected_parser,
    )
    payload = _success_payload(request, bbox=[0.9, 0.1, 0.2, 0.8])

    execution = execute_sandbox(
        request,
        _command(payload),
        _policy(),
        staging_root=tmp_path,
    )

    assert execution.ok is False
    assert execution.failure is not None
    assert execution.failure.code is SandboxFailureCode.INVALID_PARSER_OUTPUT
    assert execution.payload is None
    assert list(tmp_path.iterdir()) == []


def test_rejects_oversized_input_before_starting_parser(tmp_path: Path) -> None:
    marker = tmp_path / "started"
    command = (
        sys.executable,
        "-c",
        "from pathlib import Path; Path(r'" + str(marker) + "').write_text('started')",
    )
    request = SandboxRequest(
        input_bytes=b"too-large",
        original_filename="agenda.txt",
        expected_media_type="text/plain",
        expected_parser=ParserIdentity(name="fixture-parser", version="1.0.0"),
    )

    execution = execute_sandbox(
        request,
        command,
        _policy(max_input_bytes=4),
        staging_root=tmp_path,
    )

    assert execution.ok is False
    assert execution.failure is not None
    assert execution.failure.code is SandboxFailureCode.INPUT_TOO_LARGE
    assert marker.exists() is False
    assert list(tmp_path.iterdir()) == []


def test_enforces_output_byte_cap(tmp_path: Path) -> None:
    request = _request()
    payload = {"_test_mode": "huge-output", "_test_bytes": 129}

    execution = execute_sandbox(
        request,
        _command(payload),
        _policy(max_output_bytes=128),
        staging_root=tmp_path,
    )

    assert execution.ok is False
    assert execution.failure is not None
    assert execution.failure.code is SandboxFailureCode.PARSER_OUTPUT_TOO_LARGE
    assert execution.payload is None
    assert list(tmp_path.iterdir()) == []


def test_enforces_wall_timeout_and_does_not_return_worker_logs(tmp_path: Path) -> None:
    request = _request()

    execution = execute_sandbox(
        request,
        _command({"_test_mode": "timeout"}),
        _policy(wall_timeout_seconds=0.05),
        staging_root=tmp_path,
    )

    assert execution.ok is False
    assert execution.failure is not None
    assert execution.failure.code is SandboxFailureCode.PARSER_TIMEOUT
    assert execution.payload is None
    assert execution.stderr_bytes == 0
    assert list(tmp_path.iterdir()) == []


def test_preserves_valid_typed_parser_failure(tmp_path: Path) -> None:
    request = _request()
    payload = {
        "schema_version": 1,
        "ok": False,
        "error": {
            "code": "CORRUPT_DOCUMENT",
            "message": "document cannot be parsed",
            "retryable": False,
        },
        "_test_exit": 2,
    }

    execution = execute_sandbox(
        request,
        _command(payload),
        _policy(),
        staging_root=tmp_path,
    )

    assert execution.ok is False
    assert execution.failure is not None
    assert execution.failure.code is SandboxFailureCode.PARSER_REPORTED_FAILURE
    assert execution.failure.parser_code == "CORRUPT_DOCUMENT"
    assert execution.failure.retryable is False
    assert execution.payload is None
    assert list(tmp_path.iterdir()) == []


def test_does_not_return_parser_controlled_failure_text(tmp_path: Path) -> None:
    request = _request()
    payload = {
        "schema_version": 1,
        "ok": False,
        "error": {
            "code": "CORRUPT_DOCUMENT",
            "message": "participant private text: do not leak this marker",
            "retryable": False,
        },
        "_test_exit": 2,
    }

    execution = execute_sandbox(
        request,
        _command(payload),
        _policy(),
        staging_root=tmp_path,
    )

    assert execution.ok is False
    assert execution.failure is not None
    assert execution.failure.parser_code == "CORRUPT_DOCUMENT"
    assert execution.payload is None
    assert list(tmp_path.iterdir()) == []


def test_rejects_parser_logs_without_returning_their_content(tmp_path: Path) -> None:
    execution = execute_sandbox(
        _request(),
        (sys.executable, "-c", "print('private parser log marker')"),
        _policy(),
        staging_root=tmp_path,
    )

    assert execution.ok is False
    assert execution.failure is not None
    assert execution.failure.code is SandboxFailureCode.PARSER_LOG_OUTPUT
    assert execution.payload is None
    assert execution.stdout_bytes > 0
    assert list(tmp_path.iterdir()) == []


def test_enforces_parser_log_cap_and_cleans_staging(tmp_path: Path) -> None:
    execution = execute_sandbox(
        _request(),
        (
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('x' * 4096); sys.stdout.flush()",
        ),
        _policy(max_stdout_bytes=32),
        staging_root=tmp_path,
    )

    assert execution.ok is False
    assert execution.failure is not None
    assert execution.failure.code is SandboxFailureCode.PARSER_LOG_LIMIT
    assert execution.payload is None
    assert execution.killed is True
    assert list(tmp_path.iterdir()) == []


def test_rejects_extra_parser_output_entries(tmp_path: Path) -> None:
    writer = (
        "import argparse; from pathlib import Path; "
        "p=argparse.ArgumentParser(); p.add_argument('--input'); "
        "p.add_argument('--request'); p.add_argument('--output'); a=p.parse_args(); "
        "Path(a.output).write_text('{}', encoding='utf-8'); "
        "Path(a.output).with_name('unexpected').write_text('x', encoding='utf-8')"
    )
    execution = execute_sandbox(
        _request(),
        (sys.executable, "-c", writer),
        _policy(),
        staging_root=tmp_path,
    )

    assert execution.ok is False
    assert execution.failure is not None
    assert execution.failure.code is SandboxFailureCode.INVALID_PARSER_OUTPUT
    assert execution.payload is None
    assert list(tmp_path.iterdir()) == []


def test_rejects_a_staged_source_tamper_attempt(tmp_path: Path) -> None:
    tamper = (
        "import argparse, os, stat; from pathlib import Path; "
        "p=argparse.ArgumentParser(); p.add_argument('--input'); "
        "p.add_argument('--request'); p.add_argument('--output'); a=p.parse_args(); "
        "os.chmod(a.input, stat.S_IREAD | stat.S_IWRITE); "
        "Path(a.input).write_bytes(b'tampered')"
    )
    execution = execute_sandbox(
        _request(),
        (sys.executable, "-c", tamper),
        _policy(),
        staging_root=tmp_path,
    )

    assert execution.ok is False
    assert execution.failure is not None
    assert execution.failure.code is SandboxFailureCode.STAGED_INPUT_TAMPERED
    assert execution.payload is None
    assert list(tmp_path.iterdir()) == []
