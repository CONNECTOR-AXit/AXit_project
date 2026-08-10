"""Focused regression tests for G003 caller-cursor core services."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
import logging
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.activity_pagination import (
    InvalidCursorError,
    decode_event_cursor,
    decode_time_cursor,
    encode_event_cursor,
    encode_time_cursor,
)
from app.activity_repository import ActivityRepository, AppendedActivity
from app.activity_service import (
    ActivityService,
    NotificationEffect,
    activity_observability_snapshot,
)
from app.comments_repository import CommentsRepository, SessionAccess
from app.comments_service import CommentReplayConflictError, CommentsService
from app.notification_service import notification_href
from app.notification_repository import NotificationRepository, RecipientPreference
from app.profile_repository import (
    DEFAULT_PREFERENCES,
    ProfileInvariantError,
    ProfileRepository,
)
from app.profile_service import ProfileService


class ScriptedCursor:
    def __init__(self, responses: list[Any] | None = None) -> None:
        self.responses = deque(responses or [])
        self.current: Any = None
        self.statements: list[tuple[str, object]] = []
        self.rowcount = 1

    def execute(self, query: str, params: object = None) -> None:
        self.statements.append((query, params))
        self.current = self.responses.popleft() if self.responses else None

    def executemany(self, query: str, params: object) -> None:
        self.statements.append((query, params))

    def fetchone(self) -> Any:
        return (
            self.current
            if not isinstance(self.current, list)
            else (self.current[0] if self.current else None)
        )

    def fetchall(self) -> list[Any]:
        return (
            self.current
            if isinstance(self.current, list)
            else ([] if self.current is None else [self.current])
        )


class ActivityRepositoryStub:
    def __init__(self, result: AppendedActivity | None) -> None:
        self.result = result

    def append(self, cursor: object, **kwargs: object) -> AppendedActivity | None:
        return self.result


class NotificationRepositoryStub:
    def __init__(
        self,
        materialized: tuple[int, int] = (0, 0),
        recipients: tuple[RecipientPreference, ...] = (),
    ) -> None:
        self.snapshot_calls = 0
        self.materialize_calls = 0
        self.materialized = materialized
        self.recipients = recipients

    def snapshot_preferences(
        self, cursor: object, **kwargs: object
    ) -> tuple[RecipientPreference, ...]:
        self.snapshot_calls += 1
        return self.recipients

    def materialize(self, cursor: object, **kwargs: object) -> tuple[int, int]:
        self.materialize_calls += 1
        return self.materialized


class ActivitiesSpy:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error

    def record(self, cursor: object, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return object()


class ProfileRepositoryStub:
    def __init__(
        self,
        row: dict[str, Any],
        preferences: dict[tuple[str, str], bool] | None = None,
    ) -> None:
        self.row = row
        self.preference_values = preferences or {}

    def lock_profile(self, cursor: object, user_id: UUID) -> dict[str, Any]:
        return self.row

    def preferences(self, cursor: object, user_id: UUID) -> dict[tuple[str, str], bool]:
        return self.preference_values


class CommentsRepositoryStub:
    def __init__(self, access: SessionAccess) -> None:
        self.access = access
        self.inserted: list[tuple[UUID, ...]] = []

    def require_membership(self, cursor: object, **kwargs: object) -> SessionAccess:
        return self.access

    def insert_mentions(
        self, cursor: object, *, comment_id: UUID, mentioned_user_ids: tuple[UUID, ...]
    ) -> None:
        self.inserted.append(mentioned_user_ids)


def _profile(user_id: UUID) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": user_id,
        "email": "a.invalid",
        "display_name": "Alice",
        "job_title": None,
        "language": "ko",
        "profile_version": 0,
        "preferences_version": 0,
        "profile_updated_at": now,
        "preferences_updated_at": now,
    }


def test_authoritative_record_never_materializes_without_new_audit_authority() -> None:
    notifications = NotificationRepositoryStub()
    service = ActivityService(ActivityRepositoryStub(None), notifications)  # type: ignore[arg-type]
    effect = NotificationEffect(
        (uuid4(),),
        "comment",
        "comment",
        uuid4(),
        "open_comment",
        "title",
        "body",
        "template",
        {},
    )
    result = service.record(
        ScriptedCursor(),
        event_key="comment:key",
        event_type="comment.created",
        actor_id=uuid4(),
        scope_type="session",
        room_id=uuid4(),
        session_id=uuid4(),
        entity_type="comment",
        entity_id=uuid4(),
        notification_effects=(effect,),
    )  # type: ignore[arg-type]
    assert result.activity is None
    assert (notifications.snapshot_calls, notifications.materialize_calls) == (0, 0)


def test_profile_noop_has_no_audit_and_changed_write_propagates_activity_failure() -> (
    None
):
    user_id = uuid4()
    repository = ProfileRepositoryStub(_profile(user_id))
    no_op_activity = ActivitiesSpy()
    service = ProfileService(repository, no_op_activity)  # type: ignore[arg-type]
    assert (
        service.update_profile(
            ScriptedCursor(),
            user_id=user_id,
            expected_version=0,
            display_name="Alice",
            job_title=None,
            language="ko",
        ).updated
        is False
    )  # type: ignore[arg-type]
    assert no_op_activity.calls == []

    failing_activity = ActivitiesSpy(RuntimeError("audit insert failed"))
    service = ProfileService(repository, failing_activity)  # type: ignore[arg-type]
    cursor = ScriptedCursor([None, {"profile_version": 1}])
    with pytest.raises(RuntimeError, match="audit insert failed"):
        service.update_profile(
            cursor,
            user_id=user_id,
            expected_version=0,
            display_name="Alice 2",
            job_title=None,
            language="ko",
        )  # type: ignore[arg-type]
    assert any("UPDATE users" in statement for statement, _ in cursor.statements)
    assert len(failing_activity.calls) == 1


def test_profile_and_preferences_reads_are_own_aggregate_snapshots() -> None:
    user_id = uuid4()
    values = {("comment", "in_app"): True}
    service = ProfileService(
        ProfileRepositoryStub(_profile(user_id), values), ActivitiesSpy()
    )  # type: ignore[arg-type]
    profile = service.get_profile(ScriptedCursor(), user_id=user_id)  # type: ignore[arg-type]
    preferences = service.get_preferences(ScriptedCursor(), user_id=user_id)  # type: ignore[arg-type]
    assert profile["user_id"] == user_id and profile["email"] == "a.invalid"
    assert preferences["values"] == values and preferences["preferences_version"] == 0


def test_profile_reads_never_repair_missing_aggregate_rows() -> None:
    user_id = uuid4()
    cursor = ScriptedCursor([None])
    with pytest.raises(ProfileInvariantError, match="aggregate is incomplete"):
        ProfileService().get_profile(cursor, user_id=user_id)  # type: ignore[arg-type]
    assert len(cursor.statements) == 1
    assert cursor.statements[0][0].lstrip().startswith("SELECT")

    cursor = ScriptedCursor([_profile(user_id), []])
    with pytest.raises(ProfileInvariantError, match="aggregate is incomplete"):
        ProfileService().get_preferences(cursor, user_id=user_id)  # type: ignore[arg-type]
    assert all(
        statement.lstrip().startswith("SELECT") for statement, _ in cursor.statements
    )


def test_profile_repository_requires_the_complete_preference_matrix() -> None:
    rows = [
        {"kind": kind, "channel": channel, "enabled": enabled}
        for (kind, channel), enabled in DEFAULT_PREFERENCES.items()
    ]
    assert (
        ProfileRepository().preferences(ScriptedCursor([rows]), uuid4())
        == DEFAULT_PREFERENCES
    )  # type: ignore[arg-type]


def test_preferences_noop_has_no_audit_and_change_records_once() -> None:
    user_id = uuid4()
    from app.profile_repository import DEFAULT_PREFERENCES

    current = dict(DEFAULT_PREFERENCES)
    activities = ActivitiesSpy()
    service = ProfileService(
        ProfileRepositoryStub(_profile(user_id), current), activities
    )  # type: ignore[arg-type]
    assert (
        service.update_preferences(
            ScriptedCursor(), user_id=user_id, expected_version=0, values=current
        ).updated
        is False
    )  # type: ignore[arg-type]
    changed = dict(current)
    changed[("comment", "email_intent")] = True
    result = service.update_preferences(
        ScriptedCursor([{"preferences_version": 1}]),
        user_id=user_id,
        expected_version=0,
        values=changed,
    )  # type: ignore[arg-type]
    assert result.updated is True and result.version == 1 and len(activities.calls) == 1


def test_comment_create_dedupes_self_and_prioritizes_mentions_atomically() -> None:
    actor, alice, bob = uuid4(), uuid4(), uuid4()
    access = SessionAccess(uuid4(), actor, (actor, alice, bob))
    repository = CommentsRepositoryStub(access)
    activities = ActivitiesSpy()
    service = CommentsService(repository, activities)  # type: ignore[arg-type]
    result = service.create(
        ScriptedCursor([{"id": uuid4(), "version": 1}]),
        session_id=uuid4(),
        author_id=actor,
        client_request_id=uuid4(),
        body="hello",
        anchor_kind=None,
        anchor_id=None,
        mentioned_user_ids=(alice, alice, actor),
    )  # type: ignore[arg-type]
    assert result.idempotent is False and repository.inserted == [(alice,)]
    effects = activities.calls[0]["notification_effects"]
    assert [(effect.kind, effect.recipient_ids) for effect in effects] == [
        ("mention", (alice,)),
        ("comment", (bob,)),
    ]


def test_comment_concurrent_create_recovers_canonical_or_conflicts() -> None:
    actor = uuid4()
    access = SessionAccess(uuid4(), actor, (actor,))
    repository = CommentsRepositoryStub(access)
    service = CommentsService(repository, ActivitiesSpy())  # type: ignore[arg-type]
    client_id, canonical_id = uuid4(), uuid4()
    import app.comments_service as module

    fingerprint = module._fingerprint("hello", None, None, ())
    session_id = uuid4()
    replay = service.create(
        ScriptedCursor(
            [
                None,
                {
                    "id": canonical_id,
                    "session_id": session_id,
                    "version": 1,
                    "request_fingerprint": fingerprint,
                },
            ]
        ),
        session_id=session_id,
        author_id=actor,
        client_request_id=client_id,
        body="hello",
        anchor_kind=None,
        anchor_id=None,
        mentioned_user_ids=(),
    )  # type: ignore[arg-type]
    assert replay == module.CommentMutation(canonical_id, 1, True)
    with pytest.raises(CommentReplayConflictError):
        service.create(
            ScriptedCursor(
                [
                    None,
                    {
                        "id": canonical_id,
                        "session_id": session_id,
                        "version": 1,
                        "request_fingerprint": "0" * 64,
                    },
                ]
            ),
            session_id=uuid4(),
            author_id=actor,
            client_request_id=client_id,
            body="hello",
            anchor_kind=None,
            anchor_id=None,
            mentioned_user_ids=(),
        )  # type: ignore[arg-type]
    with pytest.raises(CommentReplayConflictError):
        service.create(
            ScriptedCursor(
                [
                    None,
                    {
                        "id": canonical_id,
                        "session_id": session_id,
                        "version": 1,
                        "request_fingerprint": fingerprint,
                    },
                ]
            ),
            session_id=uuid4(),
            author_id=actor,
            client_request_id=client_id,
            body="hello",
            anchor_kind=None,
            anchor_id=None,
            mentioned_user_ids=(),
        )  # type: ignore[arg-type]


def test_comment_update_noop_and_new_mentions_only() -> None:
    actor, old, new = uuid4(), uuid4(), uuid4()
    session_id, comment_id = uuid4(), uuid4()
    access = SessionAccess(uuid4(), actor, (actor, old, new))
    activities = ActivitiesSpy()
    service = CommentsService(CommentsRepositoryStub(access), activities)  # type: ignore[arg-type]
    current = {
        "id": comment_id,
        "author_id": actor,
        "version": 1,
        "body": "same",
        "anchor_kind": None,
        "anchor_id": None,
        "deleted_at": None,
    }
    no_op = service.update(
        ScriptedCursor([current, [{"user_id": old}]]),
        session_id=session_id,
        actor_id=actor,
        comment_id=comment_id,
        expected_version=1,
        body="same",
        anchor_kind=None,
        anchor_id=None,
        mentioned_user_ids=(old,),
    )  # type: ignore[arg-type]
    assert no_op.idempotent is True and activities.calls == []
    updated = service.update(
        ScriptedCursor([current, [{"user_id": old}], {"version": 2}]),
        session_id=session_id,
        actor_id=actor,
        comment_id=comment_id,
        expected_version=1,
        body="changed",
        anchor_kind=None,
        anchor_id=None,
        mentioned_user_ids=(old, new),
    )  # type: ignore[arg-type]
    effects = activities.calls[0]["notification_effects"]
    assert (
        updated.version == 2
        and len(effects) == 1
        and effects[0].recipient_ids == (new,)
    )


def test_room_owner_can_tombstone_another_authors_comment() -> None:
    author, owner = uuid4(), uuid4()
    access = SessionAccess(uuid4(), owner, (author, owner))
    activities = ActivitiesSpy()
    service = CommentsService(CommentsRepositoryStub(access), activities)  # type: ignore[arg-type]
    result = service.delete(
        ScriptedCursor(
            [{"author_id": author, "version": 3, "deleted_at": None}, {"version": 4}]
        ),
        session_id=uuid4(),
        actor_id=owner,
        comment_id=uuid4(),
        expected_version=3,
    )  # type: ignore[arg-type]
    assert result.version == 4 and len(activities.calls) == 1


def test_comment_bounds_and_mention_cap_are_enforced_after_dedupe() -> None:
    actor = uuid4()
    members = tuple(uuid4() for _ in range(21))
    service = CommentsService(
        CommentsRepositoryStub(SessionAccess(uuid4(), actor, (actor, *members))),
        ActivitiesSpy(),
    )  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="body"):
        service.create(
            ScriptedCursor(),
            session_id=uuid4(),
            author_id=actor,
            client_request_id=uuid4(),
            body="x" * 5001,
            anchor_kind=None,
            anchor_id=None,
            mentioned_user_ids=(),
        )  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="20"):
        service.create(
            ScriptedCursor(),
            session_id=uuid4(),
            author_id=actor,
            client_request_id=uuid4(),
            body="ok",
            anchor_kind=None,
            anchor_id=None,
            mentioned_user_ids=members,
        )  # type: ignore[arg-type]


def test_notification_catalog_renders_only_approved_same_origin_routes() -> None:
    room_id, session_id, comment_id = uuid4(), uuid4(), uuid4()
    assert (
        notification_href(
            action_kind="respond_friend_request",
            resource_type="friend_request",
            resource_id=uuid4(),
        )
        == "/friends"
    )
    assert (
        notification_href(
            action_kind="open_room", resource_type="room", resource_id=room_id
        )
        == f"/projects/{room_id}"
    )
    assert (
        notification_href(
            action_kind="open_session", resource_type="session", resource_id=session_id
        )
        == f"/projects/{session_id}"
    )
    assert (
        notification_href(
            action_kind="open_comment",
            resource_type="comment",
            resource_id=comment_id,
            session_id=session_id,
        )
        == f"/projects/{session_id}/editor?comment={comment_id}"
    )
    with pytest.raises(ValueError):
        notification_href(
            action_kind="open_room", resource_type="comment", resource_id=comment_id
        )


def test_activity_observability_counts_dedupe_and_failure_without_identifiers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    before = activity_observability_snapshot()
    service = ActivityService(
        ActivityRepositoryStub(None), NotificationRepositoryStub()
    )  # type: ignore[arg-type]
    secret_event_key = "comment:private-user-id:secret-token"
    body_marker = "BODY-MARKER-7bc0c719"
    email_marker = "EMAIL-MARKER-a3736257"
    provider_marker = "PROVIDER-MARKER-572e356b"
    raw_marker = "RAW-MARKER-b924697f"
    private_markers = (body_marker, email_marker, provider_marker, raw_marker)
    with caplog.at_level(logging.INFO, logger="app.activity_service"):
        result = service.record(
            ScriptedCursor(),
            event_key=secret_event_key,
            event_type="comment.created",
            actor_id=uuid4(),
            scope_type="session",
            room_id=uuid4(),
            session_id=uuid4(),
            entity_type="comment",
            entity_id=uuid4(),
        )  # type: ignore[arg-type]
        for metadata in (
            {"email": email_marker},
            {"provider_payload": provider_marker},
            {"comment_body": body_marker},
            {"source_text": raw_marker},
        ):
            with pytest.raises(ValueError, match="forbidden sensitive metadata"):
                service.record(
                    ScriptedCursor(),
                    event_key=secret_event_key,
                    event_type="comment.created",
                    actor_id=uuid4(),
                    scope_type="session",
                    room_id=uuid4(),
                    session_id=uuid4(),
                    entity_type="comment",
                    entity_id=uuid4(),
                    metadata=metadata,
                )  # type: ignore[arg-type]
        recorded_activity = AppendedActivity(
            uuid4(), secret_event_key, 1, datetime.now(UTC)
        )
        actor_id, room_id, session_id = uuid4(), uuid4(), uuid4()
        recipient_one, recipient_two = uuid4(), uuid4()
        recorded = ActivityService(
            ActivityRepositoryStub(recorded_activity),
            NotificationRepositoryStub(
                (1, 1),
                (
                    RecipientPreference(
                        recipient_one, frozenset({"in_app", "email_intent"})
                    ),
                    RecipientPreference(recipient_two, frozenset({"in_app"})),
                ),
            ),
        ).record(
            ScriptedCursor(),
            event_key=secret_event_key,
            event_type="session.ready",
            actor_id=actor_id,
            scope_type="session",
            room_id=room_id,
            session_id=session_id,
            entity_type="comment",
            entity_id=uuid4(),
            notification_effects=(
                NotificationEffect(
                    (recipient_one, recipient_two),
                    "analysis_completed",
                    "session",
                    session_id,
                    "open_session",
                    "title",
                    body_marker,
                    "comment.created",
                    {},
                ),
            ),
        )  # type: ignore[arg-type]
    after = activity_observability_snapshot()
    assert result.activity is None
    assert recorded.activity == recorded_activity
    assert (recorded.notifications_inserted, recorded.outbox_inserted) == (1, 1)
    assert after["attempted"] - before.get("attempted", 0) == 6
    assert after["deduplicated"] - before.get("deduplicated", 0) == 1
    assert after["failed"] - before.get("failed", 0) == 4
    assert after["recorded"] - before.get("recorded", 0) == 1
    assert after["audit_append_success"] - before.get("audit_append_success", 0) == 1
    assert after["audit_append_failure"] - before.get("audit_append_failure", 0) == 4
    assert (
        after["notifications_inserted"] - before.get("notifications_inserted", 0) == 1
    )
    assert after["notification_created"] - before.get("notification_created", 0) == 1
    assert (
        after["notification_deduplicated"] - before.get("notification_deduplicated", 0)
        == 1
    )
    assert after["outbox_inserted"] - before.get("outbox_inserted", 0) == 1
    assert after["outbox_queued"] - before.get("outbox_queued", 0) == 1
    assert (
        after["generation_ready_notification_latency_samples"]
        - before.get("generation_ready_notification_latency_samples", 0)
        == 1
    )
    assert {record.activity_outcome for record in caplog.records} == {
        "deduplicated",
        "failed",
        "recorded",
    }
    recorded_log = next(
        record for record in caplog.records if record.activity_outcome == "recorded"
    )
    assert len(recorded_log.correlation_id) == 32
    assert recorded_log.activity_actor_id == str(actor_id)
    assert recorded_log.activity_room_id == str(room_id)
    assert recorded_log.activity_session_id == str(session_id)
    assert recorded_log.activity_recipient_count == 2
    assert recorded_log.activity_channel_count == 3
    assert recorded_log.activity_notifications_deduplicated == 1
    assert recorded_log.activity_error_code is None
    assert recorded_log.activity_duration_ms >= 0
    assert recorded_log.activity_commit_state == "caller_owned_pending"
    failed_log = next(
        record for record in caplog.records if record.activity_outcome == "failed"
    )
    assert failed_log.activity_error_code == "invalid_input"
    assert failed_log.activity_commit_state == "caller_owned_pending"
    rendered = caplog.text
    assert secret_event_key not in rendered
    assert "private-user-id" not in rendered
    for marker in private_markers:
        assert marker not in rendered
        assert all(marker not in repr(record.__dict__) for record in caplog.records)
    assert all(
        "delivery" not in key.lower() and "delivered" not in key.lower()
        for record in caplog.records
        for key in record.__dict__
    )
    assert all(
        "delivery" not in key.lower() and "delivered" not in key.lower()
        for key in after
    )
    assert all(
        "committed" not in repr(record.__dict__).lower() for record in caplog.records
    )
    assert "committed=true" not in rendered.lower()


def test_activity_list_observes_existing_authorization_boundary_without_disclosure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class DeniedRepository(ActivityRepositoryStub):
        def list_authorized(self, cursor: object, **kwargs: object) -> object:
            raise PermissionError("private resource details must not be logged")

    before = activity_observability_snapshot()
    requester_id, session_id = uuid4(), uuid4()
    service = ActivityService(DeniedRepository(None), NotificationRepositoryStub())  # type: ignore[arg-type]
    with caplog.at_level(logging.INFO, logger="app.activity_service"):
        with pytest.raises(PermissionError):
            service.list(
                ScriptedCursor(),
                requester_id=requester_id,
                scope="session",
                scope_id=session_id,
                page_cursor=None,
            )  # type: ignore[arg-type]
    after = activity_observability_snapshot()
    assert after["unauthorized_access"] - before.get("unauthorized_access", 0) == 1
    record = caplog.records[-1]
    assert record.activity_outcome == "unauthorized"
    assert record.activity_error_code == "authorization_denied"
    assert record.activity_actor_id == str(requester_id)
    assert record.activity_session_id == str(session_id)
    assert record.activity_commit_state == "not_applicable"
    assert "private resource details" not in caplog.text


def test_cursor_codecs_round_trip_and_reject_tampering() -> None:
    event_id = uuid4()
    assert decode_event_cursor(encode_event_cursor(event_id)) == event_id
    now = datetime.now(UTC)
    assert decode_time_cursor(encode_time_cursor(now, event_id)) == (now, event_id)
    with pytest.raises(InvalidCursorError):
        decode_event_cursor("not-a-valid-cursor")


def test_audit_cursor_anchor_is_authorized_before_sequence_resolution() -> None:
    requester, hidden = uuid4(), uuid4()
    cursor = ScriptedCursor([None])
    with pytest.raises(PermissionError, match="cursor"):
        ActivityRepository().list_authorized(
            cursor,
            requester_id=requester,
            scope="personal",
            scope_id=None,
            page_cursor=encode_event_cursor(hidden),
            limit=10,
        )  # type: ignore[arg-type]
    assert "ledger_sequence" in cursor.statements[0][0]


@pytest.mark.parametrize("scope", ["room", "session"])
def test_room_and_session_audit_anchor_and_page_queries_recheck_live_membership(
    scope: str,
) -> None:
    requester, scope_id, anchor_id, event_id = uuid4(), uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    cursor = ScriptedCursor(
        [
            {"authorized": 1},
            {"ledger_sequence": 9},
            [{"id": event_id, "ledger_sequence": 8, "created_at": now}],
            {"coverage_started_at": now},
        ]
    )
    ActivityRepository().list_authorized(
        cursor,
        requester_id=requester,
        scope=scope,  # type: ignore[arg-type]
        scope_id=scope_id,
        page_cursor=encode_event_cursor(anchor_id),
        limit=10,
    )
    anchor_sql = cursor.statements[1][0]
    page_sql = cursor.statements[2][0]
    assert "room_memberships" in anchor_sql and "left_at IS NULL" in anchor_sql
    assert "room_memberships" in page_sql and "left_at IS NULL" in page_sql
    if scope == "session":
        assert "s.room_id=e.room_id" in anchor_sql and "s.room_id=e.room_id" in page_sql


def test_notification_and_outbox_foreign_cursors_are_rejected_before_page_query() -> (
    None
):
    now, foreign_id = datetime.now(UTC), uuid4()
    encoded = encode_time_cursor(now, foreign_id)
    with pytest.raises(PermissionError, match="notification cursor"):
        NotificationRepository().list_notifications(
            ScriptedCursor([None]), recipient_id=uuid4(), page_cursor=encoded, limit=10
        )  # type: ignore[arg-type]
    with pytest.raises(PermissionError, match="outbox cursor"):
        NotificationRepository().list_outbox(
            ScriptedCursor([None]), recipient_id=uuid4(), page_cursor=encoded, limit=10
        )  # type: ignore[arg-type]


def test_comments_list_is_membership_first_and_descending() -> None:
    requester, room_id, owner, session_id = uuid4(), uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    rows = [{"id": uuid4(), "created_at": now}, {"id": uuid4(), "created_at": now}]
    cursor = ScriptedCursor(
        [
            {"room_id": room_id, "owner_id": owner},
            [{"user_id": requester}],
            rows,
        ]
    )
    page = CommentsRepository().list(
        cursor, session_id=session_id, requester_id=requester, page_cursor=None, limit=1
    )  # type: ignore[arg-type]
    assert len(page.items) == 1 and page.next_cursor is not None
    assert "room_memberships" in cursor.statements[0][0]
    assert "ORDER BY c.created_at DESC,c.id DESC" in cursor.statements[-1][0]
