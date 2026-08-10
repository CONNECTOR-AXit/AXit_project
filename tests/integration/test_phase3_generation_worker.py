"""PostgreSQL proof that fenced generation effects reach the right aggregate."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.db import open_connection
from app.domain import JobState, TalkSessionState
from app.document_comparison import DocumentComparisonService
from app.automatic_report_suggestions import FencedAutomaticSuggestionWorker
from app.generation_repository import GenerationDocumentUnavailableError, GenerationRepository
from app.generation_runner import GenerationRunner
from app.migrations import upgrade_database
from app.queue_repository import PostgresJobQueue
from app.report_suggestions import ReportSuggestionService
from app.session_service import SessionCloseService
from app.source_retrieval import SourceRetrievalService


pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class ClosedGenerationSeed:
    host_id: UUID
    outsider_id: UUID
    session_id: UUID
    snapshot_id: UUID


@contextmanager
def _temporary_database() -> Iterator[str]:
    configured_url = os.environ.get("AXIT_TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("AXIT_TEST_DATABASE_URL is required for generation integration")
    connection_info = conninfo_to_dict(configured_url)
    database_name = "axit_phase3_generation_" + uuid4().hex
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
def generation_database_url() -> Iterator[str]:
    with _temporary_database() as database_url:
        upgrade_database(database_url)
        yield database_url


def _seed_closed_snapshot(
    connection: psycopg.Connection[dict[str, object]],
    *,
    duplicate_first: bool = False,
    include_noisy_ocr: bool = False,
) -> ClosedGenerationSeed:
    host_id, member_id, outsider_id = uuid4(), uuid4(), uuid4()
    room_id, session_id = uuid4(), uuid4()
    source_lines = (
        "Facilitator: The pilot scope and owner are confirmed, and the next review date is Friday.",
        "Alice: The Tuesday checklist assignment is recorded under my name.",
        "Bob: The sample records passed the validation audit on Thursday.",
    )
    if duplicate_first:
        source_lines += (source_lines[0],)
    with connection.transaction():
        with connection.cursor() as cursor:
            for user_id, label in ((host_id, "Host"), (member_id, "Member"), (outsider_id, "Outsider")):
                cursor.execute(
                    "INSERT INTO users (id, email, password_hash, display_name) VALUES (%s, %s, 'hash', %s)",
                    (user_id, f"{user_id.hex}@example.test", label),
                )
            cursor.execute("INSERT INTO rooms (id, owner_id, name) VALUES (%s, %s, 'Room')", (room_id, host_id))
            for user_id, role in ((host_id, "host"), (member_id, "member")):
                cursor.execute(
                    "INSERT INTO room_memberships (room_id, user_id, role) VALUES (%s, %s, %s)",
                    (room_id, user_id, role),
                )
            cursor.execute(
                """
                INSERT INTO talk_sessions (id, room_id, host_id, mode, topic, state)
                VALUES (%s, %s, %s, 'relay', 'Fixture meeting', 'open')
                """,
                (session_id, room_id, host_id),
            )
            first_anchor_run: tuple[UUID, UUID] | None = None
            for ordinal, line in enumerate(source_lines):
                submission_id, revision_id, extraction_id = uuid4(), uuid4(), uuid4()
                cursor.execute(
                    "INSERT INTO submissions (id, session_id, author_id, kind) VALUES (%s, %s, %s, 'text')",
                    (submission_id, session_id, host_id),
                )
                digest = hashlib.sha256(line.encode()).hexdigest()
                cursor.execute(
                    """
                    INSERT INTO source_revisions (
                        id, submission_id, revision_no, filename, mime_type, byte_size,
                        sha256, source_text, processing_state
                    ) VALUES (%s, %s, 1, %s, 'text/plain', %s, %s, %s, 'queued')
                    """,
                    (revision_id, submission_id, f"source-{ordinal}.txt", len(line.encode()), digest, line),
                )
                cursor.execute(
                    """
                    INSERT INTO extraction_runs (
                        id, source_revision_id, parser_name, parser_version, newline_policy,
                        unicode_normalization_profile, config_hash, anchor_schema_version,
                        status, completed_at
                    ) VALUES (%s, %s, 'inline-text', '1', 'lf', 'nfc', %s, '1', 'succeeded', CURRENT_TIMESTAMP)
                    """,
                    (extraction_id, revision_id, hashlib.sha256(f"config-{ordinal}".encode()).hexdigest()),
                )
                cursor.execute(
                    "UPDATE source_revisions SET approved_extraction_run_id = %s, processing_state = 'ready' WHERE id = %s",
                    (extraction_id, revision_id),
                )
                cursor.execute(
                    """
                    INSERT INTO source_anchors (
                        id, extraction_run_id, source_revision_id, ordinal, block_type,
                        text, anchor_json, canonical_hash
                    ) VALUES (%s, %s, %s, 0, 'text_line', %s, '{}'::jsonb, %s)
                    """,
                    (uuid4(), extraction_id, revision_id, line, hashlib.sha256(f"anchor-{ordinal}".encode()).hexdigest()),
                )
                if ordinal == 0:
                    first_anchor_run = (extraction_id, revision_id)
            if include_noisy_ocr:
                assert first_anchor_run is not None
                extraction_id, revision_id = first_anchor_run
                cursor.execute(
                    """
                    INSERT INTO source_anchors (
                        id, extraction_run_id, source_revision_id, ordinal, block_type,
                        text, confidence, anchor_json, canonical_hash
                    ) VALUES (%s, %s, %s, 1, 'image_ocr', %s, 0.93, '{}'::jsonb, %s)
                    """,
                    (
                        uuid4(),
                        extraction_id,
                        revision_id,
                        "사내 686 시스템 도입 해",
                        hashlib.sha256(b"noisy-ocr-anchor").hexdigest(),
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO source_anchors (
                        id, extraction_run_id, source_revision_id, ordinal, block_type,
                        text, anchor_json, canonical_hash
                    ) VALUES (%s, %s, %s, 2, 'text_line', %s, '{}'::jsonb, %s)
                    """,
                    (
                        uuid4(),
                        extraction_id,
                        revision_id,
                        "hidden\x01secret",
                        hashlib.sha256(b"control-character-anchor").hexdigest(),
                    ),
                )
    closed = SessionCloseService().close(
        connection,
        session_id=session_id,
        actor_id=host_id,
        exclusions=(),
        pipeline_version="phase3-v1",
    )
    return ClosedGenerationSeed(
        host_id=host_id,
        outsider_id=outsider_id,
        session_id=session_id,
        snapshot_id=closed.snapshot_id,
    )


