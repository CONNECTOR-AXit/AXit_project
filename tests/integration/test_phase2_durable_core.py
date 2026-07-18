"""Real-PostgreSQL proof for the Phase 2 migration, close, and fencing core."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.db import open_connection
from app.domain import CloseBlockedError, JobState, StaleLeaseError, TalkSessionState
from app.migrations import downgrade_database, upgrade_database
from app.queue_repository import PostgresJobQueue
from app.session_service import (
    CloseExclusionRequest,
    ExtractionAnchorSchemaMismatchError,
    SessionCloseService,
)


pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_FIXTURE = ROOT / "tests" / "fixtures" / "schema" / "phase2-durable-core.v1.json"


@dataclass(frozen=True, slots=True)
class SeededSession:
    user_id: UUID
    session_id: UUID
    submission_id: UUID
    ready_revision_id: UUID
    extraction_run_id: UUID


@contextmanager
def _temporary_database() -> Iterator[str]:
    configured_url = os.environ.get("AXIT_TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("AXIT_TEST_DATABASE_URL is required for Phase 2 PostgreSQL integration")
    connection_info = conninfo_to_dict(configured_url)
    database_name = "axit_phase2_" + uuid4().hex
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
def durable_database_url() -> Iterator[str]:
    with _temporary_database() as database_url:
        yield database_url


def _schema_table_names(database_url: str) -> set[str]:
    with open_connection(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            )
            return {str(row["tablename"]) for row in cursor.fetchall()}


def _schema_projection(database_url: str) -> dict[str, object]:
    with open_connection(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name, json_agg(column_name ORDER BY ordinal_position) AS columns
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name <> 'alembic_version'
                GROUP BY table_name
                ORDER BY table_name
                """
            )
            columns = {
                str(row["table_name"]): list(row["columns"])
                for row in cursor.fetchall()
            }
            cursor.execute(
                """
                SELECT conname FROM pg_constraint
                WHERE connamespace = 'public'::regnamespace
                ORDER BY conname
                """
            )
            constraints = {str(row["conname"]) for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT indexname FROM pg_indexes
                WHERE schemaname = 'public'
                ORDER BY indexname
                """
            )
            indexes = {str(row["indexname"]) for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT DISTINCT trigger_name
                FROM information_schema.triggers
                WHERE trigger_schema = 'public'
                ORDER BY trigger_name
                """
            )
            triggers = {str(row["trigger_name"]) for row in cursor.fetchall()}
    return {
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
        "triggers": triggers,
    }


def _seed_open_session(connection: psycopg.Connection[dict[str, object]]) -> SeededSession:
    user_id = uuid4()
    room_id = uuid4()
    session_id = uuid4()
    submission_id = uuid4()
    revision_id = uuid4()
    extraction_run_id = uuid4()
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (id, email, password_hash, display_name)
                VALUES (%s, %s, %s, %s)
                """,
                (user_id, f"{user_id.hex}@example.test", "phase2-hash", "Host"),
            )
            cursor.execute(
                "INSERT INTO rooms (id, owner_id, name) VALUES (%s, %s, %s)",
                (room_id, user_id, "Durable room"),
            )
            cursor.execute(
                """
                INSERT INTO room_memberships (room_id, user_id, role)
                VALUES (%s, %s, 'host')
                """,
                (room_id, user_id),
            )
            cursor.execute(
                """
                INSERT INTO talk_sessions (id, room_id, host_id, mode, topic, state)
                VALUES (%s, %s, %s, 'relay', 'Phase 2 close transaction', 'open')
                """,
                (session_id, room_id, user_id),
            )
            cursor.execute(
                """
                INSERT INTO submissions (id, session_id, author_id, kind)
                VALUES (%s, %s, %s, 'text')
                """,
                (submission_id, session_id, user_id),
            )
            cursor.execute(
                """
                INSERT INTO source_revisions (
                    id, submission_id, revision_no, filename, mime_type, byte_size,
                    sha256, source_text, processing_state
                ) VALUES (%s, %s, 1, 'agenda.txt', 'text/plain', 12, %s, %s, 'queued')
                """,
                (revision_id, submission_id, "a" * 64, "participant source"),
            )
            cursor.execute(
                """
                INSERT INTO extraction_runs (
                    id, source_revision_id, parser_name, parser_version, newline_policy,
                    unicode_normalization_profile, config_hash, anchor_schema_version,
                    attempt_no, status, completed_at
                ) VALUES (%s, %s, 'text', '1', 'lf', 'nfc', %s, 'v1', 1, 'succeeded', CURRENT_TIMESTAMP)
                """,
                (extraction_run_id, revision_id, "b" * 64),
            )
            cursor.execute(
                """
                UPDATE source_revisions
                SET approved_extraction_run_id = %s, processing_state = 'ready'
                WHERE id = %s
                """,
                (extraction_run_id, revision_id),
            )
    return SeededSession(user_id, session_id, submission_id, revision_id, extraction_run_id)


def _insert_anchor(
    connection: psycopg.Connection[dict[str, object]],
    seeded: SeededSession,
) -> UUID:
    anchor_id = uuid4()
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO source_anchors (
                    id, extraction_run_id, source_revision_id, ordinal, block_type,
                    text, anchor_json, canonical_hash
                ) VALUES (%s, %s, %s, 0, 'text_line', 'participant source', '{}'::jsonb, %s)
                """,
                (
                    anchor_id,
                    seeded.extraction_run_id,
                    seeded.ready_revision_id,
                    "f" * 64,
                ),
            )
    return anchor_id


