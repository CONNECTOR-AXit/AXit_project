"""Black-box subprocess proof for the Phase 2 parser IPC harness."""

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
    execute_sandbox,
)


pytestmark = pytest.mark.integration


_PARSER = r"""
import argparse
import hashlib
import json
import os
from pathlib import Path

arguments = argparse.ArgumentParser()
arguments.add_argument("--input", required=True)
arguments.add_argument("--request", required=True)
arguments.add_argument("--output", required=True)
args = arguments.parse_args()

request = json.loads(Path(args.request).read_text(encoding="utf-8"))
assert os.environ.get("DATABASE_URL") is None
assert os.environ.get("PROVIDER_TOKEN") is None
data = Path(args.input).read_bytes()
source_sha256 = hashlib.sha256(data).hexdigest()
assert source_sha256 == request["source_sha256"]
text = "독립 parser process"
anchor = {
    "schema_version": 1,
    "kind": "text_line",
    "source_sha256": source_sha256,
    "extraction_profile_hash": "b" * 64,
    "locator": {"line": 1, "start": 0, "end": len(text)},
    "text_fingerprint": hashlib.sha256(text.encode("utf-8")).hexdigest(),
}
def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
anchor_hash = hashlib.sha256(canonical(anchor).encode("utf-8")).hexdigest()
payload = {
    "schema_version": 1,
    "ok": True,
    "result": {
        "source_sha256": source_sha256,
        "media_type": request["expected_media_type"],
        "parser": request["parser"],
        "normalization_profile": "nfc-lf-v1",
        "config_profile_hash": "b" * 64,
        "anchor_set_hash": hashlib.sha256(canonical({"schema_version": 1, "anchor_hashes": [anchor_hash]}).encode("utf-8")).hexdigest(),
        "blocks": [{
            "ordinal": 0,
            "text": text,
            "block_type": "paragraph",
            "confidence": 0.99,
            "anchor": anchor,
            "anchor_hash": anchor_hash,
        }],
        "warnings": [],
    },
}
Path(args.output).write_text(canonical(payload), encoding="utf-8")
"""


def test_isolated_subprocess_accepts_only_staged_input_and_structured_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-for-parser")
    monkeypatch.setenv("PROVIDER_TOKEN", "not-for-parser")
    request = SandboxRequest(
        input_bytes=b"integration source bytes",
        original_filename="meeting.txt",
        expected_media_type="text/plain",
        expected_parser=ParserIdentity(name="integration-parser", version="1.0.0"),
    )
    policy = SandboxPolicy(
        max_input_bytes=1024,
        max_output_bytes=16 * 1024,
        max_stdout_bytes=1024,
        max_stderr_bytes=1024,
        wall_timeout_seconds=2.0,
        max_blocks=10,
        max_block_chars=1024,
        max_total_chars=2048,
    )

    execution = execute_sandbox(
        request,
        (sys.executable, "-c", _PARSER),
        policy,
        staging_root=tmp_path,
    )

    assert execution.ok is True
    assert execution.failure is None
    assert execution.source_sha256 == hashlib.sha256(request.input_bytes).hexdigest()
    assert execution.payload is not None
    assert execution.payload["result"]["parser"] == {  # type: ignore[index]
        "name": "integration-parser",
        "version": "1.0.0",
    }
    assert list(tmp_path.iterdir()) == []


def test_rejects_a_parser_exit_code_that_does_not_match_its_envelope(
    tmp_path: Path,
) -> None:
    request = SandboxRequest(
        input_bytes=b"exit mismatch",
        original_filename="meeting.txt",
        expected_media_type="text/plain",
        expected_parser=ParserIdentity(name="integration-parser", version="1.0.0"),
    )
    payload = {
        "schema_version": 1,
        "ok": False,
        "error": {
            "code": "CORRUPT_DOCUMENT",
            "message": "controlled failure",
            "retryable": False,
        },
    }
    writer = (
        "import argparse,json; from pathlib import Path; "
        "p=argparse.ArgumentParser(); p.add_argument('--input'); "
        "p.add_argument('--request'); p.add_argument('--output'); a=p.parse_args(); "
        f"Path(a.output).write_text({json.dumps(json.dumps(payload))}, encoding='utf-8')"
    )
    policy = SandboxPolicy(
        max_input_bytes=1024,
        max_output_bytes=1024,
        max_stdout_bytes=1024,
        max_stderr_bytes=1024,
        wall_timeout_seconds=2.0,
        max_blocks=10,
        max_block_chars=1024,
        max_total_chars=2048,
    )

    execution = execute_sandbox(
        request,
        (sys.executable, "-c", writer),
        policy,
        staging_root=tmp_path,
    )

    assert execution.ok is False
    assert execution.failure is not None
    assert execution.failure.code is SandboxFailureCode.PARSER_EXIT_MISMATCH
    assert list(tmp_path.iterdir()) == []