def _run_kind(
    connection: psycopg.Connection[dict[str, object]],
    *,
    kind: str,
    runner: GenerationRunner,
) -> JobState:
    queue = PostgresJobQueue()
    claimed = queue.claim_next(
        connection,
        owner=f"phase3-{kind}-worker",
        lease_seconds=60,
        kinds={kind},
    )
    assert claimed is not None
    execution = runner.execute(connection, claimed)
    queue.complete_with_effects(
        connection,
        claimed,
        target_state=execution.target_state,
        result=execution.result,
        error_code=execution.error_code,
        effect=execution.fenced_effect(GenerationRepository()),
    )
    return execution.target_state


def _session_state(connection: psycopg.Connection[dict[str, object]], session_id: UUID) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT state FROM talk_sessions WHERE id = %s", (session_id,))
        row = cursor.fetchone()
    assert row is not None
    return str(row["state"])


def test_fenced_summary_and_research_complete_the_phase3_aggregate(
    generation_database_url: str,
) -> None:
    with open_connection(generation_database_url) as connection:
        seed = _seed_closed_snapshot(connection)
        runner = GenerationRunner()
        assert _run_kind(connection, kind="summary", runner=runner) is JobState.SUCCEEDED
        assert _session_state(connection, seed.session_id) == TalkSessionState.PROCESSING.value
        assert _run_kind(connection, kind="research", runner=runner) is JobState.SUCCEEDED
        assert _session_state(connection, seed.session_id) == TalkSessionState.READY.value
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT job.kind, result.result_json
                FROM jobs job
                JOIN job_results result ON result.job_id=job.id
                WHERE job.snapshot_id=%s AND job.kind IN ('summary','research')
                ORDER BY job.kind
                """,
                (seed.snapshot_id,),
            )
            retrieval_results = cursor.fetchall()
            assert len(retrieval_results) == 2
            assert all(
                row["result_json"]["retrieval"]["strategy"] == "hybrid-local-v1"
                and row["result_json"]["retrieval"]["candidate_count"] == 3
                and row["result_json"]["retrieval"]["selected_count"] == 3
                and len(row["result_json"]["retrieval"]["selected_anchor_ids"]) == 3
                for row in retrieval_results
            )
            cursor.execute(
                "SELECT state FROM jobs WHERE snapshot_id = %s AND kind = 'report_suggestions'",
                (seed.snapshot_id,),
            )
            assert cursor.fetchone() == {"state": "pending"}

        repository = GenerationRepository()
        summary = repository.get_summary_for_member(
            connection, session_id=seed.session_id, actor_id=seed.host_id
        )
        assert summary["snapshot_id"] == str(seed.snapshot_id)
        assert all(
            support["citation_id"]
            for section in summary["sections"]
            for item in section["items"]
            for support in item["supports"]
        )
        research = repository.get_research_for_member(
            connection, session_id=seed.session_id, actor_id=seed.host_id
        )
        assert research["snapshot_id"] == str(seed.snapshot_id)
        assert len(research["topic_items"]) == 3
        assert len(research["fact_checks"]) == 3
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM web_evidence) AS evidence_count,
                    (SELECT count(*) FROM research_claims) AS claim_count,
                    (SELECT count(*) FROM citations WHERE target_type = 'web_evidence') AS web_citation_count,
                    (SELECT count(*) FROM citations WHERE target_type = 'source_anchor'
                     AND segment_id IN (
                         SELECT segment.id FROM generated_segments AS segment
                         JOIN generated_documents AS document ON document.id = segment.document_id
                         WHERE document.kind = 'research'
                     )) AS research_source_citation_count
                """
            )
            persisted = cursor.fetchone()
        assert persisted is not None
        assert persisted["evidence_count"] == 4
        assert persisted["claim_count"] == 3
        assert persisted["web_citation_count"] == 8
        assert persisted["research_source_citation_count"] == 3
        with pytest.raises(GenerationDocumentUnavailableError):
            repository.get_summary_for_member(
                connection, session_id=seed.session_id, actor_id=seed.outsider_id
            )


