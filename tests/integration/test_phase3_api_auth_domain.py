"""Real-PostgreSQL Phase 3 auth, private-room, and text provenance tests.

The frozen Phase 2 router is intentionally not patched in this worker lane.
These tests exercise the service interfaces the root route adapter wires to
the public API, which proves the durable authorization/domain boundary first.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.auth_service import AuthService, SessionAuthenticationError
from app.collaboration_service import (
    CollaborationAccessError,
    CollaborationService,
)
from app.db import open_connection
from app.migrations import upgrade_database
from app.session_service import SessionCloseService
from app.text_submission_service import (
    TextSubmissionAccessError,
    TextSubmissionOwnerError,
    TextSubmissionStateError,
    TextSubmissionService,
)


pytestmark = pytest.mark.integration


@contextmanager
def _temporary_database() -> Iterator[str]:
    configured_url = os.environ.get("AXIT_TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("AXIT_TEST_DATABASE_URL is required for Phase 3 PostgreSQL integration")
    connection_info = conninfo_to_dict(configured_url)
    database_name = "axit_phase3_auth_" + uuid4().hex
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
def phase3_database_url() -> Iterator[str]:
    with _temporary_database() as database_url:
        upgrade_database(database_url)
        yield database_url


def _register_users(
    connection: psycopg.Connection[dict[str, object]],
    auth: AuthService,
) -> tuple[UUID, UUID, UUID]:
    alice = auth.register(
        connection,
        email="alice@example.test",
        password="alice-local-password",
        display_name="Alice",
    )
    bob = auth.register(
        connection,
        email="bob@example.test",
        password="bob-local-password",
        display_name="Bob",
    )
    eve = auth.register(
        connection,
        email="eve@example.test",
        password="eve-local-password",
        display_name="Eve",
    )
    return alice.id, bob.id, eve.id


def test_auth_friend_room_text_close_and_private_viewer_flow(
    phase3_database_url: str,
) -> None:
    auth = AuthService()
    collaboration = CollaborationService()
    text_submissions = TextSubmissionService()
    with open_connection(phase3_database_url) as connection:
        alice_id, bob_id, eve_id = _register_users(connection, auth)

        first_login = auth.login(
            connection,
            email="ALICE@example.test",
            password="alice-local-password",
        )
        second_login = auth.login(
            connection,
            email="alice@example.test",
            password="alice-local-password",
        )
        with pytest.raises(SessionAuthenticationError):
            auth.authenticate(connection, session_token=first_login.session_token)
        alice_session = auth.authenticate(connection, session_token=second_login.session_token)
        assert auth.csrf_token_for(alice_session) == second_login.csrf_token

        request = collaboration.create_friend_request(
            connection,
            actor_id=alice_id,
            addressee_id=bob_id,
        )
        accepted = collaboration.respond_to_friend_request(
            connection,
            actor_id=bob_id,
            friendship_id=request.id,
            accept=True,
        )
        assert accepted.status == "accepted"
        assert collaboration.list_friends(connection, actor_id=alice_id)[0].user.id == bob_id

        room = collaboration.create_room(connection, actor_id=alice_id, name="Private prep")
        invitation = collaboration.create_room_invitation(
            connection,
            actor_id=alice_id,
            room_id=room.id,
            invitee_id=bob_id,
        )
        assert invitation.status == "accepted"
        assert [item.role for item in collaboration.list_rooms(connection, actor_id=bob_id)] == ["member"]

        talk_session = collaboration.create_talk_session(
            connection,
            actor_id=alice_id,
            room_id=room.id,
            topic="Budget priorities",
            description="Bring a source-grounded proposal.",
        )
        alice_submission = text_submissions.submit(
            connection,
            session_id=talk_session.id,
            actor_id=alice_id,
            text="Alice: Budget review is Friday.\r\nAlice: Bring the risk register.",
        )
        bob_submission = text_submissions.submit(
            connection,
            session_id=talk_session.id,
            actor_id=bob_id,
            text="Bob: I will prepare the draft.",
        )
        assert alice_submission.processing_state == "ready"
        assert bob_submission.processing_state == "ready"

        with pytest.raises(TextSubmissionOwnerError):
            text_submissions.replace(
                connection,
                submission_id=alice_submission.id,
                actor_id=bob_id,
                text="Bob cannot replace Alice's source.",
            )
        with pytest.raises(CollaborationAccessError):
            collaboration.get_talk_session(
                connection,
                actor_id=eve_id,
                session_id=talk_session.id,
            )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT revision.id, revision.source_text, revision.sha256,
                       extraction_run.status, extraction_run.anchor_schema_version
                FROM source_revisions AS revision
                JOIN extraction_runs AS extraction_run
                  ON extraction_run.id = revision.approved_extraction_run_id
                WHERE revision.id = %s
                """,
                (alice_submission.current_revision_id,),
            )
            revision = cursor.fetchone()
            assert revision is not None
            assert revision["source_text"] == (
                "Alice: Budget review is Friday.\nAlice: Bring the risk register."
            )
            assert revision["sha256"] == hashlib.sha256(
                revision["source_text"].encode("utf-8")
            ).hexdigest()
            assert revision["status"] == "succeeded"
            assert revision["anchor_schema_version"] == "1"
            cursor.execute(
                """
                SELECT id, anchor_json, canonical_hash
                FROM source_anchors
                WHERE source_revision_id = %s
                ORDER BY ordinal
                """,
                (alice_submission.current_revision_id,),
            )
            anchors = cursor.fetchall()
        assert len(anchors) == 2
        first_anchor = anchors[0]
        assert first_anchor["anchor_json"]["locator"] == {"end": 31, "line": 1, "start": 0}
        assert len(first_anchor["canonical_hash"]) == 64

        viewer = text_submissions.get_viewer(
            connection,
            actor_id=bob_id,
            revision_id=alice_submission.current_revision_id,
            anchor_id=first_anchor["id"],
        )
        assert viewer.highlighted_anchor is not None
        assert viewer.highlighted_anchor.exact_quote == "Alice: Budget review is Friday."
        with pytest.raises(TextSubmissionAccessError):
            text_submissions.get_viewer(
                connection,
                actor_id=eve_id,
                revision_id=alice_submission.current_revision_id,
            )

        closed = SessionCloseService().close(
            connection,
            session_id=talk_session.id,
            actor_id=alice_id,
            exclusions=(),
            pipeline_version="phase3-text-v1",
        )
        assert closed.state.value == "processing"
        with pytest.raises(TextSubmissionStateError):
            text_submissions.submit(
                connection,
                session_id=talk_session.id,
                actor_id=bob_id,
                text="A late submission cannot alter the snapshot.",
            )

        connection.execute(
            "UPDATE talk_sessions SET state = 'ready' WHERE id = %s",
            (talk_session.id,),
        )
        reopen_service = SessionCloseService()
        assert reopen_service.reopen(
            connection, session_id=talk_session.id, actor_id=alice_id
        ).value == "open"
        assert reopen_service.reopen(
            connection, session_id=talk_session.id, actor_id=alice_id
        ).value == "open"
