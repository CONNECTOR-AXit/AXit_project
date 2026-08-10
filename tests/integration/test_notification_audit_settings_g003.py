"""Disposable PostgreSQL execution coverage for G003 schema invariants."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from app.migrations import downgrade_database, upgrade_database
from app.notification_service import NotificationService


pytestmark = pytest.mark.integration


@contextmanager
def _database() -> Iterator[str]:
    configured = os.environ.get("AXIT_TEST_DATABASE_URL")
    if not configured:
        pytest.skip("AXIT_TEST_DATABASE_URL is required for isolated PostgreSQL integration")
    info = conninfo_to_dict(configured)
    name = "axit_g003_" + uuid4().hex
    maintenance_info = dict(info)
    maintenance_info["dbname"] = "postgres"
    target_info = dict(info)
    target_info["dbname"] = name
    target = make_conninfo(**target_info)
    with psycopg.connect(**maintenance_info, autocommit=True) as maintenance:
        maintenance.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            yield target
        finally:
            maintenance.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()",
                (name,),
            )
            maintenance.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))


@pytest.fixture(scope="module")
def g003_database_url() -> Iterator[str]:
    with _database() as database_url:
        upgrade_database(database_url)
        yield database_url


def _user(connection: psycopg.Connection[tuple[object, ...]], *, display_name: str = "User") -> UUID:
    user_id = uuid4()
    connection.execute("INSERT INTO users(id,email,password_hash,display_name) VALUES(%s,%s,'x',%s)",
                       (user_id, f"{user_id}@example.invalid", display_name))
    connection.execute("INSERT INTO user_profiles(user_id) VALUES(%s) ON CONFLICT DO NOTHING", (user_id,))
    return user_id


def _session_graph(connection: psycopg.Connection[tuple[object, ...]]) -> tuple[UUID, UUID, UUID, UUID]:
    owner = _user(connection, display_name="Owner")
    member = _user(connection, display_name="Member")
    room_id, session_id = uuid4(), uuid4()
    connection.execute("INSERT INTO rooms(id,owner_id,name) VALUES(%s,%s,'Room')", (room_id, owner))
    connection.execute("""INSERT INTO room_memberships(room_id,user_id,role) VALUES
                       (%s,%s,'host'),(%s,%s,'member')""", (room_id, owner, room_id, member))
    connection.execute("""INSERT INTO talk_sessions(id,room_id,host_id,mode,topic,state)
                       VALUES(%s,%s,%s,'relay','Topic','open')""", (session_id, room_id, owner))
    return owner, member, room_id, session_id


def _comment(connection: psycopg.Connection[tuple[object, ...]], session_id: UUID,
             author_id: UUID, *, anchor_kind: str | None = None,
             anchor_id: UUID | None = None) -> UUID:
    comment_id = uuid4()
    connection.execute("""INSERT INTO comments(id,session_id,author_id,client_request_id,
                       request_fingerprint,body,anchor_kind,anchor_id)
                       VALUES(%s,%s,%s,%s,%s,'body',%s,%s)""",
                       (comment_id, session_id, author_id, uuid4(), "a" * 64, anchor_kind, anchor_id))
    return comment_id


def _assert_rejected(database_url: str, statement: str, parameters: tuple[object, ...]) -> None:
    with pytest.raises(psycopg.DatabaseError):
        with psycopg.connect(database_url) as connection:
            connection.execute(statement, parameters)


def test_populated_0011_upgrade_backfills_only_pending_friend_request() -> None:
    with _database() as database_url:
        upgrade_database(database_url, "0011_auto_report_suggestions")
        with psycopg.connect(database_url) as connection:
            users = [uuid4() for _ in range(6)]
            for user_id in users:
                connection.execute("INSERT INTO users(id,email,password_hash,display_name) VALUES(%s,%s,'x','U')",
                                   (user_id, f"{user_id}@example.invalid"))
            friendship_ids = [uuid4(), uuid4(), uuid4()]
            for friendship_id, requester, addressee, status in zip(
                friendship_ids, users[::2], users[1::2], ("pending", "accepted", "rejected"), strict=True
            ):
                connection.execute("""INSERT INTO friendships(id,requester_id,addressee_id,status)
                                   VALUES(%s,%s,%s,%s)""", (friendship_id, requester, addressee, status))
        upgrade_database(database_url)
        upgrade_database(database_url)  # repeated upgrade must remain deterministic/no-op
        with psycopg.connect(database_url) as connection:
            notifications = connection.execute(
                "SELECT resource_id,resource_type,recipient_id FROM notifications ORDER BY resource_id").fetchall()
            assert notifications == [(friendship_ids[0], "friend_request", users[1])]
            assert connection.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 0
            assert connection.execute("SELECT count(*) FROM audit_ledger_metadata").fetchone()[0] == 1
            assert connection.execute("SELECT count(*) FROM user_profiles").fetchone()[0] == 6
            assert connection.execute("SELECT count(*) FROM notification_preferences").fetchone()[0] == 36
            defaults = connection.execute("SELECT DISTINCT language,profile_version,preferences_version FROM user_profiles").fetchall()
            assert defaults == [("ko", 0, 0)]


def test_audit_update_and_delete_are_both_rejected(g003_database_url: str) -> None:
    with psycopg.connect(g003_database_url) as connection:
        user_id = _user(connection)
        event_id = uuid4()
        connection.execute("""INSERT INTO audit_events(id,event_key,event_type,scope_type,audience_user_id,
                           entity_type,entity_id) VALUES(%s,%s,'account.registered','personal',%s,'user',%s)""",
                           (event_id, f"test:{event_id}", user_id, user_id))
    _assert_rejected(g003_database_url, "UPDATE audit_events SET metadata_json='{}' WHERE id=%s", (event_id,))
    _assert_rejected(g003_database_url, "DELETE FROM audit_events WHERE id=%s", (event_id,))


def test_session_scope_rejects_noncanonical_room_ancestry(g003_database_url: str) -> None:
    with psycopg.connect(g003_database_url) as connection:
        owner, _, _, session_id = _session_graph(connection)
        other_room = uuid4()
        connection.execute("INSERT INTO rooms(id,owner_id,name) VALUES(%s,%s,'Other')", (other_room, owner))
    _assert_rejected(g003_database_url, """INSERT INTO audit_events(id,event_key,event_type,actor_id,scope_type,
        room_id,session_id,entity_type,entity_id) VALUES(%s,%s,'session.created',%s,'session',%s,%s,'session',%s)""",
        (uuid4(), f"bad:{uuid4()}", owner, other_room, session_id, session_id))
    _assert_rejected(g003_database_url, """INSERT INTO audit_events(id,event_key,event_type,actor_id,scope_type,
        audience_user_id,room_id,entity_type,entity_id) VALUES(%s,%s,'room.created',%s,'personal',%s,%s,'room',%s)""",
        (uuid4(), f"bad-shape:{uuid4()}", owner, owner, other_room, other_room))


def test_comment_report_and_segment_anchors_enforce_session_ancestry(g003_database_url: str) -> None:
    with psycopg.connect(g003_database_url) as connection:
        owner, _, _, session_id = _session_graph(connection)
        other_owner, _, _, other_session = _session_graph(connection)
        snapshot_id, run_id, document_id, segment_id = uuid4(), uuid4(), uuid4(), uuid4()
        connection.execute("""INSERT INTO generation_snapshots(id,session_id,generation_epoch,created_by,
                           topic_copy,pipeline_version,anchor_schema_version)
                           VALUES(%s,%s,1,%s,'Other','p','a')""", (snapshot_id, other_session, other_owner))
        connection.execute("""INSERT INTO generation_runs(id,snapshot_id,kind,provider,model,prompt_version,
                           pipeline_version,state) VALUES(%s,%s,'summary','mock','mock','p','p','succeeded')""",
                           (run_id, snapshot_id))
        connection.execute("""INSERT INTO generated_documents(id,run_id,kind,structured_content_json,content_hash)
                           VALUES(%s,%s,'summary','{}',%s)""", (document_id, run_id, "a" * 64))
        connection.execute("INSERT INTO generated_segments(id,document_id,ordinal,text) VALUES(%s,%s,0,'x')",
                           (segment_id, document_id))
    _assert_rejected(g003_database_url,
        """INSERT INTO comments(id,session_id,author_id,client_request_id,request_fingerprint,body,anchor_kind,anchor_id)
           VALUES(%s,%s,%s,%s,%s,'x','report',%s)""",
        (uuid4(), session_id, owner, uuid4(), "b" * 64, snapshot_id))
    _assert_rejected(g003_database_url,
        """INSERT INTO comments(id,session_id,author_id,client_request_id,request_fingerprint,body,anchor_kind,anchor_id)
           VALUES(%s,%s,%s,%s,%s,'x','generated_segment',%s)""",
        (uuid4(), session_id, owner, uuid4(), "c" * 64, segment_id))


def test_mention_self_nonmember_limit_and_update_are_rejected(g003_database_url: str) -> None:
    with psycopg.connect(g003_database_url) as connection:
        owner, member, room_id, session_id = _session_graph(connection)
        outsider = _user(connection)
        comment_id = _comment(connection, session_id, owner)
    _assert_rejected(g003_database_url, "INSERT INTO comment_mentions(comment_id,user_id) VALUES(%s,%s)",
                     (comment_id, owner))
    _assert_rejected(g003_database_url, "INSERT INTO comment_mentions(comment_id,user_id) VALUES(%s,%s)",
                     (comment_id, outsider))
    with psycopg.connect(g003_database_url) as connection:
        connection.execute("INSERT INTO comment_mentions(comment_id,user_id) VALUES(%s,%s)", (comment_id, member))
    _assert_rejected(g003_database_url, "UPDATE comment_mentions SET user_id=%s WHERE comment_id=%s AND user_id=%s",
                     (outsider, comment_id, member))
    with psycopg.connect(g003_database_url) as connection:
        many = [_user(connection) for _ in range(21)]
        connection.executemany("INSERT INTO room_memberships(room_id,user_id,role) VALUES(%s,%s,'member')",
                               [(room_id, user_id) for user_id in many])
        capped_comment = _comment(connection, session_id, owner)
    with pytest.raises(psycopg.DatabaseError):
        with psycopg.connect(g003_database_url) as connection:
            connection.executemany("INSERT INTO comment_mentions(comment_id,user_id) VALUES(%s,%s)",
                                   [(capped_comment, user_id) for user_id in many])
    _assert_rejected(g003_database_url,
        """INSERT INTO comments(id,session_id,author_id,client_request_id,request_fingerprint,body)
           VALUES(%s,%s,%s,%s,%s,repeat('x',5001))""",
        (uuid4(), session_id, owner, uuid4(), "d" * 64))


@pytest.mark.parametrize(
    ("statement", "suffix"),
    [
        ("""INSERT INTO notifications(id,recipient_id,kind,resource_type,resource_id,action_kind,title,body,dedupe_key)
            VALUES(%s,%s,'comment','comment',%s,'open_room','t','b',%s)""", "bad-pair"),
        ("""INSERT INTO notifications(id,recipient_id,kind,resource_type,resource_id,action_kind,title,body,dedupe_key)
            VALUES(%s,%s,'comment','comment',%s,'open_comment',repeat('t',121),'b',%s)""", "title"),
        ("""INSERT INTO notifications(id,recipient_id,kind,resource_type,resource_id,action_kind,title,body,dedupe_key)
            VALUES(%s,%s,'comment','comment',%s,'open_comment','t',repeat('b',241),%s)""", "body"),
        ("""INSERT INTO email_outbox(id,recipient_id,notification_kind,dedupe_key,template_key,template_data,status)
            VALUES(%s,%s,'comment',%s,'t','[]','queued_local')""", "array"),
        ("""INSERT INTO email_outbox(id,recipient_id,notification_kind,dedupe_key,template_key,template_data,status)
            VALUES(%s,%s,'comment',%s,'t','{}','sent')""", "status"),
        ("""INSERT INTO email_outbox(id,recipient_id,notification_kind,dedupe_key,template_key,template_data,status)
            VALUES(%s,%s,'comment',%s,'t',jsonb_build_object('x',repeat('x',2050)),'queued_local')""", "size"),
    ],
)
def test_notification_and_outbox_catalog_bounds_execute_in_postgresql(
    g003_database_url: str, statement: str, suffix: str
) -> None:
    with psycopg.connect(g003_database_url) as connection:
        user_id = _user(connection)
    parameters = ((uuid4(), user_id, uuid4(), f"{suffix}:{uuid4()}")
                  if "notifications" in statement
                  else (uuid4(), user_id, f"{suffix}:{uuid4()}"))
    _assert_rejected(g003_database_url, statement, parameters)


def test_notification_hrefs_use_session_ids_for_session_and_comment_targets(
    g003_database_url: str,
) -> None:
    with psycopg.connect(g003_database_url, row_factory=dict_row) as connection:
        owner, member, room_id, session_id = _session_graph(connection)
        comment_id = _comment(connection, session_id, owner)
        notification_ids = [uuid4(), uuid4(), uuid4()]
        with connection.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO notifications(id,recipient_id,kind,actor_id,resource_type,resource_id,
                           action_kind,title,body,dedupe_key) VALUES(%s,%s,%s,%s,%s,%s,%s,'t','b',%s)""",
                [
                    (notification_ids[0], member, "room_member_added", owner, "room", room_id,
                     "open_room", f"href-room:{notification_ids[0]}"),
                    (notification_ids[1], member, "analysis_completed", owner, "session", session_id,
                     "open_session", f"href-session:{notification_ids[1]}"),
                    (notification_ids[2], member, "mention", owner, "comment", comment_id,
                     "open_comment", f"href-comment:{notification_ids[2]}"),
                ],
            )
            page, _ = NotificationService().list_notifications(
                cursor, recipient_id=member, limit=10
            )

    hrefs = {item["action_kind"]: item["href"] for item in page.items}
    assert hrefs == {
        "open_room": f"/projects/{room_id}",
        "open_session": f"/projects/{session_id}",
        "open_comment": f"/projects/{session_id}/editor?comment={comment_id}",
    }


