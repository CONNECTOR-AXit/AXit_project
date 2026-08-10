"""PostgreSQL proof of merged-document optimistic-concurrency persistence."""

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
from app.generation_repository import GenerationRepository
from app.generation_runner import GenerationRunner
from app.grok_edit_agent import GrokEditAgentService
from app.grok_report_provider import GrokEditSuggestion
from app.merged_document_service import (
    MergedDocumentAccessError,
    MergedDocumentParagraphBlock,
    MergedDocumentService,
    MergedDocumentStaleVersionError,
    MergedDocumentVersionSnapshot,
)
from app.migrations import upgrade_database
from app.queue_repository import PostgresJobQueue
from app.session_service import SessionCloseService


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
        pytest.skip("AXIT_TEST_DATABASE_URL is required for merged document integration")
    connection_info = conninfo_to_dict(configured_url)
    database_name = "axit_merged_document_" + uuid4().hex
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
def merged_document_database_url() -> Iterator[str]:
    with _temporary_database() as database_url:
        upgrade_database(database_url)
        yield database_url


def _seed_ready_snapshot(connection: psycopg.Connection[dict[str, object]]) -> ClosedGenerationSeed:
    host_id, outsider_id = uuid4(), uuid4()
    room_id, session_id = uuid4(), uuid4()
    source_lines = (
        "Facilitator: The pilot scope and owner are confirmed, and the next review date is Friday.",
        "Alice: The Tuesday checklist assignment is recorded under my name.",
    )
    document_titles = ("기획안 A", "기획안 B")
    with connection.transaction():
        with connection.cursor() as cursor:
            for user_id, label in ((host_id, "Host"), (outsider_id, "Outsider")):
                cursor.execute(
                    "INSERT INTO users (id, email, password_hash, display_name) VALUES (%s, %s, 'hash', %s)",
                    (user_id, f"{user_id.hex}@example.test", label),
                )
            cursor.execute("INSERT INTO rooms (id, owner_id, name) VALUES (%s, %s, 'Room')", (room_id, host_id))
            cursor.execute(
                "INSERT INTO room_memberships (room_id, user_id, role) VALUES (%s, %s, 'host')",
                (room_id, host_id),
            )
            cursor.execute(
                """
                INSERT INTO talk_sessions (id, room_id, host_id, mode, topic, state)
                VALUES (%s, %s, %s, 'relay', 'Fixture meeting', 'open')
                """,
                (session_id, room_id, host_id),
            )
            for ordinal, line in enumerate(source_lines):
                submission_id, revision_id, extraction_id = uuid4(), uuid4(), uuid4()
                cursor.execute(
                    "INSERT INTO submissions (id, session_id, author_id, kind, title) VALUES (%s, %s, %s, 'text', %s)",
                    (submission_id, session_id, host_id, document_titles[ordinal]),
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
    closed = SessionCloseService().close(
        connection,
        session_id=session_id,
        actor_id=host_id,
        exclusions=(),
        pipeline_version="phase3-v1",
    )
    runner = GenerationRunner()
    queue = PostgresJobQueue()
    repository = GenerationRepository()
    for kind in ("summary", "research"):
        claimed = queue.claim_next(
            connection, owner=f"seed-{kind}", lease_seconds=60, kinds={kind}
        )
        assert claimed is not None
        execution = runner.execute(connection, claimed)
        queue.complete_with_effects(
            connection,
            claimed,
            target_state=execution.target_state,
            result=execution.result,
            error_code=execution.error_code,
            effect=execution.fenced_effect(repository),
        )
    return ClosedGenerationSeed(
        host_id=host_id, outsider_id=outsider_id, session_id=session_id, snapshot_id=closed.snapshot_id
    )


class _RecordingEditProvider:
    def __init__(self) -> None:
        self.blocks: tuple[dict[str, object], ...] = ()

    def generate_edit_suggestions(self, *, instruction, blocks, anchors):
        self.blocks = tuple(blocks)
        paragraph = next(block for block in blocks if block.get("type") == "paragraph")
        return (
            GrokEditSuggestion(
                kind="edit",
                source_anchor_id=anchors[0].id,
                target_block_id=str(paragraph["id"]),
                suggested_text="근거를 다시 확인한 수정 문단입니다.",
                rationale="업로드 문서 근거를 반영했습니다.",
            ),
        )


def test_grok_edit_uses_visible_baseline_before_first_autosave(
    merged_document_database_url: str,
) -> None:
    provider = _RecordingEditProvider()
    with open_connection(merged_document_database_url) as connection:
        seed = _seed_ready_snapshot(connection)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM merged_document_states WHERE session_id=%s",
                (seed.session_id,),
            )
            assert cursor.fetchone()["count"] == 0

        suggestions = GrokEditAgentService(provider).run(
            connection,
            session_id=seed.session_id,
            actor_id=seed.host_id,
            instruction="문서 구조를 더 명확하게 수정해줘",
        )

        assert suggestions[0].target_block_id.startswith("b-p-")
        assert any(block.get("type") == "paragraph" for block in provider.blocks)