def _add_unready_current_revision(
    connection: psycopg.Connection[dict[str, object]],
    seeded: SeededSession,
) -> UUID:
    submission_id = uuid4()
    revision_id = uuid4()
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO submissions (id, session_id, author_id, kind)
                VALUES (%s, %s, %s, 'file')
                """,
                (submission_id, seeded.session_id, seeded.user_id),
            )
            cursor.execute(
                """
                INSERT INTO source_revisions (
                    id, submission_id, revision_no, filename, mime_type, byte_size,
                    sha256, processing_state
                ) VALUES (%s, %s, 1, 'failed.pdf', 'application/pdf', 10, %s, 'failed')
                """,
                (revision_id, submission_id, "c" * 64),
            )
    return revision_id


def _generation_run_id(
    connection: psycopg.Connection[dict[str, object]],
    *,
    snapshot_id: UUID,
    kind: str,
) -> UUID:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id FROM generation_runs
            WHERE snapshot_id = %s AND kind = %s
            """,
            (snapshot_id, kind),
        )
        row = cursor.fetchone()
    assert row is not None
    return row["id"]


def _insert_generated_segment(
    connection: psycopg.Connection[dict[str, object]],
    *,
    run_id: UUID,
    kind: str,
) -> UUID:
    document_id = uuid4()
    segment_id = uuid4()
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO generated_documents (
                    id, run_id, kind, structured_content_json, content_hash
                ) VALUES (%s, %s, %s, '{}'::jsonb, %s)
                """,
                (document_id, run_id, kind, "1" * 64),
            )
            cursor.execute(
                """
                INSERT INTO generated_segments (id, document_id, ordinal, text)
                VALUES (%s, %s, 0, 'bounded generated segment')
                """,
                (segment_id, document_id),
            )
    return segment_id


def test_alembic_up_down_up_and_schema_fixture(durable_database_url: str) -> None:
    fixture = json.loads(SCHEMA_FIXTURE.read_text(encoding="utf-8"))
    expected_tables = set(fixture["tables"])
    upgrade_database(durable_database_url)
    assert _schema_table_names(durable_database_url) == expected_tables | {"alembic_version"}
    projection = _schema_projection(durable_database_url)
    assert projection["columns"] == fixture["critical_columns"]
    assert set(fixture["required_constraints"]) <= projection["constraints"]
    assert set(fixture["required_indexes"]) <= projection["indexes"]
    assert set(fixture["required_triggers"]) <= projection["triggers"]

    downgrade_database(durable_database_url)
    assert _schema_table_names(durable_database_url) == {"alembic_version"}

    upgrade_database(durable_database_url)
    assert _schema_table_names(durable_database_url) == expected_tables | {"alembic_version"}
    assert _schema_projection(durable_database_url) == projection


def test_cross_revision_provenance_fk_and_close_snapshot_are_durable(
    durable_database_url: str,
) -> None:
    upgrade_database(durable_database_url)
    with open_connection(durable_database_url) as connection:
        seeded = _seed_open_session(connection)
        unready_revision = _add_unready_current_revision(connection, seeded)
        close_service = SessionCloseService()

        with pytest.raises(CloseBlockedError) as blocked:
            close_service.close(
                connection,
                session_id=seeded.session_id,
                actor_id=seeded.user_id,
                exclusions=(),
                pipeline_version="phase2-v1",
            )
        assert blocked.value.blocking_revision_ids == (str(unready_revision),)

        with pytest.raises(ExtractionAnchorSchemaMismatchError):
            close_service.close(
                connection,
                session_id=seeded.session_id,
                actor_id=seeded.user_id,
                exclusions=(
                    CloseExclusionRequest(unready_revision, "parser failure acknowledged"),
                ),
                pipeline_version="phase2-v1",
                anchor_schema_version="mismatched-v999",
            )

        closed = close_service.close(
            connection,
            session_id=seeded.session_id,
            actor_id=seeded.user_id,
            exclusions=(
                CloseExclusionRequest(unready_revision, "parser failure acknowledged"),
            ),
            pipeline_version="phase2-v1",
        )
        repeated = close_service.close(
            connection,
            session_id=seeded.session_id,
            actor_id=seeded.user_id,
            exclusions=(),
            pipeline_version="phase2-v1",
        )
        assert closed.state is TalkSessionState.PROCESSING
        assert closed.generation_epoch == 1
        assert repeated.snapshot_id == closed.snapshot_id
        assert repeated.idempotent is True

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) AS count FROM generation_snapshots WHERE session_id = %s",
                (seeded.session_id,),
            )
            assert cursor.fetchone()["count"] == 1
            cursor.execute(
                "SELECT count(*) AS count FROM generation_runs WHERE snapshot_id = %s",
                (closed.snapshot_id,),
            )
            assert cursor.fetchone()["count"] == 2
            cursor.execute(
                "SELECT count(*) AS count FROM jobs WHERE snapshot_id = %s",
                (closed.snapshot_id,),
            )
            assert cursor.fetchone()["count"] == 2
            cursor.execute(
                "SELECT count(*) AS count FROM snapshot_exclusions WHERE session_id = %s",
                (seeded.session_id,),
            )
            assert cursor.fetchone()["count"] == 1
            cursor.execute(
                "SELECT anchor_schema_version FROM generation_snapshots WHERE id = %s",
                (closed.snapshot_id,),
            )
            assert cursor.fetchone()["anchor_schema_version"] == "v1"

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO source_anchors (
                            id, extraction_run_id, source_revision_id, ordinal, block_type,
                            text, anchor_json, canonical_hash
                        ) VALUES (%s, %s, %s, 0, 'text_line', 'mismatch', '{}'::jsonb, %s)
                        """,
                        (uuid4(), seeded.extraction_run_id, unready_revision, "d" * 64),
                    )


