"""Fenced, injection-only extraction runner for the Phase 2 durable queue.

This module deliberately does not choose a parser process or mount a sandbox.
The caller injects a reviewed ``SandboxAdapter`` (the Phase 2 IPC harness is
one such adapter) and a source loader that resolves a server-issued revision
ID.  Source bytes, storage locations, database URLs, and credentials never
appear in a durable job payload or job result.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import psycopg

from app.domain import JobState, StaleLeaseError
from app.queue_repository import ClaimedJob, PostgresJobQueue
from app.sandbox_ipc import (
    ParserIdentity,
    SandboxExecution,
    SandboxFailureCode,
    SandboxRequest,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RETRYABLE_SANDBOX_FAILURES = frozenset(
    {
        SandboxFailureCode.SANDBOX_LAUNCH_FAILED,
        SandboxFailureCode.PARSER_TIMEOUT,
    }
)


class ExtractionSourceError(RuntimeError):
    """Typed source-loading failure that is safe to persist on a job attempt."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        _require_error_code(code)
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class _RunnerFailure(RuntimeError):
    """Internal typed failure; its message is intentionally never persisted."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        _require_error_code(code)
        self.code = code
        self.retryable = retryable
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ExtractionSource:
    """Trusted server-side source material for one immutable revision."""

    revision_id: UUID
    input_bytes: bytes
    original_filename: str
    media_type: str
    parser: ParserIdentity


class ExtractionSourceLoader(Protocol):
    """Resolve a revision ID without exposing storage implementation details."""

    def load(self, revision_id: UUID) -> ExtractionSource:
        """Return exactly the immutable source selected by the durable job."""


class SandboxAdapter(Protocol):
    """Execute a secretless sandbox request outside every database transaction."""

    def execute(self, request: SandboxRequest) -> SandboxExecution:
        """Return a fully validated parser outcome with no raw logs."""


ConnectionFactory = Callable[
    [], AbstractContextManager[psycopg.Connection[dict[str, Any]]]
]


@dataclass(frozen=True, slots=True)
class ExtractionRunOutcome:
    """Safe supervision facts for one polling iteration."""

    job_id: UUID | None
    claimed: bool
    completed: bool
    stale_completion: bool
    target_state: JobState | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class _ExtractionJobPayload:
    revision_id: UUID
    media_type: str
    parser: ParserIdentity


@dataclass(frozen=True, slots=True)
class _Completion:
    target_state: JobState
    result: Mapping[str, object]
    error_code: str | None


class FencedExtractionRunner:
    """Claim one extraction job, execute outside SQL, then fence completion.

    A runner instance has no credentials or parser command of its own.  It can
    be exercised with a deterministic fake adapter in Phase 2 and later given
    the separately approved G0 container launcher without changing the queue
    or public API contract.
    """

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory,
        source_loader: ExtractionSourceLoader,
        sandbox_adapter: SandboxAdapter,
        queue: PostgresJobQueue | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._source_loader = source_loader
        self._sandbox_adapter = sandbox_adapter
        self._queue = queue or PostgresJobQueue()

    def run_once(
        self,
        *,
        owner: str,
        lease_seconds: int = 60,
    ) -> ExtractionRunOutcome:
        """Run at most one extraction job using short claim/complete transactions."""

        with self._connection_factory() as connection:
            claimed = self._queue.claim_next(
                connection,
                owner=owner,
                lease_seconds=lease_seconds,
                kinds=("extraction",),
            )
        if claimed is None:
            return ExtractionRunOutcome(
                job_id=None,
                claimed=False,
                completed=False,
                stale_completion=False,
                target_state=None,
                error_code=None,
            )

        completion = self._execute_claimed_job(claimed)
        try:
            with self._connection_factory() as connection:
                self._queue.complete(
                    connection,
                    claimed,
                    target_state=completion.target_state,
                    result=completion.result,
                    error_code=completion.error_code,
                )
        except StaleLeaseError:
            return ExtractionRunOutcome(
                job_id=claimed.id,
                claimed=True,
                completed=False,
                stale_completion=True,
                target_state=completion.target_state,
                error_code=completion.error_code,
            )
        return ExtractionRunOutcome(
            job_id=claimed.id,
            claimed=True,
            completed=True,
            stale_completion=False,
            target_state=completion.target_state,
            error_code=completion.error_code,
        )

    def _execute_claimed_job(self, claimed: ClaimedJob) -> _Completion:
        try:
            payload = _parse_extraction_payload(claimed.payload)
            source = self._source_loader.load(payload.revision_id)
            _validate_loaded_source(payload, source)
            execution = self._sandbox_adapter.execute(
                SandboxRequest(
                    input_bytes=source.input_bytes,
                    original_filename=source.original_filename,
                    expected_media_type=payload.media_type,
                    expected_parser=payload.parser,
                )
            )
            return _completion_from_sandbox(payload, source, execution)
        except ExtractionSourceError as error:
            return _failed_completion(error.code, retryable=error.retryable)
        except _RunnerFailure as error:
            return _failed_completion(error.code, retryable=error.retryable)
        except Exception:
            # Never serialize exception text: it can contain source or driver
            # details. A future monitor can map this stable code to guidance.
            return _failed_completion("EXTRACTION_RUNNER_FAILURE", retryable=True)


def _parse_extraction_payload(payload: Mapping[str, object]) -> _ExtractionJobPayload:
    if set(payload) != {"revision_id", "media_type", "parser"}:
        raise _RunnerFailure("INVALID_JOB_PAYLOAD", retryable=False)
    revision_value = payload["revision_id"]
    media_type = payload["media_type"]
    parser_value = payload["parser"]
    if not isinstance(revision_value, str) or not isinstance(media_type, str):
        raise _RunnerFailure("INVALID_JOB_PAYLOAD", retryable=False)
    if not isinstance(parser_value, Mapping) or set(parser_value) != {"name", "version"}:
        raise _RunnerFailure("INVALID_JOB_PAYLOAD", retryable=False)
    parser_name = parser_value["name"]
    parser_version = parser_value["version"]
    if not isinstance(parser_name, str) or not isinstance(parser_version, str):
        raise _RunnerFailure("INVALID_JOB_PAYLOAD", retryable=False)
    try:
        return _ExtractionJobPayload(
            revision_id=UUID(revision_value),
            media_type=media_type,
            parser=ParserIdentity(name=parser_name, version=parser_version),
        )
    except (ValueError, AttributeError) as error:
        raise _RunnerFailure("INVALID_JOB_PAYLOAD", retryable=False) from error


def _validate_loaded_source(
    payload: _ExtractionJobPayload,
    source: ExtractionSource,
) -> None:
    if source.revision_id != payload.revision_id:
        raise _RunnerFailure("SOURCE_REVISION_MISMATCH", retryable=False)
    if source.media_type != payload.media_type or source.parser != payload.parser:
        raise _RunnerFailure("SOURCE_EXPECTATION_MISMATCH", retryable=False)
    if not isinstance(source.input_bytes, bytes):
        raise _RunnerFailure("SOURCE_BYTES_INVALID", retryable=False)


def _completion_from_sandbox(
    payload: _ExtractionJobPayload,
    source: ExtractionSource,
    execution: SandboxExecution,
) -> _Completion:
    if not execution.ok:
        if execution.failure is None:
            raise _RunnerFailure("INVALID_SANDBOX_OUTCOME", retryable=False)
        code = execution.failure.parser_code or execution.failure.code.value
        _require_error_code(code)
        retryable = (
            execution.failure.retryable
            if execution.failure.retryable is not None
            else execution.failure.code in _RETRYABLE_SANDBOX_FAILURES
        )
        return _failed_completion(code, retryable=retryable)

    expected_sha256 = hashlib.sha256(source.input_bytes).hexdigest()
    if execution.source_sha256 != expected_sha256 or execution.payload is None:
        raise _RunnerFailure("INVALID_SANDBOX_OUTCOME", retryable=False)
    result = execution.payload.get("result")
    if not isinstance(result, Mapping):
        raise _RunnerFailure("INVALID_SANDBOX_OUTCOME", retryable=False)
    result_source_hash = result.get("source_sha256")
    anchor_set_hash = result.get("anchor_set_hash")
    blocks = result.get("blocks")
    if (
        result_source_hash != expected_sha256
        or not isinstance(anchor_set_hash, str)
        or _SHA256.fullmatch(anchor_set_hash) is None
        or not isinstance(blocks, list)
    ):
        raise _RunnerFailure("INVALID_SANDBOX_OUTCOME", retryable=False)
    return _Completion(
        target_state=JobState.SUCCEEDED,
        result={
            "revision_id": str(payload.revision_id),
            "source_sha256": expected_sha256,
            "anchor_set_hash": anchor_set_hash,
            "block_count": len(blocks),
            "duration_ms": max(0, execution.duration_ms),
        },
        error_code=None,
    )


def _failed_completion(code: str, *, retryable: bool) -> _Completion:
    _require_error_code(code)
    return _Completion(
        target_state=(JobState.FAILED_RETRYABLE if retryable else JobState.FAILED_TERMINAL),
        result={"outcome": "failed"},
        error_code=code,
    )


def _require_error_code(code: str) -> None:
    if not code or len(code) > 128 or not code.replace("_", "").isalnum():
        raise ValueError("error code must be a bounded alphanumeric underscore identifier")
