"""Real-PostgreSQL races for Phase 3 private-room and submit/close state."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.auth_service import AuthService, LoginResult, SessionAuthenticationError
from app.collaboration_service import CollaborationService, FriendshipConflictError
from app.db import open_connection
from app.migrations import upgrade_database
from app.session_service import SessionCloseService
from app.text_submission_service import TextSubmissionService, TextSubmissionStateError


pytestmark = pytest.mark.integration


@contextmanager
def _temporary_database() -> Iterator[str]:
    configured_url = os.environ.get("AXIT_TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("AXIT_TEST_DATABASE_URL is required for Phase 3 PostgreSQL integration")
    connection_info = conninfo_to_dict(configured_url)
    database_name = "axit_phase3_concurrency_" + uuid4().hex
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
def phase3_concurrency_database_url() -> Iterator[str]:
    with _temporary_database() as database_url:
        upgrade_database(database_url)
        yield database_url


def _seed_users(
    database_url: str,
) -> tuple[UUID, UUID, UUID, UUID]:
    auth = AuthService()
    collaboration = CollaborationService()
    with open_connection(database_url) as connection:
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
        room = collaboration.create_room(connection, actor_id=alice.id, name="Race room")
    return alice.id, bob.id, eve.id, room.id


def test_concurrent_same_user_logins_leave_one_active_session(
    phase3_concurrency_database_url: str,
) -> None:
    password = "alice-local-password"
    with open_connection(phase3_concurrency_database_url) as connection:
        AuthService().register(
            connection,
            email="alice@example.test",
            password=password,
            display_name="Alice",
        )

    for _ in range(3):
        barrier = Barrier(4)

        def login() -> LoginResult:
            with open_connection(phase3_concurrency_database_url) as connection:
                barrier.wait(timeout=10)
                return AuthService().login(
                    connection,
                    email="alice@example.test",
                    password=password,
                )

        with ThreadPoolExecutor(max_workers=4) as executor:
            login_results = list(executor.map(lambda _: login(), range(4)))

        with open_connection(phase3_concurrency_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM auth_sessions
                    WHERE revoked_at IS NULL
                      AND expires_at > clock_timestamp()
                    """
                )
                active_session_ids = {row["id"] for row in cursor.fetchall()}

        assert len(active_session_ids) == 1
        authentication_outcomes: list[UUID] = []
        for login_result in login_results:
            with open_connection(phase3_concurrency_database_url) as connection:
                try:
                    authenticated = AuthService().authenticate(
                        connection,
                        session_token=login_result.session_token,
                    )
                except SessionAuthenticationError:
                    continue
            authentication_outcomes.append(authenticated.id)

        assert set(authentication_outcomes) == active_session_ids


def test_opposing_friend_request_race_persists_one_canonical_pair(
    phase3_concurrency_database_url: str,
) -> None:
    alice_id, bob_id, _, _ = _seed_users(phase3_concurrency_database_url)
    barrier = Barrier(2)

    def create(actor_id: UUID, addressee_id: UUID) -> str:
        service = CollaborationService()
        with open_connection(phase3_concurrency_database_url) as connection:
            barrier.wait(timeout=10)
            try:
                service.create_friend_request(
                    connection,
                    actor_id=actor_id,
                    addressee_id=addressee_id,
                )
            except FriendshipConflictError:
                return "conflict"
            return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda ids: create(*ids), ((alice_id, bob_id), (bob_id, alice_id))))

    assert sorted(outcomes) == ["conflict", "created"]
    with open_connection(phase3_concurrency_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) AS count FROM friendships")
            assert cursor.fetchone()["count"] == 1


def test_submit_close_race_leaves_one_consistent_snapshot_boundary(
    phase3_concurrency_database_url: str,
) -> None:
    auth = AuthService()
    collaboration = CollaborationService()
    text_submissions = TextSubmissionService()
    with open_connection(phase3_concurrency_database_url) as connection:
        alice_id, bob_id, _, room_id = _seed_users(phase3_concurrency_database_url)
        # _seed_users opened and committed a distinct connection; use this one
        # for the accepted friend/invitation/session setup.
        friend_request = collaboration.create_friend_request(
            connection,
            actor_id=alice_id,
            addressee_id=bob_id,
        )
        collaboration.respond_to_friend_request(
            connection,
            actor_id=bob_id,
            friendship_id=friend_request.id,
            accept=True,
        )
        collaboration.create_room_invitation(
            connection,
            actor_id=alice_id,
            room_id=room_id,
            invitee_id=bob_id,
        )
        session = collaboration.create_talk_session(
            connection,
            actor_id=alice_id,
            room_id=room_id,
            topic="Race-safe snapshot",
        )
        text_submissions.submit(
            connection,
            session_id=session.id,
            actor_id=alice_id,
            text="Alice: baseline source.",
        )
    del auth  # Explicitly show that race proof is independent of auth cookies.

    barrier = Barrier(2)

    def submit_late_text() -> str:
        with open_connection(phase3_concurrency_database_url) as connection:
            barrier.wait(timeout=10)
            try:
                TextSubmissionService().submit(
                    connection,
                    session_id=session.id,
                    actor_id=bob_id,
                    text="Bob: concurrent source.",
                )
            except TextSubmissionStateError:
                return "closed-first"
            return "submitted-first"

    def close_session() -> str:
        with open_connection(phase3_concurrency_database_url) as connection:
            barrier.wait(timeout=10)
            SessionCloseService().close(
                connection,
                session_id=session.id,
                actor_id=alice_id,
                exclusions=(),
                pipeline_version="phase3-concurrency-v1",
            )
            return "closed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        submitted_outcome, close_outcome = list(
            executor.map(lambda task: task(), (submit_late_text, close_session))
        )

    assert close_outcome == "closed"
    assert submitted_outcome in {"submitted-first", "closed-first"}
    with open_connection(phase3_concurrency_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM generation_snapshots WHERE session_id = %s",
                (session.id,),
            )
            snapshot = cursor.fetchone()
            assert snapshot is not None
            cursor.execute(
                "SELECT count(*) AS count FROM snapshot_revisions WHERE snapshot_id = %s",
                (snapshot["id"],),
            )
            snapshot_count = cursor.fetchone()["count"]
            cursor.execute(
                """
                SELECT count(*) AS count
                FROM source_revisions AS revision
                JOIN submissions AS submission ON submission.id = revision.submission_id
                WHERE submission.session_id = %s AND revision.is_current
                """,
                (session.id,),
            )
            current_count = cursor.fetchone()["count"]
    if submitted_outcome == "submitted-first":
        assert snapshot_count == 2
        assert current_count == 2
    else:
        assert snapshot_count == 1
        assert current_count == 1
