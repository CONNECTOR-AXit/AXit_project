"""Fenced file extraction effects and the host-only exact G0 Docker adapter."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import logging
import os
import shutil
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from types import ModuleType
from typing import Any, Final
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from app.activity_policy import build_event_key
from app.activity_service import ActivityService
from app.domain import JobState, StaleLeaseError
from app.file_submission_service import FileSubmissionError, LocalBlobStore
from app.queue_repository import ClaimedJob, PostgresJobQueue
from app.sandbox_ipc import (
    ParserIdentity,
    SandboxExecution,
    SandboxFailureCode,
    SandboxRequest,
    canonical_sha256,
)


G0_IMAGE: Final = os.environ.get("AXIT_G0_IMAGE", "axit-ingestion-g0:local")
_PROFILE_BY_MEDIA: Final = {
    "application/pdf": "66c3e4fb17d97a94b56511982ba9624ce168d35aa391087b2c414b3eb65f4cc2",
    "image/png": "31b063d1175f667d67385fc9d4657e541cf450e7524b257aee2d5da3f87f2a6c",
    "image/jpeg": "31b063d1175f667d67385fc9d4657e541cf450e7524b257aee2d5da3f87f2a6c",
    "application/x-hwp": "e320c367c7c5952bcb83a067f44edd8729d65c6c5d20fceccaf69c7a641271df",
    "application/x-hwpx": "ae4e3c7f49383c4d2768445f81fba32ce343701bcf053969bc959b50c4dea8af",
    "text/plain": "f9459187e413f808732f93f126f8140886cc575130e3884b86c12c65d29bc8b7",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "e320c367c7c5952bcb83a067f44edd8729d65c6c5d20fceccaf69c7a641271df",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "588fbb9988828934408a492500541c64714acaaa5db3cad312b8b2f616ec9c86",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "00e03add157065ac766b05c63a914d36974288c7dd698a163ba960bfa830b8d2",
}
_MAX_EXTRACTION_ATTEMPTS: Final = 3
_APPROVED_RUNNER: ModuleType | None = None
_LOGGER = logging.getLogger(__name__)

ConnectionFactory = Callable[
    [], AbstractContextManager[psycopg.Connection[dict[str, Any]]]
]


class DockerSandboxAdapter:
    """Validate the G0 envelope around one short-lived, locked-down Docker run.

    This adapter is intentionally host-side. Compose services never receive a
    Docker socket; an operator starts this worker on a Docker-capable host.
    """

    def __init__(self, *, image: str = G0_IMAGE, docker_binary: str = "docker") -> None:
        if not image or any(character.isspace() for character in image):
            raise ValueError("sandbox image must be one token")
        resolved_docker = shutil.which(docker_binary)
        if resolved_docker is None:
            raise ValueError("docker binary is unavailable")
        self._image = image
        self._docker_binary = resolved_docker

    def execute(self, request: SandboxRequest) -> SandboxExecution:
        runner = _approved_sandbox_runner()
        spike_request = runner.SandboxRequest(
            image=self._image,
            input_bytes=request.input_bytes,
            original_filename=request.original_filename,
        )
        policy = runner.SandboxPolicy.from_json(
            _repository_root() / "spikes" / "document-ingestion" / "policy.v1.json"
        )
        spike_execution = runner.execute_sandbox(
            spike_request,
            policy,
            docker_binary=self._docker_binary,
        )
        execution = _convert_approved_execution(spike_execution)
        if execution.ok and execution.payload is not None:
            result = execution.payload.get("result")
            expected = _PROFILE_BY_MEDIA.get(request.expected_media_type)
            if not isinstance(result, Mapping) or result.get("config_profile_hash") != expected:
                return SandboxExecution(
                    ok=False,
                    payload=None,
                    failure=_sandbox_failure(SandboxFailureCode.INVALID_PARSER_OUTPUT),
                    source_sha256=execution.source_sha256,
                    exit_code=execution.exit_code,
                    duration_ms=execution.duration_ms,
                    stdout_bytes=execution.stdout_bytes,
                    stderr_bytes=execution.stderr_bytes,
                    killed=execution.killed,
                )
        return execution


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _approved_sandbox_runner() -> ModuleType:
    """Load the approved G0 runner without duplicating its containment code."""

    global _APPROVED_RUNNER
    if _APPROVED_RUNNER is not None:
        return _APPROVED_RUNNER
    root = _repository_root() / "spikes" / "document-ingestion"
    for import_root in (root, root / "src"):
        value = str(import_root)
        if value not in sys.path:
            sys.path.insert(0, value)
    spec = importlib.util.spec_from_file_location(
        "axit_approved_g0_sandbox_runner", root / "sandbox_runner.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("approved G0 sandbox runner is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _APPROVED_RUNNER = module
    return module


def _convert_approved_execution(execution: Any) -> SandboxExecution:
    source_sha256 = execution.source_sha256 or "0" * 64
    if execution.ok:
        return SandboxExecution(
            ok=True,
            payload=execution.payload,
            failure=None,
            source_sha256=source_sha256,
            exit_code=execution.exit_code,
            duration_ms=execution.duration_ms,
            stdout_bytes=execution.stdout_bytes,
            stderr_bytes=execution.stderr_bytes,
            killed=execution.killed,
        )
    code = str(execution.error_code or "SANDBOX_LAUNCH_FAILED")
    boundary_codes = {
        "INPUT_TOO_LARGE": SandboxFailureCode.INPUT_TOO_LARGE,
        "PARSER_TIMEOUT": SandboxFailureCode.PARSER_TIMEOUT,
        "PARSER_LOG_LIMIT": SandboxFailureCode.PARSER_LOG_LIMIT,
        "PARSER_LOG_OUTPUT": SandboxFailureCode.PARSER_LOG_OUTPUT,
        "PARSER_CRASH": SandboxFailureCode.PARSER_CRASH,
        "PARSER_OUTPUT_LIMIT": SandboxFailureCode.PARSER_OUTPUT_TOO_LARGE,
        "INVALID_PARSER_OUTPUT": SandboxFailureCode.INVALID_PARSER_OUTPUT,
    }
    boundary = boundary_codes.get(code)
    failure = (
        _sandbox_failure(boundary)
        if boundary is not None
        else _sandbox_failure(
            SandboxFailureCode.PARSER_REPORTED_FAILURE,
            parser_code=code,
            retryable=code in {"OCR_TIMEOUT", "DEPENDENCY_UNAVAILABLE"},
        )
    )
    return SandboxExecution(
        ok=False,
        payload=None,
        failure=failure,
        source_sha256=source_sha256,
        exit_code=execution.exit_code,
        duration_ms=execution.duration_ms,
        stdout_bytes=execution.stdout_bytes,
        stderr_bytes=execution.stderr_bytes,
        killed=execution.killed,
    )


def _sandbox_failure(
    code: SandboxFailureCode,
    *,
    parser_code: str | None = None,
    retryable: bool | None = None,
) -> Any:
    # Kept local to avoid exposing parser-controlled text in an exception.
    from app.sandbox_ipc import SandboxFailure

    return SandboxFailure(code, parser_code=parser_code, retryable=retryable)


class FileExtractionWorker:
    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory,
        blob_store: LocalBlobStore,
        sandbox_adapter: Any,
        queue: PostgresJobQueue | None = None,
    ) -> None:
        self._connections = connection_factory
        self._blobs = blob_store
        self._sandbox = sandbox_adapter
        self._queue = queue or PostgresJobQueue()

    def run_once(self, owner: str) -> Any:
        with self._connections() as connection:
            _reconcile_retryable_extractions(connection)
            claimed = self._queue.claim_next(
                connection, owner=owner, lease_seconds=60, kinds=("extraction",)
            )
        if claimed is None:
            return None
        target = JobState.FAILED_TERMINAL
        error_code: str | None = "EXTRACTION_RUNNER_FAILURE"
        result_payload: Mapping[str, Any] | None = None
        revision: Mapping[str, Any] | None = None
        try:
            identity = _parse_identity(claimed)
            with self._connections() as connection:
                revision = _load_revision(connection, identity[0])
            if revision["mime_type"] != identity[1] or revision["parser"] != identity[2]:
                raise FileSubmissionError("source expectation mismatch")
            data = self._blobs.read(
                str(revision["storage_key"]),
                expected_size=int(revision["byte_size"]),
                expected_sha256=str(revision["sha256"]),
            )
            execution = (
                _extract_utf8_text(data)
                if identity[1] == "text/plain"
                else self._sandbox.execute(
                    SandboxRequest(
                        input_bytes=data,
                        original_filename=str(revision["filename"]),
                        expected_media_type=identity[1],
                        expected_parser=identity[2],
                    )
                )
            )
            if execution.ok and execution.payload is not None:
                result_payload = _validated_result(execution.payload, identity[1])
                target, error_code = JobState.SUCCEEDED, None
            elif execution.failure is not None:
                error_code = execution.failure.parser_code or execution.failure.code.value
                target = (
                    JobState.FAILED_RETRYABLE
                    if execution.failure.retryable is True
                    or execution.failure.code
                    in {SandboxFailureCode.SANDBOX_LAUNCH_FAILED, SandboxFailureCode.PARSER_TIMEOUT}
                    else JobState.FAILED_TERMINAL
                )
        except FileSubmissionError:
            # Expected local-source failures are terminal and deliberately reveal no path.
            error_code = "SOURCE_BLOB_UNAVAILABLE"
        except Exception as error:
            # Programming/DB/protocol defects must remain observable to the supervisor.
            # Log only an opaque correlation id and exception class, never parser text,
            # source bytes, paths, SQL, or credentials.
            correlation_id = uuid4().hex
            _LOGGER.exception(
                "unexpected extraction failure correlation_id=%s exception_type=%s",
                correlation_id,
                type(error).__name__,
            )
            raise

        if (
            target is JobState.FAILED_RETRYABLE
            and claimed.lease_generation >= _MAX_EXTRACTION_ATTEMPTS
        ):
            target = JobState.FAILED_TERMINAL

        safe_result: dict[str, object] = (
            {
                "revision_id": str(revision["id"]),
                "anchor_set_hash": str(result_payload["anchor_set_hash"]),
                "block_count": len(result_payload["blocks"]),
            }
            if target is JobState.SUCCEEDED and revision is not None and result_payload is not None
            else {"outcome": "failed"}
        )

        def effect(cursor: Any) -> None:
            if revision is None:
                return
            if target is JobState.SUCCEEDED and result_payload is not None:
                _persist_success(cursor, claimed, revision, result_payload)
            else:
                _persist_failure(
                    cursor,
                    claimed,
                    revision,
                    error_code or "EXTRACTION_RUNNER_FAILURE",
                    terminal=target is JobState.FAILED_TERMINAL,
                )

        try:
            with self._connections() as connection:
                self._queue.complete_with_effects(
                    connection,
                    claimed,
                    target_state=target,
                    result=safe_result,
                    error_code=error_code,
                    effect=effect,
                )
        except StaleLeaseError:
            return None
        if target is JobState.FAILED_RETRYABLE:
            try:
                with self._connections() as connection:
                    self._queue.requeue_retryable(
                        connection,
                        job_id=claimed.id,
                        expected_lease_generation=claimed.lease_generation,
                    )
            except StaleLeaseError:
                # Another extraction worker may have reconciled and claimed or
                # terminally resolved this exact logical job after our fenced
                # completion. Verify that durable winner rather than treating
                # every stale response as benign: missing/wrong/unchanged rows
                # remain real supervision failures.
                with self._connections() as connection:
                    if not _retry_requeue_has_benign_winner(
                        connection,
                        job_id=claimed.id,
                        expected_generation=claimed.lease_generation,
                    ):
                        raise
        return safe_result


def _reconcile_retryable_extractions(
    connection: psycopg.Connection[dict[str, Any]],
) -> None:
    """Close the crash window between retryable completion and explicit requeue.

    This is deliberately extraction-only. Generation jobs retain their
    existing supervision semantics. A worker may die after fenced completion
    commits but before ``requeue_retryable`` begins; the next polling worker
    repairs that durable intermediate state before claiming new work.
    """

    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE jobs
                SET state = 'pending', error_code = NULL,
                    updated_at = clock_timestamp()
                WHERE kind = 'extraction'
                  AND state = 'failed_retryable'
                  AND lease_generation < %s
                  AND lease_token IS NULL
                """,
                (_MAX_EXTRACTION_ATTEMPTS,),
            )
            cursor.execute(
                """
                WITH terminal_jobs AS (
                    SELECT id, payload_json->>'revision_id' AS revision_id
                    FROM jobs
                    WHERE kind = 'extraction'
                      AND state = 'failed_retryable'
                      AND lease_generation >= %s
                      AND lease_token IS NULL
                    FOR UPDATE
                ), repaired_revisions AS (
                    UPDATE source_revisions revision
                    SET processing_state = 'failed'
                    FROM terminal_jobs job
                    WHERE revision.id::text = job.revision_id
                      AND revision.is_current
                      AND revision.processing_state = 'queued'
                    RETURNING revision.id, job.id AS job_id
                )
                UPDATE jobs job
                SET state = 'failed_terminal', updated_at = clock_timestamp()
                FROM repaired_revisions repair
                WHERE job.id = repair.job_id
                RETURNING job.id, repair.id AS revision_id
                """,
                (_MAX_EXTRACTION_ATTEMPTS,),
            )
            repairs = tuple(cursor.fetchall())
            for repair in repairs:
                _append_extraction_activity(
                    cursor,
                    revision_id=repair["revision_id"],
                    event_type="source_revision.failed",
                    job_id=repair["id"],
                    reconciled=True,
                    metadata={"state": "failed", "reconciled": True},
                )