def test_database_enforces_snapshot_session_and_summary_research_isolation(
    durable_database_url: str,
) -> None:
    upgrade_database(durable_database_url)
    close_service = SessionCloseService()
    with open_connection(durable_database_url) as connection:
        first = _seed_open_session(connection)
        second = _seed_open_session(connection)
        first_anchor = _insert_anchor(connection, first)
        second_anchor = _insert_anchor(connection, second)
        first_closed = close_service.close(
            connection,
            session_id=first.session_id,
            actor_id=first.user_id,
            exclusions=(),
            pipeline_version="phase2-v1",
        )
        second_closed = close_service.close(
            connection,
            session_id=second.session_id,
            actor_id=second.user_id,
            exclusions=(),
            pipeline_version="phase2-v1",
        )

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO snapshot_revisions (
                            snapshot_id, source_revision_id, extraction_run_id
                        ) VALUES (%s, %s, %s)
                        """,
                        (
                            first_closed.snapshot_id,
                            second.ready_revision_id,
                            second.extraction_run_id,
                        ),
                    )

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO snapshot_exclusions (
                            id, session_id, source_revision_id, reason, actor_id
                        ) VALUES (%s, %s, %s, 'foreign revision', %s)
                        """,
                        (
                            uuid4(),
                            first.session_id,
                            second.ready_revision_id,
                            first.user_id,
                        ),
                    )

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE source_revisions SET submission_id = %s WHERE id = %s",
                        (first.submission_id, second.ready_revision_id),
                    )

        summary_run_id = _generation_run_id(
            connection,
            snapshot_id=first_closed.snapshot_id,
            kind="summary",
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO generated_documents (
                            id, run_id, kind, structured_content_json, content_hash
                        ) VALUES (%s, %s, 'research', '{}'::jsonb, %s)
                        """,
                        (uuid4(), summary_run_id, "2" * 64),
                    )
        summary_segment_id = _insert_generated_segment(
            connection,
            run_id=summary_run_id,
            kind="summary",
        )

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO citations (
                            id, segment_id, target_type, source_anchor_id, web_evidence_id
                        ) VALUES (%s, %s, 'source_anchor', %s, NULL)
                        """,
                        (uuid4(), summary_segment_id, second_anchor),
                    )

        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO citations (
                        id, segment_id, target_type, source_anchor_id, web_evidence_id
                    ) VALUES (%s, %s, 'source_anchor', %s, NULL)
                    """,
                    (uuid4(), summary_segment_id, first_anchor),
                )
                cursor.execute(
                    """
                    INSERT INTO web_evidence (
                        id, url, title, domain, accessed_at, snippet_hash
                    ) VALUES (%s, 'https://evidence.example/path', 'Evidence',
                              'evidence.example', CURRENT_TIMESTAMP, %s)
                    """,
                    (uuid4(), "3" * 64),
                )
                web_evidence_id = cursor.execute(
                    "SELECT id FROM web_evidence ORDER BY created_at DESC LIMIT 1"
                ).fetchone()["id"]

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO citations (
                            id, segment_id, target_type, source_anchor_id, web_evidence_id
                        ) VALUES (%s, %s, 'web_evidence', NULL, %s)
                        """,
                        (uuid4(), summary_segment_id, web_evidence_id),
                    )

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO research_claims (
                            id, run_id, claim_text, source_anchor_id, verdict, explanation
                        ) VALUES (%s, %s, 'claim', %s, 'supported', 'wrong run kind')
                        """,
                        (uuid4(), summary_run_id, first_anchor),
                    )

        research_run_id = _generation_run_id(
            connection,
            snapshot_id=first_closed.snapshot_id,
            kind="research",
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO research_claims (
                            id, run_id, claim_text, source_anchor_id, verdict, explanation
                        ) VALUES (%s, %s, 'claim', %s, 'supported', 'foreign anchor')
                        """,
                        (uuid4(), research_run_id, second_anchor),
                    )

        assert second_closed.snapshot_id != first_closed.snapshot_id


