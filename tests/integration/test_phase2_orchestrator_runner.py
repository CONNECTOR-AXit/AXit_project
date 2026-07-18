"""Real-PostgreSQL proof for the Phase 2 fenced extraction runner."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.db import open_connection
from app.domain import JobState
from app.migrations import upgrade_database
from app.orchestrator_runner import (
    ExtractionSource,
    ExtractionSourceError,
    FencedExtractionRunner,
)
from app.queue_repository import PostgresJobQueue
from app.sandbox_ipc import (
    ParserIdentity,
    SandboxExecution,
    SandboxFailure,
    SandboxFailureCode,
    SandboxRequest,
)


pytestmark = pytest.mark.integration


@contextmanager
def _temporary_database() -> Iterator[str]:
    configured_url = os.environ.get("AXIT_TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("AXIT_TEST_DATABASE_URL is required for Phase 2 PostgreSQL integration")
    connection_info = conninfo_to_dict(configured_url)
    database_name = "axit_phase2_runner_" + uuid4().hex
    maintenance_info = dict(connection_info)
    maintenance_info["dbname"] = "postgres"
    target_info = dict(connection_info)
    target_info["dbname"] = database_name
    target_url = make_conninfo(**target_info)
    with psycopg.connect(**maintenance_info, autocommit=True) as maintenance:
        maintenance.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        try:
            yield target_url
        finally:
            maintenance.execute(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            maintenance.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))


@pytest.fixture
def runner_database_url() -> Iterator[str]:
    with _temporary_database() as database_url:
        upgrade_database(database_url)
        yield database_url


@dataclass
class _FakeLoader:
    source: ExtractionSource
    calls: list[UUID] = field(default_factory=list)

    def load(self, revision_id: UUID) -> ExtractionSource:
        self.calls.append(revision_id)
        return self.source


@dataclass
class _FailingLoader:
    code: str
    retryable: bool
    calls: int = 0

    def load(self, revision_id: UUID) -> ExtractionSource:
        del revision_id
        self.calls += 1
        raise ExtractionSourceError(self.code, retryable=self.retryable)


@dataclass
class _FakeAdapter:
    execution: SandboxExecution
    requests: list[SandboxRequest] = field(default_factory=list)

    def execute(self, request: SandboxRequest) -> SandboxExecution:
        self.requests.append(request)
        return self.execution


def _source() -> ExtractionSource:
    return ExtractionSource(
        revision_id=uuid4(),
        input_bytes=b"immutable text revision",
        original_filename="agenda.txt",
        media_type="text/plain",
        parser=ParserIdentity(name="phase2-fixture-parser", version="1.0"),
    )


def _success_execution(source: ExtractionSource) -> SandboxExecution:
    source_hash = hashlib.sha256(source.input_bytes).hexdigest()
    return SandboxExecution(
        ok=True,
        payload={
            "result": {
                "source_sha256": source_hash,
                "anchor_set_hash": "a" * 64,
                "blocks": [{"ordinal": 0}],
            }
        },
        failure=None,
        source_sha256=source_hash,
        exit_code=0,
        duration_ms=7,
        stdout_bytes=0,
        stderr_bytes=0,
        killed=False,
    )


def _payload(source: ExtractionSource) -> dict[str, object]:
    return {
        "revision_id": str(source.revision_id),
        "media_type": source.media_type,
        "parser": {
            "name": source.parser.name,
            "version": source.parser.version,
        },
    }


def _runner(
    database_url: str,
    loader: object,
    adapter: object,
) -> FencedExtractionRunner:
    return FencedExtractionRunner(
        connection_factory=lambda: open_connection(database_url),
        source_loader=loader,  # type: ignore[arg-type]
        sandbox_adapter=adapter,  # type: ignore[arg-type]
    )


def test_runner_claims_only_extraction_and_persists_a_safe_fenced_result(
    runner_database_url: str,
) -> None:
    queue = PostgresJobQueue()
    source = _source()
    loader = _FakeLoader(source)
    adapter = _FakeAdapter(_success_execution(source))
    with open_connection(runner_database_url) as connection:
        summary = queue.enqueue(
            connection,
            logical_key="phase2:runner-summary-first",
            kind="summary",
            payload={"snapshot_id": str(uuid4())},
        )
        extraction = queue.enqueue(
            connection,
            logical_key="phase2:runner-extraction",
            kind="extraction",
            payload=_payload(source),
        )

    outcome = _runner(runner_database_url, loader, adapter).run_once(owner="runner-a")

    assert outcome.job_id == extraction.id
    assert outcome.completed is True
    assert outcome.target_state is JobState.SUCCEEDED
    assert loader.calls == [source.revision_id]
    assert len(adapter.requests) == 1
    request = adapter.requests[0]
    assert request.input_bytes == source.input_bytes
    assert request.expected_media_type == "text/plain"
    assert not hasattr(request, "database_url")
    assert not hasattr(request, "storage_key")
    with open_connection(runner_database_url) as connection:
        assert queue.fetch_job(connection, job_id=summary.id).state is JobState.PENDING
        assert queue.fetch_job(connection, job_id=extraction.id).state is JobState.SUCCEEDED
        assert queue.result_count(connection, job_id=extraction.id) == 1


def test_invalid_payload_finishes_terminally_without_calling_loader_or_adapter(
    runner_database_url: str,
) -> None:
    queue = PostgresJobQueue()
    source = _source()
    loader = _FakeLoader(source)
    adapter = _FakeAdapter(_success_execution(source))
    with open_connection(runner_database_url) as connection:
        job = queue.enqueue(
            connection,
            logical_key="phase2:runner-invalid-payload",
            kind="extraction",
            payload={"revision_id": str(source.revision_id), "source_bytes": "forbidden"},
        )

    outcome = _runner(runner_database_url, loader, adapter).run_once(owner="runner-a")

    assert outcome.completed is True
    assert outcome.target_state is JobState.FAILED_TERMINAL
    assert outcome.error_code == "INVALID_JOB_PAYLOAD"
    assert loader.calls == []
    assert adapter.requests == []
    with open_connection(runner_database_url) as connection:
        assert queue.fetch_job(connection, job_id=job.id).state is JobState.FAILED_TERMINAL
        assert queue.result_count(connection, job_id=job.id) == 0


def test_typed_sandbox_and_loader_failures_do_not_persist_results(
    runner_database_url: str,
) -> None:
    queue = PostgresJobQueue()
    source = _source()
    retryable_adapter = _FakeAdapter(
        SandboxExecution(
            ok=False,
            payload=None,
            failure=SandboxFailure(
                SandboxFailureCode.PARSER_REPORTED_FAILURE,
                parser_code="OCR_TIMEOUT",
                retryable=True,
            ),
            source_sha256=hashlib.sha256(source.input_bytes).hexdigest(),
            exit_code=2,
            duration_ms=5,
            stdout_bytes=0,
            stderr_bytes=0,
            killed=False,
        )
    )
    with open_connection(runner_database_url) as connection:
        retryable_job = queue.enqueue(
            connection,
            logical_key="phase2:runner-retryable",
            kind="extraction",
            payload=_payload(source),
        )

    retryable = _runner(
        runner_database_url,
        _FakeLoader(source),
        retryable_adapter,
    ).run_once(owner="runner-a")
    assert retryable.target_state is JobState.FAILED_RETRYABLE
    assert retryable.error_code == "OCR_TIMEOUT"

    with open_connection(runner_database_url) as connection:
        terminal_job = queue.enqueue(
            connection,
            logical_key="phase2:runner-terminal-loader",
            kind="extraction",
            payload=_payload(source),
        )
    terminal = _runner(
        runner_database_url,
        _FailingLoader("SOURCE_NOT_FOUND", retryable=False),
        _FakeAdapter(_success_execution(source)),
    ).run_once(owner="runner-b")
    assert terminal.target_state is JobState.FAILED_TERMINAL
    assert terminal.error_code == "SOURCE_NOT_FOUND"

    with open_connection(runner_database_url) as connection:
        assert queue.result_count(connection, job_id=retryable_job.id) == 0
        assert queue.result_count(connection, job_id=terminal_job.id) == 0


def test_stale_runner_completion_leaves_the_reclaimed_job_canonical(
    runner_database_url: str,
) -> None:
    queue = PostgresJobQueue()
    source = _source()
    with open_connection(runner_database_url) as connection:
        job = queue.enqueue(
            connection,
            logical_key="phase2:runner-stale-completion",
            kind="extraction",
            payload=_payload(source),
        )

    @dataclass
    class _ReclaimingAdapter:
        requests: list[SandboxRequest] = field(default_factory=list)

        def execute(self, request: SandboxRequest) -> SandboxExecution:
            self.requests.append(request)
            with open_connection(runner_database_url) as connection:
                with connection.transaction():
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE jobs SET lease_until = clock_timestamp() - INTERVAL '1 second' WHERE id = %s",
                            (job.id,),
                        )
            with open_connection(runner_database_url) as connection:
                reclaimed = queue.claim_next(
                    connection,
                    owner="runner-b",
                    lease_seconds=30,
                    kinds=("extraction",),
                )
            assert reclaimed is not None
            return _success_execution(source)

    outcome = _runner(
        runner_database_url,
        _FakeLoader(source),
        _ReclaimingAdapter(),
    ).run_once(owner="runner-a", lease_seconds=30)

    assert outcome.stale_completion is True
    assert outcome.completed is False
    with open_connection(runner_database_url) as connection:
        persisted = queue.fetch_job(connection, job_id=job.id)
        assert persisted.state is JobState.RUNNING
        assert persisted.lease_generation == 2
        assert queue.result_count(connection, job_id=job.id) == 0