def _retry_requeue_has_benign_winner(
    connection: psycopg.Connection[dict[str, Any]],
    *,
    job_id: UUID,
    expected_generation: int,
) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT kind, state, lease_generation FROM jobs WHERE id = %s",
            (job_id,),
        )
        row = cursor.fetchone()
    if row is None or row["kind"] != "extraction":
        return False
    generation = row["lease_generation"]
    if isinstance(generation, bool) or not isinstance(generation, int):
        return False
    state = row["state"]
    if state == "pending":
        return generation >= expected_generation
    if state == "running":
        return generation > expected_generation
    if state == "failed_retryable":
        return generation > expected_generation
    if state in {"succeeded", "failed_terminal"}:
        return generation >= expected_generation
    return False


def _parse_identity(claimed: ClaimedJob) -> tuple[UUID, str, ParserIdentity]:
    payload = claimed.payload
    if set(payload) != {"revision_id", "media_type", "parser"}:
        raise ValueError("invalid extraction job")
    parser = payload["parser"]
    if not isinstance(parser, Mapping) or set(parser) != {"name", "version"}:
        raise ValueError("invalid extraction job")
    return (
        UUID(str(payload["revision_id"])),
        str(payload["media_type"]),
        ParserIdentity(str(parser["name"]), str(parser["version"])),
    )


