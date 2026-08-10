"""Disposable PostgreSQL atomicity proofs deferred from G004 to G010."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from threading import Barrier
from time import perf_counter
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.activity_service import ActivityService
from app.automatic_report_suggestions import (
    AutomaticSuggestionExecution,
    AutomaticSuggestionProposal,
)
from app.collaboration_service import CollaborationService
from app.comments_service import CommentsService
from app.domain import JobState, StaleLeaseError
from app.file_extraction_worker import FileExtractionWorker
from app.file_submission_service import FileSubmissionService, LocalBlobStore
from app.generation_repository import GenerationRepository
from app.integrated_report import report_content_hash
from app.migrations import upgrade_database
from app.queue_repository import PostgresJobQueue
from app.session_retry_service import SessionRetryService
from app.session_service import SessionCloseService


pytestmark = pytest.mark.integration


class _MaterializationStatementCounter:
    """Delegate a real cursor while counting only fan-out INSERT statements."""

    def __init__(self, cursor: psycopg.Cursor[dict[str, Any]]) -> None:
        self._cursor = cursor
        self.notifications = 0
        self.outbox = 0

    def execute(self, query: Any, parameters: Any = None) -> Any:
        normalized = " ".join(str(query).split()).lower()
        if normalized.startswith("insert into notifications"):
            self.notifications += 1
        elif normalized.startswith("insert into email_outbox"):
            self.outbox += 1
        return self._cursor.execute(query, parameters)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


@contextmanager
def _database() -> Iterator[str]:
    configured = os.environ.get("AXIT_TEST_DATABASE_URL")
    if not configured:
        pytest.skip(
            "AXIT_TEST_DATABASE_URL is required for isolated PostgreSQL integration"
        )
    info = conninfo_to_dict(configured)
    name = "axit_g010_" + uuid4().hex
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
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid<>pg_backend_pid()",
                (name,),
            )
            maintenance.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name))
            )


@pytest.fixture(scope="module")  # type: ignore[untyped-decorator]
def g010_database_url() -> Iterator[str]:
    with _database() as database_url:
        upgrade_database(database_url)
        yield database_url


def _user(connection: psycopg.Connection[Any], *, name: str) -> UUID:
    user_id = uuid4()
    connection.execute(
        "INSERT INTO users(id,email,password_hash,display_name) VALUES(%s,%s,'x',%s)",
        (user_id, f"{user_id}@example.invalid", name),
    )
    connection.execute("INSERT INTO user_profiles(user_id) VALUES(%s)", (user_id,))
    connection.execute(
        """INSERT INTO notification_preferences(user_id,kind,channel,enabled)
           SELECT %s,kind,channel,channel='in_app'
           FROM (VALUES ('analysis_completed'),('mention'),('comment')) kinds(kind)
           CROSS JOIN (VALUES ('in_app'),('email_intent')) channels(channel)""",
        (user_id,),
    )
    return user_id


def _room_session(
    connection: psycopg.Connection[Any],
    *,
    state: str = "open",
    member_count: int = 1,
    generation_epoch: int = 0,
    state_version: int = 0,
) -> tuple[UUID, tuple[UUID, ...], UUID, UUID]:
    owner = _user(connection, name="Owner")
    members = tuple(
        _user(connection, name=f"Member {index}") for index in range(member_count)
    )
    room_id, session_id = uuid4(), uuid4()
    connection.execute(
        "INSERT INTO rooms(id,owner_id,name) VALUES(%s,%s,'Room')", (room_id, owner)
    )
    connection.execute(
        "INSERT INTO room_memberships(room_id,user_id,role) VALUES(%s,%s,'host')",
        (room_id, owner),
    )
    with connection.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO room_memberships(room_id,user_id,role) VALUES(%s,%s,'member')",
            [(room_id, member) for member in members],
        )
    connection.execute(
        """INSERT INTO talk_sessions(
               id,room_id,host_id,mode,topic,state,generation_epoch,state_version
           ) VALUES(%s,%s,%s,'relay','Topic',%s,%s,%s)""",
        (session_id, room_id, owner, state, generation_epoch, state_version),
    )
    return owner, members, room_id, session_id


def _approved_revision(
    connection: psycopg.Connection[Any], *, session_id: UUID, author_id: UUID
) -> tuple[UUID, UUID]:
    submission_id, revision_id, run_id = uuid4(), uuid4(), uuid4()
    connection.execute(
        """INSERT INTO submissions(id,session_id,author_id,kind,title)
           VALUES(%s,%s,%s,'text','Source')""",
        (submission_id, session_id, author_id),
    )
    connection.execute(
        """INSERT INTO source_revisions(
               id,submission_id,revision_no,filename,mime_type,byte_size,sha256,
               source_text,processing_state,is_current
           ) VALUES(%s,%s,1,'source.txt','text/plain',1,%s,'x','uploaded',TRUE)""",
        (revision_id, submission_id, "a" * 64),
    )
    connection.execute(
        """INSERT INTO extraction_runs(
               id,source_revision_id,parser_name,parser_version,newline_policy,
               unicode_normalization_profile,config_hash,anchor_schema_version,status
           ) VALUES(%s,%s,'builtin','1','lf','nfc',%s,'anchor-v1','succeeded')""",
        (run_id, revision_id, "b" * 64),
    )
    connection.execute(
        """UPDATE source_revisions
           SET processing_state='ready',approved_extraction_run_id=%s WHERE id=%s""",
        (run_id, revision_id),
    )
    return revision_id, run_id


class _RaiseAfterRecord:
    """Delegate the real append/materialization, then force caller rollback."""

    def __init__(self) -> None:
        self._delegate = ActivityService()

    def record(self, cursor: Any, **kwargs: Any) -> object:
        self._delegate.record(cursor, **kwargs)
        raise RuntimeError("injected activity failure")


def test_friend_request_has_two_audiences_one_notification_and_replay_zero(
    g010_database_url: str,
) -> None:
    with psycopg.connect(g010_database_url) as connection:
        alice = _user(connection, name="Alice")
        bob = _user(connection, name="Bob")
        service = CollaborationService()
        first = service.create_friend_request(
            connection, actor_id=alice, addressee_id=bob
        )
        replay = service.create_friend_request(
            connection, actor_id=alice, addressee_id=bob
        )

        assert replay.id == first.id
        assert (
            connection.execute(
                "SELECT count(*) FROM friendships WHERE id=%s", (first.id,)
            ).fetchone()[0]
            == 1
        )
        audiences = connection.execute(
            """SELECT audience_user_id FROM audit_events
               WHERE entity_type='friendship' AND entity_id=%s ORDER BY audience_user_id""",
            (first.id,),
        ).fetchall()
        assert {row[0] for row in audiences} == {alice, bob}
        assert len(audiences) == 2
        assert (
            connection.execute(
                "SELECT count(*) FROM notifications WHERE resource_id=%s AND recipient_id=%s",
                (first.id, bob),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM email_outbox WHERE recipient_id IN (%s,%s)",
                (alice, bob),
            ).fetchone()[0]
            == 0
        )


def test_friend_acceptance_and_room_admission_replays_have_zero_effects(
    g010_database_url: str,
) -> None:
    with psycopg.connect(g010_database_url) as connection:
        host = _user(connection, name="Host")
        guest = _user(connection, name="Guest")
        service = CollaborationService()
        friendship = service.create_friend_request(
            connection, actor_id=host, addressee_id=guest
        )
        service.respond_to_friend_request(
            connection, actor_id=guest, friendship_id=friendship.id, accept=True
        )
        accepted_replay = service.respond_to_friend_request(
            connection, actor_id=guest, friendship_id=friendship.id, accept=True
        )
        room = service.create_room(connection, actor_id=host, name="Replay Room")
        invitation = service.create_room_invitation(
            connection, actor_id=host, room_id=room.id, invitee_id=guest
        )
        invitation_replay = service.create_room_invitation(
            connection, actor_id=host, room_id=room.id, invitee_id=guest
        )

        assert accepted_replay.status == "accepted"
        assert invitation_replay.id == invitation.id
        assert (
            connection.execute(
                "SELECT count(*) FROM room_memberships WHERE room_id=%s AND user_id=%s",
                (room.id, guest),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM audit_events WHERE entity_id=%s", (friendship.id,)
            ).fetchone()[0]
            == 4
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM audit_events WHERE event_type='room.member_added' AND room_id=%s",
                (room.id,),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM notifications WHERE kind='room_member_added' AND resource_id=%s",
                (room.id,),
            ).fetchone()[0]
            == 1
        )


def test_http_domain_and_activity_rows_roll_back_together(
    g010_database_url: str,
) -> None:
    with psycopg.connect(g010_database_url) as connection:
        actor_id = _user(connection, name="Rollback Actor")
        before = connection.execute("SELECT count(*) FROM rooms").fetchone()[0]
        with pytest.raises(RuntimeError, match="injected activity failure"):
            CollaborationService(cast(Any, _RaiseAfterRecord())).create_room(
                connection, actor_id=actor_id, name="Must Roll Back"
            )
        assert connection.execute("SELECT count(*) FROM rooms").fetchone()[0] == before
        assert (
            connection.execute(
                "SELECT count(*) FROM audit_events WHERE actor_id=%s AND event_type='room.created'",
                (actor_id,),
            ).fetchone()[0]
            == 0
        )


def test_close_and_retry_commit_in_ledger_order_and_replays_are_noops(
    g010_database_url: str,
) -> None:
    with psycopg.connect(g010_database_url, row_factory=dict_row) as connection:
        host, _, _, session_id = _room_session(connection)
        _approved_revision(connection, session_id=session_id, author_id=host)
        close_service = SessionCloseService()
        first = close_service.close(
            connection,
            session_id=session_id,
            actor_id=host,
            exclusions=(),
            pipeline_version="pipeline-v1",
        )
        replay = close_service.close(
            connection,
            session_id=session_id,
            actor_id=host,
            exclusions=(),
            pipeline_version="pipeline-v1",
        )
        assert replay.snapshot_id == first.snapshot_id
        assert replay.idempotent is True
        close_events = connection.execute(
            """SELECT event_type,ledger_sequence FROM audit_events
               WHERE session_id=%s AND event_type IN ('session.closed','session.processing')
               ORDER BY ledger_sequence""",
            (session_id,),
        ).fetchall()
        assert [row["event_type"] for row in close_events] == [
            "session.closed",
            "session.processing",
        ]
        assert close_events[0]["ledger_sequence"] < close_events[1]["ledger_sequence"]
        assert (
            connection.execute(
                "SELECT count(*) AS count FROM generation_snapshots WHERE session_id=%s",
                (session_id,),
            ).fetchone()["count"]
            == 1
        )

        connection.execute(
            """UPDATE generation_runs SET state='failed_retryable',error_code='retry'
               WHERE snapshot_id=%s AND kind='summary'""",
            (first.snapshot_id,),
        )
        connection.execute(
            """UPDATE jobs SET state='failed_retryable',error_code='retry'
               WHERE snapshot_id=%s AND kind='summary'""",
            (first.snapshot_id,),
        )
        connection.execute(
            "UPDATE talk_sessions SET state='needs_attention' WHERE id=%s",
            (session_id,),
        )
        retried = SessionRetryService().retry(
            connection, session_id=session_id, actor_id=host
        )
        retry_replay = SessionRetryService().retry(
            connection, session_id=session_id, actor_id=host
        )
        assert retried.requeued_kinds == ("summary",)
        assert retry_replay.requeued_kinds == ()
        retry_events = connection.execute(
            """SELECT event_type,ledger_sequence FROM audit_events
               WHERE session_id=%s AND event_type IN ('session.retry_requested','session.processing')
               ORDER BY ledger_sequence DESC LIMIT 2""",
            (session_id,),
        ).fetchall()
        assert [row["event_type"] for row in reversed(retry_events)] == [
            "session.retry_requested",
            "session.processing",
        ]
        assert retry_events[1]["ledger_sequence"] < retry_events[0]["ledger_sequence"]


def test_close_activity_failure_rolls_back_state_snapshot_jobs_and_ledger(
    g010_database_url: str,
) -> None:
    with psycopg.connect(g010_database_url) as connection:
        host, _, _, session_id = _room_session(connection)
        _approved_revision(connection, session_id=session_id, author_id=host)
        jobs_before = connection.execute("SELECT count(*) FROM jobs").fetchone()[0]
        with pytest.raises(RuntimeError, match="injected activity failure"):
            SessionCloseService(cast(Any, _RaiseAfterRecord())).close(
                connection,
                session_id=session_id,
                actor_id=host,
                exclusions=(),
                pipeline_version="pipeline-v1",
            )
        state = connection.execute(
            "SELECT state,state_version,generation_epoch FROM talk_sessions WHERE id=%s",
            (session_id,),
        ).fetchone()
        assert state == ("open", 0, 0)
        assert (
            connection.execute(
                "SELECT count(*) FROM generation_snapshots WHERE session_id=%s",
                (session_id,),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == jobs_before
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM audit_events WHERE session_id=%s", (session_id,)
            ).fetchone()[0]
            == 0
        )


def test_first_ready_transition_materializes_once_per_member_and_epoch(
    g010_database_url: str,
) -> None:
    with psycopg.connect(g010_database_url, row_factory=dict_row) as connection:
        _, members, _, session_id = _room_session(
            connection,
            state="processing",
            member_count=2,
            generation_epoch=4,
            state_version=8,
        )
        host = connection.execute(
            "SELECT host_id FROM talk_sessions WHERE id=%s", (session_id,)
        ).fetchone()["host_id"]
        snapshot_id = uuid4()
        connection.execute(
            """INSERT INTO generation_snapshots(
                   id,session_id,generation_epoch,created_by,topic_copy,pipeline_version,
                   anchor_schema_version
               ) VALUES(%s,%s,4,%s,'Topic','pipeline-v1','anchor-v1')""",
            (snapshot_id, session_id, host),
        )
        for kind in ("summary", "research"):
            connection.execute(
                """INSERT INTO generation_runs(
                       id,snapshot_id,kind,provider,model,prompt_version,pipeline_version,state
                   ) VALUES(%s,%s,%s,'mock','fixture','prompt','pipeline-v1','succeeded')""",
                (uuid4(), snapshot_id, kind),
            )
        repository = GenerationRepository()
        with (
            connection.transaction(),
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            first = repository.recompute_aggregate(cursor, snapshot_id=snapshot_id)
        with (
            connection.transaction(),
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            replay = repository.recompute_aggregate(cursor, snapshot_id=snapshot_id)

        assert first.transitioned_to_ready is True
        assert replay.transitioned_to_ready is False
        recipients = {host, *members}
        notification_rows = connection.execute(
            """SELECT recipient_id,count(*) AS count FROM notifications
               WHERE kind='analysis_completed' AND resource_id=%s GROUP BY recipient_id""",
            (session_id,),
        ).fetchall()
        assert {row["recipient_id"] for row in notification_rows} == recipients
        assert all(row["count"] == 1 for row in notification_rows)
        assert (
            connection.execute(
                "SELECT count(*) AS count FROM audit_events WHERE event_type='session.ready' AND session_id=%s",
                (session_id,),
            ).fetchone()["count"]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) AS count FROM jobs WHERE kind='report_suggestions' AND snapshot_id=%s",
                (snapshot_id,),
            ).fetchone()["count"]
            == 1
        )


def test_concurrent_first_ready_race_materializes_each_channel_exactly_once(
    g010_database_url: str,
) -> None:
    with psycopg.connect(g010_database_url, row_factory=dict_row) as connection:
        host, members, _, session_id = _room_session(
            connection,
            state="processing",
            member_count=1,
            generation_epoch=5,
            state_version=10,
        )
        recipients = (host, *members)
        connection.execute(
            """UPDATE notification_preferences SET enabled=TRUE
               WHERE user_id=ANY(%s) AND kind='analysis_completed'
                 AND channel='email_intent'""",
            (list(recipients),),
        )
        snapshot_id = uuid4()
        connection.execute(
            """INSERT INTO generation_snapshots(
                   id,session_id,generation_epoch,created_by,topic_copy,pipeline_version,
                   anchor_schema_version
               ) VALUES(%s,%s,5,%s,'Topic','pipeline-v1','anchor-v1')""",
            (snapshot_id, session_id, host),
        )
        for kind in ("summary", "research"):
            connection.execute(
                """INSERT INTO generation_runs(
                       id,snapshot_id,kind,provider,model,prompt_version,pipeline_version,state
                   ) VALUES(%s,%s,%s,'mock','fixture','prompt','pipeline-v1','succeeded')""",
                (uuid4(), snapshot_id, kind),
            )

    ready = Barrier(2, timeout=10)

    def project_ready() -> bool:
        with (
            psycopg.connect(g010_database_url, row_factory=dict_row) as connection,
            connection.transaction(),
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            cursor.execute("SET LOCAL statement_timeout = '10s'")
            ready.wait()
            projection = GenerationRepository().recompute_aggregate(
                cursor, snapshot_id=snapshot_id
            )
            return bool(projection.transitioned_to_ready)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(project_ready) for _ in range(2)]
        transitions = [future.result(timeout=15) for future in futures]

    assert sorted(transitions) == [False, True]
    with psycopg.connect(g010_database_url, row_factory=dict_row) as connection:
        assert (
            connection.execute(
                """SELECT count(*) AS count FROM audit_events
               WHERE event_type='session.ready' AND session_id=%s""",
                (session_id,),
            ).fetchone()["count"]
            == 1
        )
        notifications = connection.execute(
            """SELECT recipient_id,count(*) AS count FROM notifications
               WHERE kind='analysis_completed' AND resource_id=%s
               GROUP BY recipient_id""",
            (session_id,),
        ).fetchall()
        outbox = connection.execute(
            """SELECT recipient_id,count(*) AS count FROM email_outbox
               WHERE notification_kind='analysis_completed'
                 AND template_data->>'session_id'=%s
               GROUP BY recipient_id""",
            (str(session_id),),
        ).fetchall()
        assert {row["recipient_id"]: row["count"] for row in notifications} == {
            recipient: 1 for recipient in recipients
        }
        assert {row["recipient_id"]: row["count"] for row in outbox} == {
            recipient: 1 for recipient in recipients
        }
        assert (
            connection.execute(
                """SELECT count(*) AS count FROM jobs
               WHERE kind='report_suggestions' AND snapshot_id=%s""",
                (snapshot_id,),
            ).fetchone()["count"]
            == 1
        )


def test_warmed_50_member_comment_and_analysis_fanout_is_bounded_and_fast(
    g010_database_url: str,
) -> None:
    with psycopg.connect(g010_database_url, row_factory=dict_row) as connection:
        comment_author, comment_members, _, comment_session_id = _room_session(
            connection,
            member_count=49,
        )
        comment_audience = (comment_author, *comment_members)
        connection.execute(
            """UPDATE notification_preferences SET enabled=TRUE
               WHERE user_id=ANY(%s) AND kind='comment'""",
            (list(comment_audience),),
        )

        # Warm the same PostgreSQL plans on a small committed fan-out before timing.
        warm_author, warm_members, _, warm_session_id = _room_session(
            connection,
            state="processing",
            member_count=1,
            generation_epoch=1,
            state_version=2,
        )
        connection.execute(
            """UPDATE notification_preferences SET enabled=TRUE
               WHERE user_id=ANY(%s) AND kind IN ('comment','analysis_completed')""",
            ([warm_author, *warm_members],),
        )
        with connection.cursor(row_factory=dict_row) as raw_cursor:
            CommentsService().create(
                raw_cursor,
                session_id=warm_session_id,
                author_id=warm_author,
                client_request_id=uuid4(),
                body="warm comment fanout",
                anchor_kind=None,
                anchor_id=None,
                mentioned_user_ids=(),
            )
            warm_snapshot_id = uuid4()
            raw_cursor.execute(
                """INSERT INTO generation_snapshots(
                       id,session_id,generation_epoch,created_by,topic_copy,pipeline_version,
                       anchor_schema_version
                   ) VALUES(%s,%s,1,%s,'Warm','pipeline-v1','anchor-v1')""",
                (warm_snapshot_id, warm_session_id, warm_author),
            )
            for kind in ("summary", "research"):
                raw_cursor.execute(
                    """INSERT INTO generation_runs(
                           id,snapshot_id,kind,provider,model,prompt_version,pipeline_version,state
                       ) VALUES(%s,%s,%s,'mock','fixture','prompt','pipeline-v1','succeeded')""",
                    (uuid4(), warm_snapshot_id, kind),
                )
            GenerationRepository().recompute_aggregate(
                raw_cursor,
                snapshot_id=warm_snapshot_id,
            )

        client_request_id = uuid4()
        with connection.cursor(row_factory=dict_row) as raw_cursor:
            cursor = _MaterializationStatementCounter(raw_cursor)
            started = perf_counter()
            comment = CommentsService().create(
                cast(Any, cursor),
                session_id=comment_session_id,
                author_id=comment_author,
                client_request_id=client_request_id,
                body="bounded 50 member comment fanout",
                anchor_kind=None,
                anchor_id=None,
                mentioned_user_ids=(),
            )
            comment_elapsed = perf_counter() - started
            replay = CommentsService().create(
                cast(Any, cursor),
                session_id=comment_session_id,
                author_id=comment_author,
                client_request_id=client_request_id,
                body="bounded 50 member comment fanout",
                anchor_kind=None,
                anchor_id=None,
                mentioned_user_ids=(),
            )

        assert len(comment_audience) == 50
        assert comment_elapsed < 2.0
        assert replay.id == comment.id and replay.idempotent is True
        assert (cursor.notifications, cursor.outbox) == (1, 1)
        assert (
            connection.execute(
                """SELECT count(*) AS count FROM notifications
               WHERE kind='comment' AND resource_id=%s""",
                (comment.id,),
            ).fetchone()["count"]
            == 49
        )
        assert (
            connection.execute(
                """SELECT count(*) AS count FROM email_outbox
               WHERE notification_kind='comment'
                 AND template_data->>'comment_id'=%s""",
                (str(comment.id),),
            ).fetchone()["count"]
            == 49
        )

        analysis_host, analysis_members, _, analysis_session_id = _room_session(
            connection,
            state="processing",
            member_count=49,
            generation_epoch=9,
            state_version=18,
        )
        analysis_audience = (analysis_host, *analysis_members)
        connection.execute(
            """UPDATE notification_preferences SET enabled=TRUE
               WHERE user_id=ANY(%s) AND kind='analysis_completed'""",
            (list(analysis_audience),),
        )
        snapshot_id = uuid4()
        connection.execute(
            """INSERT INTO generation_snapshots(
                   id,session_id,generation_epoch,created_by,topic_copy,pipeline_version,
                   anchor_schema_version
               ) VALUES(%s,%s,9,%s,'Topic','pipeline-v1','anchor-v1')""",
            (snapshot_id, analysis_session_id, analysis_host),
        )
        for kind in ("summary", "research"):
            connection.execute(
                """INSERT INTO generation_runs(
                       id,snapshot_id,kind,provider,model,prompt_version,pipeline_version,state
                   ) VALUES(%s,%s,%s,'mock','fixture','prompt','pipeline-v1','succeeded')""",
                (uuid4(), snapshot_id, kind),
            )

        with connection.cursor(row_factory=dict_row) as raw_cursor:
            cursor = _MaterializationStatementCounter(raw_cursor)
            started = perf_counter()
            first = GenerationRepository().recompute_aggregate(
                cast(Any, cursor),
                snapshot_id=snapshot_id,
            )
            analysis_elapsed = perf_counter() - started
            replay_projection = GenerationRepository().recompute_aggregate(
                cast(Any, cursor),
                snapshot_id=snapshot_id,
            )

        assert len(analysis_audience) == 50
        assert analysis_elapsed < 2.0
        assert first.transitioned_to_ready is True
        assert replay_projection.transitioned_to_ready is False
        assert (cursor.notifications, cursor.outbox) == (1, 1)
        assert (
            connection.execute(
                """SELECT count(*) AS count FROM notifications
               WHERE kind='analysis_completed' AND resource_id=%s""",
                (analysis_session_id,),
            ).fetchone()["count"]
            == 50
        )
        assert (
            connection.execute(
                """SELECT count(*) AS count FROM email_outbox
               WHERE notification_kind='analysis_completed'
                 AND template_data->>'session_id'=%s""",
                (str(analysis_session_id),),
            ).fetchone()["count"]
            == 50
        )


def test_stale_queue_completion_never_invokes_domain_effect(
    g010_database_url: str,
) -> None:
    queue = PostgresJobQueue()
    with psycopg.connect(g010_database_url) as connection:
        job = queue.enqueue(
            connection,
            logical_key=f"stale-proof:{uuid4()}",
            kind="extraction",
            payload={"proof": True},
        )
        claimed = queue.claim_next(
            connection, owner="g010-first", lease_seconds=60, kinds={"extraction"}
        )
        assert claimed is not None and claimed.id == job.id
        queue.complete(
            connection,
            claimed,
            target_state=JobState.SUCCEEDED,
            result={"winner": True},
        )
        marker = uuid4()

        def stale_effect(cursor: Any) -> None:
            cursor.execute(
                """INSERT INTO audit_events(
                       id,event_key,event_type,scope_type,audience_user_id,entity_type,entity_id
                   ) SELECT %s,%s,'account.registered','personal',id,'user',id
                     FROM users LIMIT 1""",
                (marker, f"stale:{marker}"),
            )

        with pytest.raises(StaleLeaseError):
            queue.complete_with_effects(
                connection,
                claimed,
                target_state=JobState.SUCCEEDED,
                result={"winner": False},
                effect=stale_effect,
            )
        assert (
            connection.execute(
                "SELECT count(*) FROM audit_events WHERE id=%s", (marker,)
            ).fetchone()[0]
            == 0
        )


def test_automatic_suggestions_audit_only_newly_inserted_rows(
    g010_database_url: str,
) -> None:
    with psycopg.connect(g010_database_url, row_factory=dict_row) as connection:
        author, _, room_id, session_id = _room_session(
            connection, state="ready", generation_epoch=1
        )
        snapshot_id = uuid4()
        connection.execute(
            """INSERT INTO generation_snapshots(
                   id,session_id,generation_epoch,created_by,topic_copy,pipeline_version,
                   anchor_schema_version
               ) VALUES(%s,%s,1,%s,'Topic','pipeline-v1','anchor-v1')""",
            (snapshot_id, session_id, author),
        )
        summary_hash, research_hash = "d" * 64, "e" * 64
        for kind, content_hash in (
            ("summary", summary_hash),
            ("research", research_hash),
        ):
            run_id = uuid4()
            connection.execute(
                """INSERT INTO generation_runs(
                       id,snapshot_id,kind,provider,model,prompt_version,pipeline_version,state
                   ) VALUES(%s,%s,%s,'mock','fixture','prompt','pipeline-v1','succeeded')""",
                (run_id, snapshot_id, kind),
            )
            connection.execute(
                """INSERT INTO generated_documents(
                       id,run_id,kind,structured_content_json,content_hash
                   ) VALUES(%s,%s,%s,%s,%s)""",
                (uuid4(), run_id, kind, Jsonb({"kind": kind}), content_hash),
            )
        canonical_report_hash = report_content_hash(summary_hash, research_hash)
        proposals = tuple(
            AutomaticSuggestionProposal(
                key,
                "add",
                cast(Any, None),
                f"suggestion {key}",
                "comparison",
            )
            for key in ("a" * 64, "b" * 64)
        )
        first_result, first_effect = AutomaticSuggestionExecution(
            snapshot_id,
            session_id,
            room_id,
            author,
            canonical_report_hash,
            proposals[:1],
        ).fenced_completion()
        with (
            connection.transaction(),
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            first_effect(cursor)
        second_result, second_effect = AutomaticSuggestionExecution(
            snapshot_id,
            session_id,
            room_id,
            author,
            canonical_report_hash,
            proposals,
        ).fenced_completion()
        with (
            connection.transaction(),
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            second_effect(cursor)

        assert first_result["suggestion_count"] == 1
        assert second_result["suggestion_count"] == 1
        assert (
            connection.execute(
                "SELECT count(*) AS count FROM report_suggestions WHERE snapshot_id=%s",
                (snapshot_id,),
            ).fetchone()["count"]
            == 2
        )
        assert (
            connection.execute(
                "SELECT count(*) AS count FROM audit_events WHERE event_type='suggestion.created' AND session_id=%s",
                (session_id,),
            ).fetchone()["count"]
            == 2
        )


def test_file_activity_failure_removes_staged_blob_and_rolls_back_rows(
    g010_database_url: str, tmp_path: Path
) -> None:
    blob_store = LocalBlobStore(tmp_path / "blobs")
    with psycopg.connect(g010_database_url) as connection:
        actor, _, _, session_id = _room_session(connection)
        service = FileSubmissionService(
            blob_store=blob_store,
            activity_service=cast(Any, _RaiseAfterRecord()),
        )
        with pytest.raises(RuntimeError, match="injected activity failure"):
            service.submit(
                connection,
                session_id=session_id,
                actor_id=actor,
                filename="source.txt",
                declared_mime_type="text/plain",
                stream=BytesIO(b"grounded source"),
                content_length=len(b"grounded source"),
            )
        assert list(blob_store.root.iterdir()) == []
        assert (
            connection.execute(
                "SELECT count(*) FROM submissions WHERE session_id=%s", (session_id,)
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM audit_events WHERE session_id=%s", (session_id,)
            ).fetchone()[0]
            == 0
        )


def test_extraction_success_commits_attempt_event_with_terminal_effects(
    g010_database_url: str, tmp_path: Path
) -> None:
    blob_store = LocalBlobStore(tmp_path / "success-blobs")
    with psycopg.connect(g010_database_url) as connection:
        actor, _, _, session_id = _room_session(connection)
        submitted = FileSubmissionService(blob_store=blob_store).submit(
            connection,
            session_id=session_id,
            actor_id=actor,
            filename="source.txt",
            declared_mime_type="text/plain",
            stream=BytesIO(b"grounded source"),
            content_length=len(b"grounded source"),
        )

    @contextmanager
    def connections() -> Iterator[psycopg.Connection[Any]]:
        with psycopg.connect(g010_database_url, row_factory=dict_row) as connection:
            yield connection

    result = FileExtractionWorker(
        connection_factory=connections,
        blob_store=blob_store,
        sandbox_adapter=object(),
    ).run_once("g010-success")

    assert result is not None and result["revision_id"] == str(
        submitted.current_revision_id
    )
    with psycopg.connect(g010_database_url, row_factory=dict_row) as connection:
        revision = connection.execute(
            """SELECT processing_state,approved_extraction_run_id
               FROM source_revisions WHERE id=%s""",
            (submitted.current_revision_id,),
        ).fetchone()
        assert revision is not None and revision["processing_state"] == "ready"
        event = connection.execute(
            """SELECT event_key FROM audit_events
               WHERE event_type='source_revision.ready' AND entity_id=%s""",
            (submitted.current_revision_id,),
        ).fetchone()
        assert event is not None and ":attempt:" in event["event_key"]
        assert (
            connection.execute(
                "SELECT count(*) AS count FROM extraction_runs WHERE source_revision_id=%s",
                (submitted.current_revision_id,),
            ).fetchone()["count"]
            == 1
        )


def test_extraction_terminal_failure_commits_attempt_event_once(
    g010_database_url: str, tmp_path: Path
) -> None:
    blob_store = LocalBlobStore(tmp_path / "terminal-blobs")
    with psycopg.connect(g010_database_url, row_factory=dict_row) as connection:
        actor, _, _, session_id = _room_session(connection)
        submitted = FileSubmissionService(blob_store=blob_store).submit(
            connection,
            session_id=session_id,
            actor_id=actor,
            filename="source.txt",
            declared_mime_type="text/plain",
            stream=BytesIO(b"missing source"),
            content_length=len(b"missing source"),
        )
        storage = connection.execute(
            "SELECT storage_key FROM source_revisions WHERE id=%s",
            (submitted.current_revision_id,),
        ).fetchone()
        assert storage is not None
        # Preserve a regular local file but violate its persisted size/hash so the
        # public blob-store boundary raises the expected typed source error.
        blob_store.path_for(storage["storage_key"]).write_bytes(b"tampered")

    @contextmanager
    def connections() -> Iterator[psycopg.Connection[Any]]:
        with psycopg.connect(g010_database_url, row_factory=dict_row) as connection:
            yield connection

    result = FileExtractionWorker(
        connection_factory=connections,
        blob_store=blob_store,
        sandbox_adapter=object(),
    ).run_once("g010-terminal")

    assert result == {"outcome": "failed"}
    with psycopg.connect(g010_database_url, row_factory=dict_row) as connection:
        job = connection.execute(
            "SELECT state,error_code FROM jobs WHERE payload_json->>'revision_id'=%s",
            (str(submitted.current_revision_id),),
        ).fetchone()
        assert job is not None
        assert (job["state"], job["error_code"]) == (
            "failed_terminal",
            "SOURCE_BLOB_UNAVAILABLE",
        )
        assert (
            connection.execute(
                "SELECT processing_state FROM source_revisions WHERE id=%s",
                (submitted.current_revision_id,),
            ).fetchone()["processing_state"]
            == "failed"
        )
        events = connection.execute(
            """SELECT event_key FROM audit_events
               WHERE event_type='source_revision.failed' AND entity_id=%s""",
            (submitted.current_revision_id,),
        ).fetchall()
        assert len(events) == 1
        assert ":attempt:" in events[0]["event_key"]


def test_extraction_reconciliation_is_terminal_once_and_retry_is_noop(
    g010_database_url: str, tmp_path: Path
) -> None:
    blob_store = LocalBlobStore(tmp_path / "reconcile-blobs")
    with psycopg.connect(g010_database_url, row_factory=dict_row) as connection:
        actor, _, _, session_id = _room_session(connection)
        submitted = FileSubmissionService(blob_store=blob_store).submit(
            connection,
            session_id=session_id,
            actor_id=actor,
            filename="source.txt",
            declared_mime_type="text/plain",
            stream=BytesIO(b"repair source"),
            content_length=len(b"repair source"),
        )
        job = connection.execute(
            "SELECT id FROM jobs WHERE payload_json->>'revision_id'=%s",
            (str(submitted.current_revision_id),),
        ).fetchone()
        assert job is not None
        connection.execute(
            """UPDATE jobs SET state='failed_retryable',lease_generation=3,
                   error_code='retryable_failure'
               WHERE id=%s""",
            (job["id"],),
        )

    @contextmanager
    def connections() -> Iterator[psycopg.Connection[Any]]:
        with psycopg.connect(g010_database_url, row_factory=dict_row) as connection:
            yield connection

    worker = FileExtractionWorker(
        connection_factory=connections,
        blob_store=blob_store,
        sandbox_adapter=object(),
    )
    assert worker.run_once("g010-reconcile") is None
    assert worker.run_once("g010-reconcile-replay") is None

    with psycopg.connect(g010_database_url, row_factory=dict_row) as connection:
        assert (
            connection.execute(
                "SELECT state FROM jobs WHERE id=%s", (job["id"],)
            ).fetchone()["state"]
            == "failed_terminal"
        )
        assert (
            connection.execute(
                "SELECT processing_state FROM source_revisions WHERE id=%s",
                (submitted.current_revision_id,),
            ).fetchone()["processing_state"]
            == "failed"
        )
        events = connection.execute(
            """SELECT event_key FROM audit_events
               WHERE event_type='source_revision.failed' AND entity_id=%s""",
            (submitted.current_revision_id,),
        ).fetchall()
        assert len(events) == 1
        assert events[0]["event_key"] == (
            f"revision:{submitted.current_revision_id}:reconcile:{job['id']}:failed"
        )
