"""Bounded automatic retry for live-provider research jobs only.

Summary stays on the deterministic MockProvider, so its retryable failures
are permanent bugs, not transient ones -- it keeps the pre-existing
manual-retry semantics. Research now calls a live external API (Grok + web
search), so a bounded number of automatic retries is worth having.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Literal
from uuid import UUID, uuid4

from app.domain import JobState
from app.generation_runner import GenerationExecution
from app.generation_worker import FencedGenerationWorker
from app.queue_repository import ClaimedJob


def _claimed_job(kind: Literal["summary", "research"], lease_generation: int) -> ClaimedJob:
    snapshot_id = uuid4()
    return ClaimedJob(
        id=uuid4(),
        logical_key=f"{kind}:{snapshot_id}",
        kind=kind,
        payload={
            "snapshot_id": str(snapshot_id),
            "kind": kind,
            "pipeline_version": "test-v1",
        },
        owner="test-worker",
        lease_generation=lease_generation,
        lease_token=uuid4(),
        attempt_id=uuid4(),
    )


def _retryable_failure(kind: Literal["summary", "research"]) -> GenerationExecution:
    snapshot_id = uuid4()
    return GenerationExecution(
        snapshot_id=snapshot_id,
        kind=kind,
        pipeline_version="test-v1",
        target_state=JobState.FAILED_RETRYABLE,
        result={
            "snapshot_id": str(snapshot_id),
            "kind": kind,
            "status": "failed_retryable",
            "error_code": "transient_boom",
        },
        error_code="transient_boom",
        retryable=True,
    )


class _FakeRunner:
    def __init__(self, execution: GenerationExecution) -> None:
        self._execution = execution

    def execute(self, connection: object, claimed: ClaimedJob) -> GenerationExecution:
        return self._execution


class _FakeQueue:
    def __init__(self, claimed: ClaimedJob) -> None:
        self._claimed = claimed
        self.completed_target_states: list[JobState] = []
        self.requeue_calls: list[tuple[UUID, int]] = []

    def claim_next(self, connection: object, *, owner: str, lease_seconds: int, kinds: object) -> ClaimedJob:
        return self._claimed

    def complete_with_effects(
        self,
        connection: object,
        claimed: ClaimedJob,
        *,
        target_state: JobState,
        result: object,
        error_code: str | None,
        effect: object,
    ) -> None:
        self.completed_target_states.append(target_state)

    def requeue_retryable(
        self, connection: object, *, job_id: UUID, expected_lease_generation: int
    ) -> None:
        self.requeue_calls.append((job_id, expected_lease_generation))


@contextmanager
def _fake_connection_factory() -> Any:
    yield None


def test_research_retryable_failure_is_requeued_before_max_attempts() -> None:
    claimed = _claimed_job("research", lease_generation=1)
    queue = _FakeQueue(claimed)
    worker = FencedGenerationWorker(
        connection_factory=_fake_connection_factory,
        runner=_FakeRunner(_retryable_failure("research")),  # type: ignore[arg-type]
        queue=queue,  # type: ignore[arg-type]
    )

    worker.run_once(owner="test-owner")

    assert queue.completed_target_states == [JobState.FAILED_RETRYABLE]
    assert queue.requeue_calls == [(claimed.id, claimed.lease_generation)]


def test_research_retryable_failure_becomes_terminal_at_max_attempts() -> None:
    claimed = _claimed_job("research", lease_generation=3)
    queue = _FakeQueue(claimed)
    worker = FencedGenerationWorker(
        connection_factory=_fake_connection_factory,
        runner=_FakeRunner(_retryable_failure("research")),  # type: ignore[arg-type]
        queue=queue,  # type: ignore[arg-type]
    )

    worker.run_once(owner="test-owner")

    assert queue.completed_target_states == [JobState.FAILED_TERMINAL]
    assert queue.requeue_calls == []


def test_summary_retryable_failure_keeps_manual_retry_semantics() -> None:
    """Summary runs on the deterministic mock, so it must never auto-retry."""

    claimed = _claimed_job("summary", lease_generation=1)
    queue = _FakeQueue(claimed)
    worker = FencedGenerationWorker(
        connection_factory=_fake_connection_factory,
        runner=_FakeRunner(_retryable_failure("summary")),  # type: ignore[arg-type]
        queue=queue,  # type: ignore[arg-type]
    )

    worker.run_once(owner="test-owner")

    assert queue.completed_target_states == [JobState.FAILED_RETRYABLE]
    assert queue.requeue_calls == []