def _load_revision(connection: Any, revision_id: UUID) -> Mapping[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT revision.id, revision.filename, revision.mime_type,
                   revision.byte_size, revision.sha256, revision.storage_key,
                   submission.session_id, session_row.room_id
            FROM source_revisions revision
            JOIN submissions submission ON submission.id=revision.submission_id
            JOIN talk_sessions session_row ON session_row.id=submission.session_id
            WHERE revision.id = %s AND revision.is_current
              AND revision.processing_state = 'queued'
            """,
            (revision_id,),
        )
        row = cursor.fetchone()
    if row is None or row["storage_key"] is None:
        raise FileSubmissionError("queued source revision is unavailable")
    parser_by_media = {
        "application/pdf": ParserIdentity("pypdfium2", "5.12.1"),
        "image/png": ParserIdentity("pillow+tesseract-cli", "12.3.0+5.3.0"),
        "image/jpeg": ParserIdentity("pillow+tesseract-cli", "12.3.0+5.3.0"),
        "application/x-hwp": ParserIdentity("pyhwp", "0.1b15"),
        "application/x-hwpx": ParserIdentity("hwpxlib", "1.0.9"),
        "text/plain": ParserIdentity("builtin-utf8-text", "1.0.0"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ParserIdentity(
            "stdlib-docx", "1.0.0"
        ),
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ParserIdentity(
            "libreoffice+pypdfium2+tesseract-cli", "1.0.0"
        ),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ParserIdentity(
            "stdlib-xlsx", "1.0.0"
        ),
    }
    loaded: dict[str, Any] = dict(row)
    loaded["parser"] = parser_by_media.get(row["mime_type"])
    return loaded


def _extract_utf8_text(data: bytes) -> SandboxExecution:
    """Decode bounded plain text without invoking a document parser process."""

    source_hash = hashlib.sha256(data).hexdigest()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return SandboxExecution(
            ok=False,
            payload=None,
            failure=_sandbox_failure(
                SandboxFailureCode.PARSER_REPORTED_FAILURE,
                parser_code="INVALID_TEXT_ENCODING",
                retryable=False,
            ),
            source_sha256=source_hash,
            exit_code=2,
            duration_ms=0,
            stdout_bytes=0,
            stderr_bytes=0,
            killed=False,
        )
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks: list[dict[str, object]] = []
    profile_hash = _PROFILE_BY_MEDIA["text/plain"]
    total_chars = 0
    truncated = False
    for line_number, raw_line in enumerate(io.StringIO(normalized), start=1):
        line = raw_line.removesuffix("\n")
        if not line.strip():
            continue
        if len(blocks) >= 10_000 or total_chars >= 1_000_000:
            truncated = True
            break
        remaining = min(100_000, 1_000_000 - total_chars)
        if len(line) > remaining:
            line = line[:remaining]
            truncated = True
        total_chars += len(line)
        anchor: dict[str, object] = {
            "schema_version": 1,
            "kind": "text_line",
            "source_sha256": source_hash,
            "extraction_profile_hash": profile_hash,
            "locator": {"line": line_number, "start": 0, "end": len(line)},
            "text_fingerprint": hashlib.sha256(line.encode("utf-8")).hexdigest(),
        }
        blocks.append(
            {
                "ordinal": len(blocks),
                "text": line,
                "block_type": "text_line",
                "confidence": 1.0,
                "anchor": anchor,
                "anchor_hash": canonical_sha256(anchor),
            }
        )
        if truncated:
            break
    if not blocks:
        return SandboxExecution(
            ok=False,
            payload=None,
            failure=_sandbox_failure(
                SandboxFailureCode.PARSER_REPORTED_FAILURE,
                parser_code="EMPTY_TEXT",
                retryable=False,
            ),
            source_sha256=source_hash,
            exit_code=2,
            duration_ms=0,
            stdout_bytes=0,
            stderr_bytes=0,
            killed=False,
        )
    anchor_hashes = [str(block["anchor_hash"]) for block in blocks]
    result: dict[str, object] = {
        "source_sha256": source_hash,
        "media_type": "text/plain",
        "parser": {"name": "builtin-utf8-text", "version": "1.0.0"},
        "normalization_profile": "nfc-lf-v1",
        "config_profile_hash": profile_hash,
        "anchor_set_hash": canonical_sha256(
            {"schema_version": 1, "anchor_hashes": anchor_hashes}
        ),
        "blocks": blocks,
        "warnings": ["TRUNCATED_TO_EXTRACTION_LIMIT"] if truncated else [],
    }
    return SandboxExecution(
        ok=True,
        payload={"schema_version": 1, "ok": True, "result": result},
        failure=None,
        source_sha256=source_hash,
        exit_code=0,
        duration_ms=0,
        stdout_bytes=0,
        stderr_bytes=0,
        killed=False,
    )


def _validated_result(payload: Mapping[str, Any], media_type: str) -> Mapping[str, Any]:
    result = payload.get("result")
    if not isinstance(result, Mapping) or result.get("config_profile_hash") != _PROFILE_BY_MEDIA[media_type]:
        raise ValueError("unapproved extraction profile")
    if not isinstance(result.get("blocks"), list) or not result["blocks"]:
        raise ValueError("empty extraction")
    return result


def _persist_success(cursor: Any, claimed: ClaimedJob, revision: Mapping[str, Any], result: Mapping[str, Any]) -> None:
    run_id = uuid4()
    parser = result["parser"]
    cursor.execute(
        """
        INSERT INTO extraction_runs (
            id, source_revision_id, parser_name, parser_version, newline_policy,
            unicode_normalization_profile, config_hash, anchor_schema_version,
            attempt_no, status, completed_at, job_attempt_id
        ) VALUES (%s, %s, %s, %s, 'lf', 'nfc', %s, '1', %s, 'succeeded', clock_timestamp(), %s)
        """,
        (
            run_id,
            revision["id"],
            parser["name"],
            parser["version"],
            result["config_profile_hash"],
            claimed.lease_generation,
            claimed.attempt_id,
        ),
    )
    for block in result["blocks"]:
        cursor.execute(
            """
            INSERT INTO source_anchors (
                id, extraction_run_id, source_revision_id, ordinal, block_type,
                text, confidence, anchor_json, canonical_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid4(), run_id, revision["id"], block["ordinal"], block["block_type"],
                block["text"], block["confidence"], Jsonb(block["anchor"]), block["anchor_hash"],
            ),
        )
    cursor.execute(
        """
        UPDATE source_revisions
        SET approved_extraction_run_id = %s, processing_state = 'ready'
        WHERE id = %s AND is_current AND processing_state = 'queued'
        """,
        (run_id, revision["id"]),
    )
    if cursor.rowcount != 1:
        raise StaleLeaseError("source revision is no longer current and queued")
    _append_extraction_activity(
        cursor,
        revision_id=revision["id"],
        event_type="source_revision.ready",
        job_attempt_id=claimed.attempt_id,
        room_id=revision["room_id"],
        session_id=revision["session_id"],
        metadata={"state": "ready", "block_count": len(result["blocks"])},
    )