def test_injected_failure_rolls_back_domain_audit_and_notification(g003_database_url: str) -> None:
    user_id, event_id, notification_id = uuid4(), uuid4(), uuid4()
    with pytest.raises(RuntimeError, match="inject"):
        with psycopg.connect(g003_database_url) as connection:
            connection.execute("INSERT INTO users(id,email,password_hash,display_name) VALUES(%s,%s,'x','Rollback')",
                               (user_id, f"{user_id}@example.invalid"))
            connection.execute("""INSERT INTO audit_events(id,event_key,event_type,scope_type,audience_user_id,
                               entity_type,entity_id) VALUES(%s,%s,'account.registered','personal',%s,'user',%s)""",
                               (event_id, f"rollback:{event_id}", user_id, user_id))
            connection.execute("""INSERT INTO notifications(id,recipient_id,kind,resource_type,resource_id,
                               action_kind,title,body,dedupe_key) VALUES(%s,%s,'comment','comment',%s,
                               'open_comment','t','b',%s)""",
                               (notification_id, user_id, uuid4(), f"rollback:{notification_id}"))
            raise RuntimeError("inject rollback")
    with psycopg.connect(g003_database_url) as connection:
        assert connection.execute("SELECT count(*) FROM users WHERE id=%s", (user_id,)).fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM audit_events WHERE id=%s", (event_id,)).fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM notifications WHERE id=%s", (notification_id,)).fetchone()[0] == 0


def test_guarded_disposable_downgrade_and_reupgrade() -> None:
    if os.environ.get("AXIT_ALLOW_DESTRUCTIVE_MIGRATION_TEST") != "1":
        pytest.skip("AXIT_ALLOW_DESTRUCTIVE_MIGRATION_TEST=1 is required for destructive disposable migration proof")
    with _database() as database_url:
        upgrade_database(database_url)
        downgrade_database(database_url, "0011_auto_report_suggestions")
        upgrade_database(database_url)
        with psycopg.connect(database_url) as connection:
            assert connection.execute("SELECT to_regclass('public.audit_events')").fetchone()[0] == "audit_events"