def test_database_constraints_reject_unapproved_or_unsuccessful_ready_revision_and_duplicate_job_key(
    durable_database_url: str,
) -> None:
    upgrade_database(durable_database_url)
    with open_connection(durable_database_url) as connection:
        seeded = _seed_open_session(connection)
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    submission_id = uuid4()
                    cursor.execute(
                        """
                        INSERT INTO submissions (id, session_id, author_id, kind)
                        VALUES (%s, %s, %s, 'text')
                        """,
                        (submission_id, seeded.session_id, seeded.user_id),
                    )
                    cursor.execute(
                        """
                        INSERT INTO source_revisions (
                            id, submission_id, revision_no, filename, mime_type,
                            byte_size, sha256, processing_state
                        ) VALUES (%s, %s, 1, 'unapproved.txt', 'text/plain', 1, %s, 'ready')
                        """,
                        (uuid4(), submission_id, "e" * 64),
                    )

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    submission_id = uuid4()
                    revision_id = uuid4()
                    failed_run_id = uuid4()
                    cursor.execute(
                        """
                        INSERT INTO submissions (id, session_id, author_id, kind)
                        VALUES (%s, %s, %s, 'text')
                        """,
                        (submission_id, seeded.session_id, seeded.user_id),
                    )
                    cursor.execute(
                        """
                        INSERT INTO source_revisions (
                            id, submission_id, revision_no, filename, mime_type,
                            byte_size, sha256, processing_state
                        ) VALUES (%s, %s, 1, 'failed-run.txt', 'text/plain', 1, %s, 'queued')
                        """,
                        (revision_id, submission_id, "f" * 64),
                    )
                    cursor.execute(
                        """
                        INSERT INTO extraction_runs (
                            id, source_revision_id, parser_name, parser_version,
                            newline_policy, unicode_normalization_profile, config_hash,
                            anchor_schema_version, status
                        ) VALUES (%s, %s, 'text', '1', 'lf', 'nfc', %s, 'v1', 'failed')
                        """,
                        (failed_run_id, revision_id, "0" * 64),
                    )
                    cursor.execute(
                        """
                        UPDATE source_revisions
                        SET approved_extraction_run_id = %s, processing_state = 'ready'
                        WHERE id = %s
                        """,
                        (failed_run_id, revision_id),
                    )

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE extraction_runs SET status = 'failed' WHERE id = %s",
                        (seeded.extraction_run_id,),
                    )

        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO jobs (id, logical_key, kind, payload_json, state)
                    VALUES (%s, 'phase2:unique-key', 'extraction', '{}'::jsonb, 'pending')
                    """,
                    (uuid4(),),
                )
        with pytest.raises(psycopg.errors.UniqueViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO jobs (id, logical_key, kind, payload_json, state)
                        VALUES (%s, 'phase2:unique-key', 'extraction', '{}'::jsonb, 'pending')
                        """,
                        (uuid4(),),
                    )

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO web_evidence (
                            id, url, title, domain, accessed_at, snippet_hash
                        ) VALUES (%s, 'https://evil.example@trusted.example/', 'Evidence',
                                  'trusted.example', CURRENT_TIMESTAMP, %s)
                        """,
                        (uuid4(), "d" * 64),
                    )

        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO jobs (id, logical_key, kind, payload_json, state)
                        VALUES (%s, 'phase2:missing-failure-code', 'extraction', '{}'::jsonb, 'failed_retryable')
                        """,
                        (uuid4(),),
                    )