def test_generation_excludes_noisy_ocr_and_reports_quality_metadata(
    generation_database_url: str,
) -> None:
    with open_connection(generation_database_url) as connection:
        seed = _seed_closed_snapshot(connection, include_noisy_ocr=True)
        assert _run_kind(
            connection, kind="summary", runner=GenerationRunner()
        ) is JobState.SUCCEEDED
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT result.result_json
                FROM jobs job
                JOIN job_results result ON result.job_id=job.id
                WHERE job.snapshot_id=%s AND job.kind='summary'
                """,
                (seed.snapshot_id,),
            )
            result = cursor.fetchone()["result_json"]

        assert result["retrieval"]["candidate_count"] == 5
        assert result["retrieval"]["eligible_count"] == 3
        assert result["retrieval"]["source_quality"] == {
            "status": "filtered",
            "total_anchor_count": 5,
            "accepted_anchor_count": 3,
            "excluded_anchor_count": 2,
            "reason_counts": {
                "control_characters": 1,
                "incomplete_ocr_fragment": 1,
            },
        }
        assert GenerationRepository().get_source_quality_for_member(
            connection,
            session_id=seed.session_id,
            actor_id=seed.host_id,
        ) == result["retrieval"]["source_quality"]
        assert SourceRetrievalService().search(
            connection,
            session_id=seed.session_id,
            actor_id=seed.host_id,
            query="686",
        ) == ()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT revision.id
                FROM submissions submission
                JOIN source_revisions revision ON revision.submission_id=submission.id
                WHERE submission.session_id=%s
                ORDER BY submission.created_at, submission.id
                LIMIT 2
                """,
                (seed.session_id,),
            )
            revision_ids = tuple(row["id"] for row in cursor.fetchall())
        comparison = DocumentComparisonService().compare(
            connection,
            session_id=seed.session_id,
            actor_id=seed.host_id,
            left_revision_id=revision_ids[0],
            right_revision_id=revision_ids[1],
        )
        comparison_text = [
            anchor.text
            for anchor in (*comparison.left_only, *comparison.right_only)
        ] + [
            anchor.text
            for match in comparison.matches
            for anchor in (match.left, match.right)
        ]
        assert all("686" not in text for text in comparison_text)