def test_get_derives_baseline_then_save_persists_and_detects_stale_version(
    merged_document_database_url: str,
) -> None:
    service = MergedDocumentService()
    with open_connection(merged_document_database_url) as connection:
        seed = _seed_ready_snapshot(connection)

        baseline = service.get(connection, session_id=seed.session_id, actor_id=seed.host_id)
        assert baseline.version == 0
        assert baseline.updated_at is None
        assert len(baseline.blocks) > 0

        # A paragraph's tag must be the real uploaded document title it was
        # drawn from (a genuine RAG citation), not a constant placeholder.
        paragraph_tags = {
            block.tag
            for block in baseline.blocks
            if isinstance(block, MergedDocumentParagraphBlock) and block.tag
        }
        assert paragraph_tags <= {"기획안 A", "기획안 B"}
        assert paragraph_tags

        edited_blocks = (
            MergedDocumentParagraphBlock(id="b-p-0-0", text="편집된 첫 문단입니다.", tag="통합"),
        )
        saved = service.save(
            connection,
            session_id=seed.session_id,
            actor_id=seed.host_id,
            expected_version=0,
            blocks=edited_blocks,
        )
        assert saved.version == 1
        assert saved.updated_at is not None
        assert saved.blocks == edited_blocks

        reloaded = service.get(connection, session_id=seed.session_id, actor_id=seed.host_id)
        assert reloaded.version == 1
        assert reloaded.blocks == edited_blocks

        with pytest.raises(MergedDocumentStaleVersionError):
            service.save(
                connection,
                session_id=seed.session_id,
                actor_id=seed.host_id,
                expected_version=0,
                blocks=edited_blocks,
            )

        second_edit = (
            MergedDocumentParagraphBlock(id="b-p-0-0", text="두 번째 편집입니다.", tag="통합"),
        )
        resaved = service.save(
            connection,
            session_id=seed.session_id,
            actor_id=seed.host_id,
            expected_version=1,
            blocks=second_edit,
        )
        assert resaved.version == 2
        assert resaved.blocks == second_edit


def test_get_augments_legacy_ai_document_with_complete_source_coverage(
    merged_document_database_url: str,
) -> None:
    service = MergedDocumentService()
    with open_connection(merged_document_database_url) as connection:
        seed = _seed_ready_snapshot(connection)
        service.save(
            connection,
            session_id=seed.session_id,
            actor_id=seed.host_id,
            expected_version=0,
            blocks=(
                MergedDocumentParagraphBlock(
                    id="ai-0",
                    text="기존 AI 통합 보고서",
                    tag="RAG",
                ),
            ),
        )

        reloaded = service.get(
            connection,
            session_id=seed.session_id,
            actor_id=seed.host_id,
        )

        assert reloaded.blocks[0].id == "ai-0"
        assert any(block.id == "source-coverage-heading" for block in reloaded.blocks)
        source_text = "\n".join(block.text for block in reloaded.blocks[1:])
        assert "The pilot scope and owner are confirmed" in source_text
        assert "The Tuesday checklist assignment" in source_text