def _persist_failure(
    cursor: Any,
    claimed: ClaimedJob,
    revision: Mapping[str, Any],
    error_code: str,
    *,
    terminal: bool,
) -> None:
    cursor.execute(
        """
        INSERT INTO extraction_runs (
            id, source_revision_id, parser_name, parser_version, newline_policy,
            unicode_normalization_profile, config_hash, anchor_schema_version,
            attempt_no, status, error_code, completed_at, job_attempt_id
        ) VALUES (%s, %s, %s, %s, 'lf', 'nfc', %s, '1', %s, 'failed', %s, clock_timestamp(), %s)
        """,
        (
            uuid4(), revision["id"], revision["parser"].name, revision["parser"].version,
            _PROFILE_BY_MEDIA[str(revision["mime_type"])], claimed.lease_generation,
            error_code, claimed.attempt_id,
        ),
    )
    if terminal:
        cursor.execute(
            """UPDATE source_revisions SET processing_state = 'failed'
               WHERE id = %s AND is_current AND processing_state = 'queued'
               RETURNING id""",
            (revision["id"],),
        )
        if cursor.fetchone() is None:
            raise StaleLeaseError("source revision is no longer current and queued")
        _append_extraction_activity(
            cursor,
            revision_id=revision["id"],
            event_type="source_revision.failed",
            job_attempt_id=claimed.attempt_id,
            room_id=revision["room_id"],
            session_id=revision["session_id"],
            metadata={"state": "failed", "error_code": error_code},
        )


