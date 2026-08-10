"""Fenced supervision for Phase 3's local MockProvider generation jobs.

The provider call is intentionally outside PostgreSQL transactions.  Its
result reaches durable tables only through ``PostgresJobQueue``'s lease/token
CAS and the repository callback, so a reclaimed or stale worker cannot leave
behind a summary, citation, or aggregate-state change.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
import logging
from typing import Any, Final, Literal, cast
from uuid import UUID, uuid4

import psycopg

from app.domain import JobState, StaleLeaseError
from app.generation_repository import GenerationRepository
from app.generation_runner import (
    GenerationExecution,
    GenerationRunner,
    GenerationRunnerError,
)
from app.queue_repository import ClaimedJob, PostgresJobQueue


_GENERATION_KINDS: Final[tuple[str, str]] = ("summary", "research")
_FAILURE_CODE: Final = "generation_runner_failure"
# Research is the only generation kind backed by a live external call (Grok +
# web search), so it is the only one worth an automatic bounded retry — a
# transient tool/validation hiccup there is plausible in a way a MockProvider
# failure never is. Summary jobs keep the pre-existing manual-only semantics.
# 3 = 1 initial attempt + up to 2 automatic retries.
_MAX_RESEARCH_ATTEMPTS: Final = 3
_LOGGER = logging.getLogger(__name__)


def _log_unexpected(stage: str, error: Exception) -> None:
    _LOGGER.exception(
        "unexpected generation %s failure correlation_id=%s exception_type=%s",
        stage, uuid4().hex, type(error).__name__,
    )

ConnectionFactory = Callable[
    [], AbstractContextManager[psycopg.Connection[dict[str, Any]]]
]


@dataclass(frozen=True, slots=True)
class GenerationWorkerOutcome:
    """Safe supervisor facts for one poll; never include provider/source data."""

    job_id: UUID | None
    claimed: bool
    completed: bool
    stale_completion: bool
    target_state: JobState | None
    error_code: str | None


class FencedGenerationWorker:
    """Claim one summary/research job, execute, then persist through fencing."""

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory,
        runner: GenerationRunner | None = None,
        repository: GenerationRepository | None = None,
        queue: PostgresJobQueue | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._runner = runner or GenerationRunner()
        self._repository = repository or GenerationRepository()
        self._queue = queue or PostgresJobQueue()

    def run_once(
        self,
        *,
        owner: str,
        lease_seconds: int = 300,
        kinds: tuple[Literal["summary", "research"], ...] = ("summary", "research"),
    ) -> GenerationWorkerOutcome:
        """Run at most one canonical generation job without leaking content."""

        if not kinds or any(kind not in _GENERATION_KINDS for kind in kinds):
            raise ValueError("generation worker kinds must be summary and/or research")

        with self._connection_factory() as connection:
            claimed = self._queue.claim_next(
                connection,
                owner=owner,
                lease_seconds=lease_seconds,
                kinds=kinds,
            )
        if claimed is None:
            return GenerationWorkerOutcome(
                job_id=None,
                claimed=False,
                completed=False,
                stale_completion=False,
                target_state=None,
                error_code=None,
            )

        execution = _cap_research_retries(self._execute_safely(claimed), claimed)
        try:
            self._complete(claimed, execution)
        except StaleLeaseError:
            return _outcome(claimed, execution, completed=False, stale_completion=True)
        except Exception as error:
            _log_unexpected("completion", error)
            raise
        if execution is not None and execution.target_state is JobState.FAILED_RETRYABLE:
            self._retry_research(claimed)
        return _outcome(claimed, execution, completed=True, stale_completion=False)

    def _retry_research(self, claimed: ClaimedJob) -> None:
        """Immediately requeue a research job that still has attempts left.

        Summary jobs are untouched here — MockProvider failures are permanent
        bugs, not transient ones, so they keep the pre-existing manual-retry
        semantics.
        """

        if claimed.kind != "research":
            return
        try:
            with self._connection_factory() as connection:
                self._queue.requeue_retryable(
                    connection,
                    job_id=claimed.id,
                    expected_lease_generation=claimed.lease_generation,
                )
        except StaleLeaseError:
            # Another worker already reconciled this exact attempt (e.g. its
            # own lease-expiry reclaim beat us to it); the job is not lost,
            # so there is nothing more to do here.
            pass

    def _execute_safely(self, claimed: ClaimedJob) -> GenerationExecution | None:
        try:
            with self._connection_factory() as connection:
                return self._runner.execute(connection, claimed)
        except GenerationRunnerError:
            return _failure_for_claim(claimed)
        except Exception as error:
            _log_unexpected("execution", error)
            raise

    def _complete(self, claimed: ClaimedJob, execution: GenerationExecution | None) -> None:
        if execution is None:
            # An invalid job payload has no proven generation-run identity to
            # update.  The fenced job itself is still terminal so it cannot
            # spin forever; no domain artifact is written.
            with self._connection_factory() as connection:
                self._queue.complete(
                    connection,
                    claimed,
                    target_state=JobState.FAILED_TERMINAL,
                    result={"outcome": "failed", "error_code": _FAILURE_CODE},
                    error_code=_FAILURE_CODE,
                )
            return
        with self._connection_factory() as connection:
            self._queue.complete_with_effects(
                connection,
                claimed,
                target_state=execution.target_state,
                result=execution.result,
                error_code=execution.error_code,
                effect=execution.fenced_effect(self._repository),
            )


def _cap_research_retries(
    execution: GenerationExecution | None, claimed: ClaimedJob
) -> GenerationExecution | None:
    """After the last allowed attempt, a retryable research failure becomes terminal."""

    if (
        execution is None
        or execution.target_state is not JobState.FAILED_RETRYABLE
        or claimed.kind != "research"
        or claimed.lease_generation < _MAX_RESEARCH_ATTEMPTS
    ):
        return execution
    return replace(
        execution,
        target_state=JobState.FAILED_TERMINAL,
        retryable=False,
        result={**execution.result, "status": JobState.FAILED_TERMINAL.value},
    )


def _failure_for_claim(claimed: ClaimedJob) -> GenerationExecution | None:
    """Build a safe terminal effect only when payload identity is validated."""

    raw_snapshot_id = claimed.payload.get("snapshot_id")
    raw_kind = claimed.payload.get("kind")
    raw_pipeline = claimed.payload.get("pipeline_version")
    if (
        not isinstance(raw_snapshot_id, str)
        or raw_kind not in _GENERATION_KINDS
        or raw_kind != claimed.kind
        or not isinstance(raw_pipeline, str)
        or not raw_pipeline.strip()
    ):
        return None
    try:
        snapshot_id = UUID(raw_snapshot_id)
    except ValueError:
        return None
    return GenerationExecution(
        snapshot_id=snapshot_id,
        kind=cast(Literal["summary", "research"], raw_kind),
        pipeline_version=raw_pipeline,
        target_state=JobState.FAILED_TERMINAL,
        result={
            "snapshot_id": str(snapshot_id),
            "kind": raw_kind,
            "status": JobState.FAILED_TERMINAL.value,
            "error_code": _FAILURE_CODE,
        },
        error_code=_FAILURE_CODE,
        retryable=False,
    )


def _outcome(
    claimed: ClaimedJob,
    execution: GenerationExecution | None,
    *,
    completed: bool,
    stale_completion: bool,
) -> GenerationWorkerOutcome:
    return GenerationWorkerOutcome(
        job_id=claimed.id,
        claimed=True,
        completed=completed,
        stale_completion=stale_completion,
        target_state=(execution.target_state if execution is not None else None),
        error_code=(execution.error_code if execution is not None else _FAILURE_CODE),
    )