def test_automatic_comparison_job_materializes_grounded_idempotent_suggestions(
    generation_database_url: str,
) -> None:
    with open_connection(generation_database_url) as connection:
        seed = _seed_closed_snapshot(connection, duplicate_first=True)
        runner = GenerationRunner()
        assert _run_kind(connection, kind="summary", runner=runner) is JobState.SUCCEEDED
        assert _run_kind(connection, kind="research", runner=runner) is JobState.SUCCEEDED

    worker = FencedAutomaticSuggestionWorker(
        connection_factory=lambda: open_connection(generation_database_url)
    )
    first = worker.run_once(owner="automatic-suggestion-worker")
    assert first.claimed
    assert first.completed
    assert first.target_state is JobState.SUCCEEDED

    with open_connection(generation_database_url) as connection:
        suggestions = ReportSuggestionService().list(
            connection, session_id=seed.session_id, actor_id=seed.host_id
        )
        assert len(suggestions) == 3
        assert {suggestion.kind for suggestion in suggestions} == {"add", "remove"}
        assert {suggestion.origin for suggestion in suggestions} == {"automatic_comparison"}
        assert all(suggestion.source_anchor_id is not None for suggestion in suggestions)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT anchor.id
                FROM snapshot_revisions snapshot_revision
                JOIN source_anchors anchor
                  ON anchor.source_revision_id = snapshot_revision.source_revision_id
                 AND anchor.extraction_run_id = snapshot_revision.extraction_run_id
                WHERE snapshot_revision.snapshot_id = %s
                """,
                (seed.snapshot_id,),
            )
            snapshot_anchor_ids = {row["id"] for row in cursor.fetchall()}
        assert {suggestion.source_anchor_id for suggestion in suggestions} <= snapshot_anchor_ids
        suggestion_ids = {suggestion.id for suggestion in suggestions}

    second = worker.run_once(owner="automatic-suggestion-worker")
    assert not second.claimed
    with open_connection(generation_database_url) as connection:
        repeated = ReportSuggestionService().list(
            connection, session_id=seed.session_id, actor_id=seed.host_id
        )
        assert {suggestion.id for suggestion in repeated} == suggestion_ids


def test_fenced_provider_failure_projects_needs_attention_after_other_kind_finishes(
    generation_database_url: str,
) -> None:
    with open_connection(generation_database_url) as connection:
        seed = _seed_closed_snapshot(connection)
        assert _run_kind(
            connection,
            kind="summary",
            runner=GenerationRunner(
                summary_fixture_id="summary-source-prompt-injection-rejection-001"
            ),
        ) is JobState.FAILED_TERMINAL
        assert _run_kind(connection, kind="research", runner=GenerationRunner()) is JobState.SUCCEEDED
        assert _session_state(connection, seed.session_id) == TalkSessionState.NEEDS_ATTENTION.value
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT state, error_code FROM generation_runs WHERE snapshot_id = %s AND kind = 'summary'",
                (seed.snapshot_id,),
            )
            row = cursor.fetchone()
        assert row == {"state": "failed_terminal", "error_code": "source_prompt_injection"}