def _append_extraction_activity(
    cursor: Any,
    *,
    revision_id: UUID,
    event_type: str,
    job_attempt_id: UUID | None = None,
    job_id: UUID | None = None,
    reconciled: bool = False,
    room_id: UUID | None = None,
    session_id: UUID | None = None,
    metadata: Mapping[str, object],
) -> None:
    if room_id is None or session_id is None:
        cursor.execute(
            """SELECT session_row.room_id, submission.session_id
               FROM source_revisions revision
               JOIN submissions submission ON submission.id=revision.submission_id
               JOIN talk_sessions session_row ON session_row.id=submission.session_id
               WHERE revision.id=%s""",
            (revision_id,),
        )
        scope = cursor.fetchone()
        if scope is None:
            raise RuntimeError("source revision activity scope is unavailable")
        room_id, session_id = scope["room_id"], scope["session_id"]
    identity: dict[str, object] = {"revision_id": revision_id}
    if reconciled:
        identity.update(reconciled=True, job_id=job_id)
    else:
        identity["job_attempt_id"] = job_attempt_id
    ActivityService().append(
        cursor,
        event_key=build_event_key(event_type, **identity),
        event_type=event_type,
        actor_id=None,
        scope_type="session",
        room_id=room_id,
        session_id=session_id,
        entity_type="source_revision",
        entity_id=revision_id,
        metadata=dict(metadata),
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv if argv is not None else sys.argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parsed = parser.parse_args(arguments)
    from app.db import open_connection

    blob_store = LocalBlobStore(Path(os.environ.get("AXIT_BLOB_ROOT", ".axit-blobs")))
    worker = FileExtractionWorker(
        connection_factory=open_connection,
        blob_store=blob_store,
        sandbox_adapter=DockerSandboxAdapter(),
    )
    owner = f"file-worker-{os.getpid()}"
    next_sweep = 0.0
    while True:
        if time.monotonic() >= next_sweep:
            with open_connection() as connection:
                blob_store.sweep_orphans(connection)
            next_sweep = time.monotonic() + 60 * 60
        outcome = worker.run_once(owner)
        if parsed.once:
            return 0
        if outcome is None:
            time.sleep(0.25)


if __name__ == "__main__":
    raise SystemExit(main())