def test_non_member_cannot_read_or_save(merged_document_database_url: str) -> None:
    service = MergedDocumentService()
    with open_connection(merged_document_database_url) as connection:
        seed = _seed_ready_snapshot(connection)
        stranger_id = uuid4()

        with pytest.raises(MergedDocumentAccessError):
            service.get(connection, session_id=seed.session_id, actor_id=stranger_id)

        with pytest.raises(MergedDocumentAccessError):
            service.save(
                connection,
                session_id=seed.session_id,
                actor_id=stranger_id,
                expected_version=0,
                blocks=(MergedDocumentParagraphBlock(id="x", text="x"),),
            )


def test_create_version_snapshots_current_document_and_lists_newest_first(
    merged_document_database_url: str,
) -> None:
    service = MergedDocumentService()
    with open_connection(merged_document_database_url) as connection:
        seed = _seed_ready_snapshot(connection)

        # No versions saved yet.
        assert service.list_versions(connection, session_id=seed.session_id, actor_id=seed.host_id) == ()

        # "현재 문서를 버전으로 추가" against the never-saved baseline must still work
        # (it snapshots whatever get() currently returns, baseline included).
        first_version = service.create_version(
            connection, session_id=seed.session_id, actor_id=seed.host_id, label="초안"
        )
        assert isinstance(first_version, MergedDocumentVersionSnapshot)
        assert first_version.label == "초안"
        assert first_version.document_version == 0
        assert first_version.created_by == seed.host_id
        assert len(first_version.blocks) > 0

        edited_blocks = (
            MergedDocumentParagraphBlock(id="b-p-0-0", text="편집된 문단입니다.", tag="기획안 A"),
        )
        service.save(
            connection,
            session_id=seed.session_id,
            actor_id=seed.host_id,
            expected_version=0,
            blocks=edited_blocks,
        )
        second_version = service.create_version(
            connection, session_id=seed.session_id, actor_id=seed.host_id, label="1차 수정"
        )
        assert second_version.document_version == 1
        assert second_version.blocks == edited_blocks

        # Both permanent snapshots survive independently, newest first, and the
        # live merged_document_states row (checked separately below) is untouched
        # by taking a version snapshot.
        versions = service.list_versions(connection, session_id=seed.session_id, actor_id=seed.host_id)
        assert [v.id for v in versions] == [second_version.id, first_version.id]
        assert [v.label for v in versions] == ["1차 수정", "초안"]

        current = service.get(connection, session_id=seed.session_id, actor_id=seed.host_id)
        assert current.version == 1
        assert current.blocks == edited_blocks


def test_create_version_rejects_blank_label(merged_document_database_url: str) -> None:
    service = MergedDocumentService()
    with open_connection(merged_document_database_url) as connection:
        seed = _seed_ready_snapshot(connection)
        with pytest.raises(ValueError):
            service.create_version(
                connection, session_id=seed.session_id, actor_id=seed.host_id, label="   "
            )


def test_get_version_returns_full_content_and_rejects_non_members(
    merged_document_database_url: str,
) -> None:
    service = MergedDocumentService()
    with open_connection(merged_document_database_url) as connection:
        seed = _seed_ready_snapshot(connection)
        created = service.create_version(
            connection, session_id=seed.session_id, actor_id=seed.host_id, label="초안"
        )

        fetched = service.get_version(
            connection, session_id=seed.session_id, actor_id=seed.host_id, version_id=created.id
        )
        assert fetched.id == created.id
        assert fetched.label == "초안"
        assert fetched.blocks == created.blocks

        with pytest.raises(MergedDocumentAccessError):
            service.get_version(
                connection,
                session_id=seed.session_id,
                actor_id=seed.host_id,
                version_id=uuid4(),
            )

        with pytest.raises(MergedDocumentAccessError):
            service.get_version(
                connection,
                session_id=seed.session_id,
                actor_id=uuid4(),
                version_id=created.id,
            )