def test_two_workers_claim_once_and_stale_completion_rolls_back(
    durable_database_url: str,
) -> None:
    upgrade_database(durable_database_url)
    queue = PostgresJobQueue()
    with open_connection(durable_database_url) as connection:
        job = queue.enqueue(
            connection,
            logical_key="phase2:two-workers",
            kind="extraction",
            payload={"revision_id": str(uuid4())},
        )

    def claim(owner: str):
        with open_connection(durable_database_url) as worker_connection:
            return queue.claim_next(worker_connection, owner=owner, lease_seconds=30)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(claim, ("worker-a", "worker-b")))
    first_claim = next(item for item in claims if item is not None)
    assert sum(item is not None for item in claims) == 1

    with open_connection(durable_database_url) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE jobs SET lease_until = clock_timestamp() - INTERVAL '1 second' WHERE id = %s",
                    (job.id,),
                )

    with open_connection(durable_database_url) as expired_connection:
        with pytest.raises(StaleLeaseError):
            queue.heartbeat(expired_connection, first_claim, lease_seconds=30)
        with pytest.raises(StaleLeaseError):
            queue.complete(
                expired_connection,
                first_claim,
                target_state=JobState.SUCCEEDED,
                result={"worker": "expired"},
            )
        assert queue.result_count(expired_connection, job_id=job.id) == 0

    with open_connection(durable_database_url) as connection:
        reclaimed = queue.claim_next(connection, owner="worker-c", lease_seconds=30)
        assert reclaimed is not None
        assert reclaimed.lease_generation == first_claim.lease_generation + 1
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, error_code FROM job_attempts
                WHERE job_id = %s AND lease_generation = %s
                """,
                (job.id, first_claim.lease_generation),
            )
            expired_attempt = cursor.fetchone()
        assert expired_attempt == {"status": "expired", "error_code": "lease_expired"}

    with open_connection(durable_database_url) as stale_connection:
        with pytest.raises(StaleLeaseError):
            queue.complete(
                stale_connection,
                first_claim,
                target_state=JobState.SUCCEEDED,
                result={"worker": "stale"},
            )
        assert queue.result_count(stale_connection, job_id=job.id) == 0

    with open_connection(durable_database_url) as current_connection:
        queue.complete(
            current_connection,
            reclaimed,
            target_state=JobState.SUCCEEDED,
            result={"worker": "current"},
        )
        assert queue.fetch_job(current_connection, job_id=job.id).state is JobState.SUCCEEDED
        assert queue.result_count(current_connection, job_id=job.id) == 1


def test_retry_reuses_one_logical_job_and_only_success_persists_result(
    durable_database_url: str,
) -> None:
    upgrade_database(durable_database_url)
    queue = PostgresJobQueue()
    with open_connection(durable_database_url) as connection:
        job = queue.enqueue(
            connection,
            logical_key="phase2:retry-same-logical-job",
            kind="research",
            payload={"snapshot_id": str(uuid4())},
        )
        first = queue.claim_next(connection, owner="worker-a", lease_seconds=30)
        assert first is not None
        queue.complete(
            connection,
            first,
            target_state=JobState.FAILED_RETRYABLE,
            result={"typed_failure": "provider_timeout"},
            error_code="provider_timeout",
        )
        assert queue.result_count(connection, job_id=job.id) == 0
        queue.requeue_retryable(
            connection,
            job_id=job.id,
            expected_lease_generation=first.lease_generation,
        )
        with pytest.raises(StaleLeaseError):
            queue.requeue_retryable(
                connection,
                job_id=job.id,
                expected_lease_generation=first.lease_generation + 1,
            )
        second = queue.claim_next(connection, owner="worker-b", lease_seconds=30)
        assert second is not None
        assert second.id == first.id
        assert second.lease_generation == first.lease_generation + 1
        queue.complete(
            connection,
            second,
            target_state=JobState.SUCCEEDED,
            result={"fixture": "research-success"},
        )
        assert queue.result_count(connection, job_id=job.id) == 1


def test_result_insert_failure_rolls_back_the_completion_cas(
    durable_database_url: str,
) -> None:
    upgrade_database(durable_database_url)
    queue = PostgresJobQueue()
    with open_connection(durable_database_url) as connection:
        job = queue.enqueue(
            connection,
            logical_key="phase2:result-rollback",
            kind="summary",
            payload={"snapshot_id": str(uuid4())},
        )
        claimed = queue.claim_next(connection, owner="worker-a", lease_seconds=30)
        assert claimed is not None

    # Simulate a conflicting canonical result inserted by a corrupt writer.
    # ``complete`` must roll its state/attempt CAS back when the unique result
    # insert fails rather than leaving a succeeded job without a valid result.
    with open_connection(durable_database_url) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO job_results (id, job_id, result_json, result_hash)
                    VALUES (%s, %s, '{}'::jsonb, %s)
                    """,
                    (uuid4(), job.id, "a" * 64),
                )

    with open_connection(durable_database_url) as connection:
        with pytest.raises(psycopg.errors.UniqueViolation):
            queue.complete(
                connection,
                claimed,
                target_state=JobState.SUCCEEDED,
                result={"would": "conflict"},
            )
        assert queue.fetch_job(connection, job_id=job.id).state is JobState.RUNNING
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, ended_at FROM job_attempts
                WHERE job_id = %s AND lease_generation = %s
                """,
                (job.id, claimed.lease_generation),
            )
            attempt = cursor.fetchone()
        assert attempt == {"status": "running", "ended_at": None}
