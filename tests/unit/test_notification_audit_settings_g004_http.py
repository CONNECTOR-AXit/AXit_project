"""Focused G004 regression coverage for caller-owned HTTP mutation transactions."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

import pytest

from app.auth_service import AuthService
from app.collaboration_service import CollaborationService, FriendshipConflictError
from app.domain import TalkSessionState
from app.file_submission_service import FileSubmissionService
from app.report_suggestions import ReportSuggestionService, ReportSuggestionStateError
from app.session_retry_service import SessionRetryService
from app.session_service import SessionCloseService
from app.text_submission_service import TextSubmissionService


class ActivitiesSpy:
    def __init__(self, error: Exception | None = None, *, fail_on_call: int = 1) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error
        self.fail_on_call = fail_on_call

    def record(self, cursor: object, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if self.error is not None and len(self.calls) == self.fail_on_call:
            raise self.error
        return object()


class Transaction(AbstractContextManager[None]):
    def __init__(self) -> None:
        self.rolled_back = False

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.rolled_back = exc is not None


class QueryCursor(AbstractContextManager["QueryCursor"]):
    def __init__(self, responder: Callable[[str, object], tuple[object, int]]) -> None:
        self.responder = responder
        self.current: object = None
        self.rowcount = 0
        self.statements: list[str] = []

    def execute(self, query: str, params: object = None) -> None:
        self.statements.append(query)
        self.current, self.rowcount = self.responder(query, params)

    def fetchone(self) -> Any:
        if isinstance(self.current, list):
            return self.current[0] if self.current else None
        return self.current

    def fetchall(self) -> list[Any]:
        if isinstance(self.current, list):
            return self.current
        return [] if self.current is None else [self.current]

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class Connection:
    def __init__(self, cursor: QueryCursor) -> None:
        self._cursor = cursor
        self.transactions: list[Transaction] = []

    def transaction(self) -> Transaction:
        transaction = Transaction()
        self.transactions.append(transaction)
        return transaction

    def cursor(self, **kwargs: object) -> QueryCursor:
        return self._cursor


class FastPasswordHasher:
    def hash(self, password: str) -> str:
        return f"hash:{password}"


class BlobStoreStub:
    def __init__(self, temporary: Path) -> None:
        self.temporary = temporary
        self.deleted: list[str | Path] = []

    def temporary_path(self) -> Path:
        return self.temporary

    def commit(self, temporary: Path, *, revision_id: UUID) -> str:
        assert temporary == self.temporary
        return f"revisions/{revision_id}/original"

    def delete(self, key_or_path: str | Path) -> None:
        self.deleted.append(key_or_path)


class QueueStub:
    def enqueue(self, connection: object, **kwargs: object) -> object:
        return object()


def _friendship_view_row(friendship_id: UUID, requester_id: UUID,
                         addressee_id: UUID) -> dict[str, object]:
    return {
        "id": friendship_id,
        "requester_id": requester_id,
        "requester_email": "requester@example.invalid",
        "requester_display_name": "Requester",
        "addressee_id": addressee_id,
        "addressee_email": "addressee@example.invalid",
        "addressee_display_name": "Addressee",
        "status": "pending",
        "created_at": datetime.now(UTC),
    }


def test_registration_defaults_and_audit_share_transaction_failure_boundary() -> None:
    user_id: UUID | None = None

    def responder(query: str, params: object) -> tuple[object, int]:
        nonlocal user_id
        if "INSERT INTO users" in query:
            assert isinstance(params, tuple)
            user_id = params[0]
            return ({"id": user_id, "email": params[1], "display_name": params[3]}, 1)
        return (None, 1)

    cursor = QueryCursor(responder)
    connection = Connection(cursor)
    activities = ActivitiesSpy(RuntimeError("audit insert failed"))
    service = AuthService(password_hasher=FastPasswordHasher(),  # type: ignore[arg-type]
                          activity_service=activities)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="audit insert failed"):
        service.register(connection, email="alice@example.invalid",  # type: ignore[arg-type]
                         password="correct horse battery", display_name="Alice")

    assert connection.transactions[-1].rolled_back is True
    assert user_id is not None
    assert [call["event_type"] for call in activities.calls] == ["account.registered"]
    assert activities.calls[0]["actor_id"] == user_id
    assert activities.calls[0]["audience_user_id"] == user_id
    statements = "\n".join(cursor.statements)
    assert "INSERT INTO user_profiles" in statements
    assert "INSERT INTO notification_preferences" in statements


def test_friend_request_exact_per_audience_cardinality_and_replay_zero_effects() -> None:
    actor_id, addressee_id, friendship_id = uuid4(), uuid4(), uuid4()
    view = _friendship_view_row(friendship_id, actor_id, addressee_id)

    def new_responder(query: str, params: object) -> tuple[object, int]:
        if "SELECT id FROM users" in query:
            return ({"id": addressee_id}, 1)
        if "INSERT INTO friendships" in query:
            return ({"id": friendship_id}, 1)
        if "requester_email" in query:
            return (view, 1)
        return (None, 1)

    activities = ActivitiesSpy()
    service = CollaborationService(activities)  # type: ignore[arg-type]
    connection = Connection(QueryCursor(new_responder))
    service.create_friend_request(connection, actor_id=actor_id,  # type: ignore[arg-type]
                                  addressee_id=addressee_id)

    assert [call["audience_user_id"] for call in activities.calls] == [
        actor_id, addressee_id,
    ]
    assert [len(call["notification_effects"]) for call in activities.calls] == [0, 1]
    assert activities.calls[1]["notification_effects"][0].recipient_ids == (addressee_id,)

    def replay_responder(query: str, params: object) -> tuple[object, int]:
        if "SELECT id FROM users" in query:
            return ({"id": addressee_id}, 1)
        if "INSERT INTO friendships" in query:
            return (None, 0)
        if "FROM friendships" in query and "FOR UPDATE" in query:
            return ({"id": friendship_id, "requester_id": actor_id,
                     "addressee_id": addressee_id, "status": "pending"}, 1)
        if "requester_email" in query:
            return (view, 1)
        return (None, 1)

    replay_activities = ActivitiesSpy()
    replay_service = CollaborationService(replay_activities)  # type: ignore[arg-type]
    replay_service.create_friend_request(
        Connection(QueryCursor(replay_responder)),  # type: ignore[arg-type]
        actor_id=actor_id,
        addressee_id=addressee_id,
    )
    assert replay_activities.calls == []


def test_room_domain_write_rolls_back_when_activity_insert_fails() -> None:
    cursor = QueryCursor(lambda query, params: (None, 1))
    connection = Connection(cursor)
    service = CollaborationService(ActivitiesSpy(RuntimeError("effect failed")))  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="effect failed"):
        service.create_room(connection, actor_id=uuid4(), name="Project")  # type: ignore[arg-type]
    assert connection.transactions[-1].rolled_back is True
    assert any("INSERT INTO rooms" in statement for statement in cursor.statements)
    assert any("INSERT INTO room_memberships" in statement for statement in cursor.statements)


def test_file_blob_is_cleaned_when_activity_insert_aborts_database_transaction(
    tmp_path: Path,
) -> None:
    room_id = uuid4()

    def responder(query: str, params: object) -> tuple[object, int]:
        if "SELECT session_row.state" in query:
            return ({"state": "open", "room_id": room_id}, 1)
        if "current revision count" in query or "count(*) AS count" in query:
            return ({"count": 0}, 1)
        return (None, 1)

    cursor = QueryCursor(responder)
    connection = Connection(cursor)
    blob_store = BlobStoreStub(tmp_path / "upload.tmp")
    service = FileSubmissionService(
        blob_store=blob_store, queue=QueueStub(),  # type: ignore[arg-type]
        activity_service=ActivitiesSpy(RuntimeError("audit insert failed")),  # type: ignore[arg-type]
    )
    with pytest.raises(RuntimeError, match="audit insert failed"):
        service.submit(
            connection, session_id=uuid4(), actor_id=uuid4(),  # type: ignore[arg-type]
            filename="notes.txt", declared_mime_type="text/plain",
            stream=BytesIO(b"safe meeting note"), content_length=17,
        )
    assert connection.transactions[-1].rolled_back is True
    assert len(blob_store.deleted) == 1
    assert str(blob_store.deleted[0]).startswith("revisions/")


@pytest.mark.parametrize("accept,event_type", [(True, "friendship.accepted"),
                                                (False, "friendship.rejected")])
def test_friend_terminal_transition_has_two_audiences_and_replay_zero(
    accept: bool, event_type: str,
) -> None:
    requester, addressee, friendship_id = uuid4(), uuid4(), uuid4()
    target = "accepted" if accept else "rejected"
    view = _friendship_view_row(friendship_id, requester, addressee) | {"status": target}

    def responder(query: str, params: object) -> tuple[object, int]:
        if "SELECT id, requester_id, addressee_id, status" in query:
            return ({"id": friendship_id, "requester_id": requester,
                     "addressee_id": addressee, "status": "pending"}, 1)
        if "requester_email" in query:
            return (view, 1)
        return (None, 1)

    activities = ActivitiesSpy()
    service = CollaborationService(activities)  # type: ignore[arg-type]
    service.respond_to_friend_request(  # type: ignore[arg-type]
        Connection(QueryCursor(responder)), actor_id=addressee,
        friendship_id=friendship_id, accept=accept,
    )
    assert [call["event_type"] for call in activities.calls] == [event_type, event_type]
    assert [call["audience_user_id"] for call in activities.calls] == [requester, addressee]

    def replay(query: str, params: object) -> tuple[object, int]:
        if "SELECT id, requester_id, addressee_id, status" in query:
            return ({"id": friendship_id, "requester_id": requester,
                     "addressee_id": addressee, "status": target}, 1)
        if "requester_email" in query:
            return (view, 1)
        return (None, 1)

    replay_activities = ActivitiesSpy()
    CollaborationService(replay_activities).respond_to_friend_request(  # type: ignore[arg-type]
        Connection(QueryCursor(replay)), actor_id=addressee,
        friendship_id=friendship_id, accept=accept,
    )
    assert replay_activities.calls == []


def _admission_responder(*, room_id: UUID, actor_id: UUID, invitee_id: UUID,
                         invitation_id: UUID, replay: bool = False,
                         departed: bool = False) -> Callable[[str, object], tuple[object, int]]:
    def responder(query: str, params: object) -> tuple[object, int]:
        if "SELECT membership.role" in query:
            return ({"role": "host"}, 1)
        if "SELECT id FROM users" in query:
            return ({"id": invitee_id}, 1)
        if "FROM friendships" in query:
            return ({"id": uuid4(), "requester_id": actor_id,
                     "addressee_id": invitee_id, "status": "accepted"}, 1)
        if "SELECT id,status FROM room_invitations" in query:
            return (({"id": invitation_id, "status": "accepted"} if replay else None),
                    1 if replay else 0)
        if "SELECT left_at FROM room_memberships" in query:
            if not replay:
                return (None, 0)
            return ({"left_at": datetime.now(UTC) if departed else None}, 1)
        if "INSERT INTO room_invitations" in query or "FROM room_invitations WHERE id" in query:
            return ({"id": invitation_id, "room_id": room_id,
                     "invitee_id": invitee_id, "status": "accepted"}, 1)
        return (None, 1)
    return responder


def test_room_admission_first_effect_replay_zero_and_departed_conflict() -> None:
    room_id, actor_id, invitee_id, invitation_id = uuid4(), uuid4(), uuid4(), uuid4()
    activities = ActivitiesSpy()
    service = CollaborationService(activities)  # type: ignore[arg-type]
    service.create_room_invitation(  # type: ignore[arg-type]
        Connection(QueryCursor(_admission_responder(
            room_id=room_id, actor_id=actor_id, invitee_id=invitee_id,
            invitation_id=invitation_id,
        ))), actor_id=actor_id, room_id=room_id, invitee_id=invitee_id,
    )
    assert [call["event_type"] for call in activities.calls] == ["room.member_added"]
    effect = activities.calls[0]["notification_effects"][0]
    assert effect.recipient_ids == (invitee_id,) and effect.action_kind == "open_room"

    replay_activities = ActivitiesSpy()
    replay_cursor = QueryCursor(_admission_responder(
        room_id=room_id, actor_id=actor_id, invitee_id=invitee_id,
        invitation_id=invitation_id, replay=True,
    ))
    CollaborationService(replay_activities).create_room_invitation(  # type: ignore[arg-type]
        Connection(replay_cursor), actor_id=actor_id, room_id=room_id,
        invitee_id=invitee_id,
    )
    assert replay_activities.calls == []
    assert not any("UPDATE room_memberships" in query for query in replay_cursor.statements)

    departed_activities = ActivitiesSpy()
    departed_cursor = QueryCursor(_admission_responder(
        room_id=room_id, actor_id=actor_id, invitee_id=invitee_id,
        invitation_id=invitation_id, replay=True, departed=True,
    ))
    with pytest.raises(FriendshipConflictError, match="cannot be readmitted"):
        CollaborationService(departed_activities).create_room_invitation(  # type: ignore[arg-type]
            Connection(departed_cursor), actor_id=actor_id, room_id=room_id,
            invitee_id=invitee_id,
        )
    assert departed_activities.calls == []
    assert not any("UPDATE room_memberships" in query for query in departed_cursor.statements)


def test_session_create_actor_scope_and_key() -> None:
    room_id, actor_id, session_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)

    def responder(query: str, params: object) -> tuple[object, int]:
        if "SELECT membership.role" in query:
            return ({"role": "host"}, 1)
        if "INSERT INTO talk_sessions" in query:
            assert isinstance(params, tuple)
            return ({"id": params[0], "room_id": room_id, "host_id": actor_id,
                     "topic": "Topic", "description": "", "deadline": None,
                     "state": "open", "generation_epoch": 0, "created_at": now,
                     "closed_at": None}, 1)
        return (None, 1)

    activities = ActivitiesSpy()
    service = CollaborationService(activities)  # type: ignore[arg-type]
    result = service.create_talk_session(  # type: ignore[arg-type]
        Connection(QueryCursor(responder)), actor_id=actor_id, room_id=room_id,
        topic="Topic",
    )
    session_id = result.id
    assert activities.calls[0]["event_key"] == f"session:{session_id}:created"
    assert activities.calls[0]["actor_id"] == actor_id
    assert activities.calls[0]["scope_type"] == "session"
    assert activities.calls[0]["room_id"] == room_id


def _text_responder(*, room_id: UUID, actor_id: UUID, session_id: UUID,
                    submission_id: UUID | None = None) -> Callable[[str, object], tuple[object, int]]:
    def responder(query: str, params: object) -> tuple[object, int]:
        if "SELECT session_row.state, session_row.room_id" in query:
            return ({"state": "open", "room_id": room_id}, 1)
        if "current_revision_count" in query:
            return ({"current_revision_count": 0}, 1)
        if "SELECT submission.id" in query:
            return ({"id": submission_id, "session_id": session_id, "author_id": actor_id,
                     "room_id": room_id, "kind": "text", "title": "Title",
                     "session_state": "open"}, 1)
        if "latest_revision_no" in query:
            return ({"latest_revision_no": 1}, 1)
        return (None, 1)
    return responder


def test_text_create_revise_keys_and_activity_failure_rollbacks() -> None:
    room_id, actor_id, session_id, submission_id = uuid4(), uuid4(), uuid4(), uuid4()
    activities = ActivitiesSpy()
    service = TextSubmissionService(activity_service=activities)  # type: ignore[arg-type]
    created = service.submit(  # type: ignore[arg-type]
        Connection(QueryCursor(_text_responder(
            room_id=room_id, actor_id=actor_id, session_id=session_id,
        ))), session_id=session_id, actor_id=actor_id, text="one", title="Title",
    )
    assert activities.calls[0]["event_key"] == (
        f"submission:{created.id}:revision:1:created"
    )

    revised_activities = ActivitiesSpy()
    revised_service = TextSubmissionService(activity_service=revised_activities)  # type: ignore[arg-type]
    revised_service.replace(  # type: ignore[arg-type]
        Connection(QueryCursor(_text_responder(
            room_id=room_id, actor_id=actor_id, session_id=session_id,
            submission_id=submission_id,
        ))), submission_id=submission_id, actor_id=actor_id, text="two",
    )
    assert revised_activities.calls[0]["event_key"] == (
        f"submission:{submission_id}:revision:2:revised"
    )

    for operation in ("create", "revise"):
        failing = ActivitiesSpy(RuntimeError("audit failed"))
        failing_service = TextSubmissionService(activity_service=failing)  # type: ignore[arg-type]
        connection = Connection(QueryCursor(_text_responder(
            room_id=room_id, actor_id=actor_id, session_id=session_id,
            submission_id=submission_id,
        )))
        with pytest.raises(RuntimeError, match="audit failed"):
            if operation == "create":
                failing_service.submit(  # type: ignore[arg-type]
                    connection, session_id=session_id, actor_id=actor_id, text="one")
            else:
                failing_service.replace(  # type: ignore[arg-type]
                    connection, submission_id=submission_id, actor_id=actor_id, text="two")
        assert connection.transactions[-1].rolled_back is True


def _close_responder(*, session_id: UUID, room_id: UUID, actor_id: UUID,
                     snapshot_id: UUID, replay: bool = False
                     ) -> Callable[[str, object], tuple[object, int]]:
    revision_id, run_id = uuid4(), uuid4()

    def responder(query: str, params: object) -> tuple[object, int]:
        if "SELECT session_row.id, session_row.host_id" in query:
            return ({"id": session_id, "host_id": actor_id, "topic": "Topic",
                     "state": "processing" if replay else "open", "generation_epoch": 4,
                     "state_version": 7, "retry_ordinal": 2, "room_id": room_id}, 1)
        if "SELECT revision.id" in query:
            return ([{"id": revision_id, "processing_state": "ready",
                      "approved_extraction_run_id": run_id,
                      "approved_extraction_status": "succeeded",
                      "approved_anchor_schema_version": "source-anchor.v1"}], 1)
        if "SET state = 'closed'" in query:
            return ({"state_version": 8}, 1)
        if "SET state = 'processing'" in query:
            return ({"state_version": 9}, 1)
        if "FROM generation_snapshots" in query:
            return ({"id": snapshot_id, "generation_epoch": 5}, 1)
        return (None, 1)
    return responder


def test_close_exact_versions_order_failure_and_replay_zero() -> None:
    session_id, room_id, actor_id, snapshot_id = uuid4(), uuid4(), uuid4(), uuid4()
    activities = ActivitiesSpy()
    service = SessionCloseService(activities)  # type: ignore[arg-type]
    result = service.close(  # type: ignore[arg-type]
        Connection(QueryCursor(_close_responder(
            session_id=session_id, room_id=room_id, actor_id=actor_id,
            snapshot_id=snapshot_id,
        ))), session_id=session_id, actor_id=actor_id, exclusions=(),
        pipeline_version="phase2-v1",
    )
    assert result.state is TalkSessionState.PROCESSING and result.generation_epoch == 5
    assert [(call["event_type"], call["event_key"]) for call in activities.calls] == [
        ("session.closed", f"session:{session_id}:state-v8:closed"),
        ("session.processing", f"session:{session_id}:state-v9:processing"),
    ]

    failing = ActivitiesSpy(RuntimeError("second audit failed"), fail_on_call=2)
    connection = Connection(QueryCursor(_close_responder(
        session_id=session_id, room_id=room_id, actor_id=actor_id,
        snapshot_id=snapshot_id,
    )))
    with pytest.raises(RuntimeError, match="second audit failed"):
        SessionCloseService(failing).close(  # type: ignore[arg-type]
            connection, session_id=session_id, actor_id=actor_id, exclusions=(),
            pipeline_version="phase2-v1",
        )
    assert connection.transactions[-1].rolled_back is True

    replay_activities = ActivitiesSpy()
    replay = SessionCloseService(replay_activities).close(  # type: ignore[arg-type]
        Connection(QueryCursor(_close_responder(
            session_id=session_id, room_id=room_id, actor_id=actor_id,
            snapshot_id=snapshot_id, replay=True,
        ))), session_id=session_id, actor_id=actor_id, exclusions=(),
        pipeline_version="phase2-v1",
    )
    assert replay.idempotent is True and replay_activities.calls == []


def _retry_responder(*, session_id: UUID, room_id: UUID, actor_id: UUID,
                     snapshot_id: UUID, replay: bool = False
                     ) -> Callable[[str, object], tuple[object, int]]:
    def responder(query: str, params: object) -> tuple[object, int]:
        if "SELECT session_row.id, session_row.host_id" in query:
            return ({"id": session_id, "host_id": actor_id,
                     "state": "processing" if replay else "needs_attention",
                     "room_id": room_id, "generation_epoch": 4,
                     "state_version": 11, "retry_ordinal": 2}, 1)
        if "FROM generation_snapshots" in query:
            return ({"id": snapshot_id}, 1)
        if "FROM generation_runs" in query and "FOR UPDATE" in query:
            return ([{"id": uuid4(), "kind": "summary", "state": "failed_retryable"}], 1)
        if "UPDATE talk_sessions" in query:
            return ({"state_version": 12, "retry_ordinal": 3}, 1)
        return (None, 1)
    return responder


def test_retry_epoch_versions_order_failure_and_processing_replay_zero() -> None:
    session_id, room_id, actor_id, snapshot_id = uuid4(), uuid4(), uuid4(), uuid4()
    activities = ActivitiesSpy()
    result = SessionRetryService(activities).retry(  # type: ignore[arg-type]
        Connection(QueryCursor(_retry_responder(
            session_id=session_id, room_id=room_id, actor_id=actor_id,
            snapshot_id=snapshot_id,
        ))), session_id=session_id, actor_id=actor_id,
    )
    assert result.requeued_kinds == ("summary",)
    assert [(call["event_type"], call["event_key"]) for call in activities.calls] == [
        ("session.retry_requested", f"session:{session_id}:epoch:4:retry:3"),
        ("session.processing", f"session:{session_id}:state-v12:processing"),
    ]

    failing = ActivitiesSpy(RuntimeError("retry audit failed"), fail_on_call=2)
    connection = Connection(QueryCursor(_retry_responder(
        session_id=session_id, room_id=room_id, actor_id=actor_id,
        snapshot_id=snapshot_id,
    )))
    with pytest.raises(RuntimeError, match="retry audit failed"):
        SessionRetryService(failing).retry(  # type: ignore[arg-type]
            connection, session_id=session_id, actor_id=actor_id,
        )
    assert connection.transactions[-1].rolled_back is True

    replay_activities = ActivitiesSpy()
    replay = SessionRetryService(replay_activities).retry(  # type: ignore[arg-type]
        Connection(QueryCursor(_retry_responder(
            session_id=session_id, room_id=room_id, actor_id=actor_id,
            snapshot_id=snapshot_id, replay=True,
        ))), session_id=session_id, actor_id=actor_id,
    )
    assert replay.requeued_kinds == () and replay_activities.calls == []


def _suggestion_row(*, suggestion_id: UUID, session_id: UUID, actor_id: UUID,
                    snapshot_id: UUID, status: str) -> dict[str, object]:
    now = datetime.now(UTC)
    return {"id": suggestion_id, "session_id": session_id, "author_id": actor_id,
            "source_anchor_id": None, "snapshot_id": snapshot_id,
            "report_content_hash": "a" * 64, "kind": "add", "origin": "member",
            "suggested_text": "Suggestion", "rationale": "", "status": status,
            "resolved_by": actor_id if status != "open" else None,
            "created_at": now, "resolved_at": now if status != "open" else None}


def test_suggestion_create_decision_and_terminal_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrated_report import IntegratedReportIdentity
    import app.report_suggestions as suggestion_module

    session_id, room_id, actor_id, snapshot_id, suggestion_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    monkeypatch.setattr(suggestion_module, "load_report_identity",
                        lambda connection, session_id: IntegratedReportIdentity(snapshot_id, "a" * 64))

    def create_responder(query: str, params: object) -> tuple[object, int]:
        if "SELECT s.room_id" in query:
            return ({"room_id": room_id}, 1)
        if "INSERT INTO report_suggestions" in query:
            assert isinstance(params, tuple)
            return (_suggestion_row(suggestion_id=params[0], session_id=session_id,
                                    actor_id=actor_id, snapshot_id=snapshot_id,
                                    status="open"), 1)
        return (None, 1)

    activities = ActivitiesSpy()
    created = ReportSuggestionService(activities).create(  # type: ignore[arg-type]
        Connection(QueryCursor(create_responder)), session_id=session_id,
        actor_id=actor_id, suggested_text="Suggestion",
    )
    assert activities.calls[0]["event_key"] == f"suggestion:{created.id}:created"

    def decision_responder(query: str, params: object) -> tuple[object, int]:
        if "FROM report_suggestions suggestion" in query:
            return ({"session_id": session_id, "host_id": actor_id, "status": "open",
                     "current_member_id": actor_id, "room_id": room_id}, 1)
        if "UPDATE report_suggestions" in query:
            return (_suggestion_row(suggestion_id=suggestion_id, session_id=session_id,
                                    actor_id=actor_id, snapshot_id=snapshot_id,
                                    status="accepted"), 1)
        return (None, 1)

    decision_activities = ActivitiesSpy()
    ReportSuggestionService(decision_activities).resolve(  # type: ignore[arg-type]
        Connection(QueryCursor(decision_responder)), suggestion_id=suggestion_id,
        actor_id=actor_id, decision="accepted",
    )
    assert decision_activities.calls[0]["event_key"] == (
        f"suggestion:{suggestion_id}:v1:accepted"
    )

    terminal_activities = ActivitiesSpy()
    with pytest.raises(ReportSuggestionStateError, match="already resolved"):
        ReportSuggestionService(terminal_activities).resolve(  # type: ignore[arg-type]
            Connection(QueryCursor(lambda query, params: (
                {"session_id": session_id, "host_id": actor_id, "status": "accepted",
                 "current_member_id": actor_id, "room_id": room_id}, 1
            ))), suggestion_id=suggestion_id, actor_id=actor_id, decision="accepted",
        )
    assert terminal_activities.calls == []
