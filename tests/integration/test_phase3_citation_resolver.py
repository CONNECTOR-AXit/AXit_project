"""Real-PostgreSQL proof that citation resolution is membership-first."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from app.citation_resolver import CitationResolver, CitationUnavailableError
from app.db import open_connection
from app.migrations import upgrade_database


pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class CitationSeed:
    host_id: UUID
    member_id: UUID
    outsider_id: UUID
    revision_id: UUID
    anchor_id: UUID
    citation_id: UUID


@contextmanager
def _temporary_database() -> Iterator[str]:
    configured_url = os.environ.get("AXIT_TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("AXIT_TEST_DATABASE_URL is required for citation integration")
    info = conninfo_to_dict(configured_url)
    database_name = "axit_phase3_citation_" + uuid4().hex
    maintenance_info = dict(info)
    maintenance_info["dbname"] = "postgres"
    target_info = dict(info)
    target_info["dbname"] = database_name
    with psycopg.connect(**maintenance_info, autocommit=True) as maintenance:
        maintenance.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        try:
            yield make_conninfo(**target_info)
        finally:
            maintenance.execute(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            maintenance.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))


@pytest.fixture
def citation_database_url() -> Iterator[str]:
    with _temporary_database() as database_url:
        upgrade_database(database_url)
        yield database_url


def _seed(connection: psycopg.Connection[dict[str, object]]) -> CitationSeed:
    host_id, member_id, outsider_id = uuid4(), uuid4(), uuid4()
    room_id, session_id, submission_id, revision_id, extraction_id = (uuid4() for _ in range(5))
    snapshot_id, run_id, document_id, segment_id, citation_id, anchor_id = (uuid4() for _ in range(6))
    quote = "Alice: The Tuesday checklist assignment is recorded under my name."
    with connection.transaction():
        with connection.cursor() as cursor:
            for user_id, name in ((host_id, "Host"), (member_id, "Member"), (outsider_id, "Eve")):
                cursor.execute(
                    "INSERT INTO users (id, email, password_hash, display_name) VALUES (%s, %s, 'hash', %s)",
                    (user_id, f"{user_id.hex}@example.test", name),
                )
            cursor.execute("INSERT INTO rooms (id, owner_id, name) VALUES (%s, %s, 'Private')", (room_id, host_id))
            cursor.execute("INSERT INTO room_memberships (room_id, user_id, role) VALUES (%s, %s, 'host'), (%s, %s, 'member')", (room_id, host_id, room_id, member_id))
            cursor.execute("INSERT INTO talk_sessions (id, room_id, host_id, mode, topic, state, generation_epoch) VALUES (%s, %s, %s, 'relay', 'Topic', 'ready', 1)", (session_id, room_id, host_id))
            cursor.execute("INSERT INTO submissions (id, session_id, author_id, kind) VALUES (%s, %s, %s, 'text')", (submission_id, session_id, host_id))
            cursor.execute("INSERT INTO source_revisions (id, submission_id, revision_no, filename, mime_type, byte_size, sha256, source_text, processing_state) VALUES (%s, %s, 1, 'source.txt', 'text/plain', %s, %s, %s, 'queued')", (revision_id, submission_id, len(quote), 'a' * 64, quote))
            cursor.execute("INSERT INTO extraction_runs (id, source_revision_id, parser_name, parser_version, newline_policy, unicode_normalization_profile, config_hash, anchor_schema_version, status, completed_at) VALUES (%s, %s, 'inline-text', '1', 'lf', 'nfc', %s, '1', 'succeeded', CURRENT_TIMESTAMP)", (extraction_id, revision_id, 'b' * 64))
            cursor.execute("UPDATE source_revisions SET approved_extraction_run_id = %s, processing_state = 'ready' WHERE id = %s", (extraction_id, revision_id))
            cursor.execute("INSERT INTO source_anchors (id, extraction_run_id, source_revision_id, ordinal, block_type, text, anchor_json, canonical_hash) VALUES (%s, %s, %s, 0, 'text_line', %s, %s, %s)", (anchor_id, extraction_id, revision_id, quote, Jsonb({"kind": "text_line"}), 'c' * 64))
            cursor.execute("INSERT INTO generation_snapshots (id, session_id, generation_epoch, created_by, topic_copy, pipeline_version, anchor_schema_version) VALUES (%s, %s, 1, %s, 'Topic', 'phase3-v1', '1')", (snapshot_id, session_id, host_id))
            cursor.execute("INSERT INTO snapshot_revisions (snapshot_id, source_revision_id, extraction_run_id) VALUES (%s, %s, %s)", (snapshot_id, revision_id, extraction_id))
            cursor.execute("INSERT INTO generation_runs (id, snapshot_id, kind, provider, model, prompt_version, pipeline_version, state, completed_at) VALUES (%s, %s, 'summary', 'mock', 'fixture-v1', 'mock-provider.prompt.v1', 'phase3-v1', 'succeeded', CURRENT_TIMESTAMP)", (run_id, snapshot_id))
            cursor.execute("INSERT INTO generated_documents (id, run_id, kind, structured_content_json, content_hash) VALUES (%s, %s, 'summary', %s, %s)", (document_id, run_id, Jsonb({"sections": []}), 'd' * 64))
            cursor.execute("INSERT INTO generated_segments (id, document_id, ordinal, text) VALUES (%s, %s, 0, 'Alice reported an assignment.')", (segment_id, document_id))
            cursor.execute("INSERT INTO citations (id, segment_id, target_type, source_anchor_id) VALUES (%s, %s, 'source_anchor', %s)", (citation_id, segment_id, anchor_id))
    return CitationSeed(host_id, member_id, outsider_id, revision_id, anchor_id, citation_id)


def test_citation_resolver_hides_private_targets_before_target_details(
    citation_database_url: str,
) -> None:
    with open_connection(citation_database_url) as connection:
        seed = _seed(connection)
        resolver = CitationResolver()
        for actor_id in (seed.host_id, seed.member_id):
            target = resolver.resolve(connection, citation_id=seed.citation_id, actor_id=actor_id)
            assert target.target_type == "source_anchor"
            assert target.source_anchor_id == seed.anchor_id
            assert target.source_revision_id == seed.revision_id
        with pytest.raises(CitationUnavailableError):
            resolver.resolve(connection, citation_id=seed.citation_id, actor_id=seed.outsider_id)
        viewer = resolver.resolve_source_anchor_for_viewer(
            connection,
            source_revision_id=seed.revision_id,
            source_anchor_id=seed.anchor_id,
            actor_id=seed.member_id,
        )
        assert viewer is not None and viewer.id == seed.anchor_id
        with pytest.raises(CitationUnavailableError):
            resolver.resolve_source_anchor_for_viewer(
                connection,
                source_revision_id=seed.revision_id,
                source_anchor_id=seed.anchor_id,
                actor_id=seed.outsider_id,
            )
