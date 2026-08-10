from __future__ import annotations

import hashlib
import logging
from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.automatic_report_suggestions import (
    AutomaticSuggestionExecution,
    AutomaticSuggestionProposal,
    FencedAutomaticSuggestionWorker,
)
from app.activity_repository import AppendedActivity
from app.activity_service import ActivityService, activity_observability_snapshot
from app.domain import JobState, StaleLeaseError, TalkSessionState
from app.file_extraction_worker import (
    FileExtractionWorker,
    _persist_failure,
    _persist_success,
    _reconcile_retryable_extractions,
)
from app.generation_repository import GenerationRepository
from app.generation_worker import FencedGenerationWorker
from app.notification_repository import NotificationRepository, RecipientPreference
from app.queue_repository import ClaimedJob, PostgresJobQueue, canonical_json_bytes


class _GenerationCursor:
    def __init__(
        self,
        *,
        current_state: str = "processing",
        generation_epoch: int = 7,
        run_states: tuple[str, str] = ("succeeded", "succeeded"),
    ) -> None:
        self.session_id, self.room_id = uuid4(), uuid4()
        self.member_ids = (uuid4(), uuid4())
        self.current_state = current_state
        self.generation_epoch = generation_epoch
        self.run_states = run_states
        self.rowcount = 0
        self._rows: list[dict[str, Any]] = []

    def execute(self, query: str, parameters: object = None) -> None:
        normalized = " ".join(query.split())
        self.rowcount = 0
        if "FROM generation_snapshots AS snapshot" in normalized:
            self._rows = [
                {
                    "session_id": self.session_id,
                    "state": self.current_state,
                    "pipeline_version": "pipeline-v1",
                    "room_id": self.room_id,
                    "generation_epoch": self.generation_epoch,
                    "state_version": 12,
                }
            ]
        elif "FROM generation_runs" in normalized:
            self._rows = [
                {
                    "kind": "research",
                    "state": self.run_states[0],
                    "error_code": (
                        "failed" if self.run_states[0].startswith("failed") else None
                    ),
                },
                {
                    "kind": "summary",
                    "state": self.run_states[1],
                    "error_code": (
                        "failed" if self.run_states[1].startswith("failed") else None
                    ),
                },
            ]
        elif normalized.startswith("UPDATE talk_sessions"):
            self.rowcount = 1
            self._rows = []
        elif "FROM room_memberships" in normalized:
            self._rows = [{"user_id": user_id} for user_id in self.member_ids]
        else:
            self._rows = []

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        rows, self._rows = self._rows, []
        return rows


class _Notifications:
    def __init__(self) -> None:
        self.materialized: list[dict[str, Any]] = []

    def snapshot_preferences(
        self, _cursor: object, *, recipient_ids: tuple[UUID, ...], kind: str
    ) -> tuple[object, ...]:
        assert kind == "analysis_completed"
        return tuple(recipient_ids)

    def materialize(self, _cursor: object, **kwargs: Any) -> tuple[int, int]:
        self.materialized.append(kwargs)
        return 2, 0


class _Activities:
    def __init__(self) -> None:
        self.notifications = _Notifications()
        self.appended: list[dict[str, Any]] = []

    def append(self, _cursor: object, **kwargs: Any) -> object:
        self.appended.append(kwargs)
        return object()

    def record(self, cursor: object, **kwargs: Any) -> object:
        self.append(
            cursor,
            **{
                key: value
                for key, value in kwargs.items()
                if key != "notification_effects"
            },
        )
        for effect in kwargs.get("notification_effects", ()):
            recipients = self.notifications.snapshot_preferences(
                cursor, recipient_ids=effect.recipient_ids, kind=effect.kind
            )
            self.notifications.materialize(
                cursor,
                recipients=recipients,
                kind=effect.kind,
                actor_id=kwargs["actor_id"],
                resource_type=effect.resource_type,
                resource_id=effect.resource_id,
                action_kind=effect.action_kind,
                title=effect.title,
                body=effect.body,
                base_dedupe_key=effect.dedupe_key or kwargs["event_key"],
                template_key=effect.template_key,
                template_data=effect.template_data,
            )
        return object()


class _ObservedActivityRepository:
    def append(self, _cursor: object, **kwargs: Any) -> AppendedActivity:
        return AppendedActivity(uuid4(), kwargs["event_key"], 1, datetime.now(UTC))


class _ObservedNotifications:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.materialize_calls = 0

    def snapshot_preferences(
        self, _cursor: object, *, recipient_ids: tuple[UUID, ...], kind: str
    ) -> tuple[RecipientPreference, ...]:
        assert kind == "analysis_completed"
        return tuple(
            RecipientPreference(user_id, frozenset({"in_app", "email_intent"}))
            for user_id in recipient_ids
        )

    def materialize(self, _cursor: object, **kwargs: Any) -> tuple[int, int]:
        self.materialize_calls += 1
        if self.failure is not None:
            raise self.failure
        return 1, 1


def test_generation_first_ready_transition_audits_and_fans_out_once() -> None:
    cursor = _GenerationCursor()
    activities = _Activities()
    projection = GenerationRepository(activities).recompute_aggregate(  # type: ignore[arg-type]
        cursor,
        snapshot_id=uuid4(),  # type: ignore[arg-type]
    )

    assert projection.state is TalkSessionState.READY
    assert projection.transitioned_to_ready is True
    assert [event["event_type"] for event in activities.appended] == ["session.ready"]
    assert activities.appended[0]["event_key"].endswith("state-v13:ready")
    assert len(activities.notifications.materialized) == 1
    effect = activities.notifications.materialized[0]
    assert effect["base_dedupe_key"] == f"analysis:{cursor.session_id}:7"
    assert effect["actor_id"] is None


def test_generation_ready_observes_real_orchestration_after_materialization(
    caplog: pytest.LogCaptureFixture,
) -> None:
    before = activity_observability_snapshot()
    notifications = _ObservedNotifications()
    activities = ActivityService(_ObservedActivityRepository(), notifications)  # type: ignore[arg-type]
    cursor = _GenerationCursor()
    with caplog.at_level(logging.INFO, logger="app.activity_service"):
        projection = GenerationRepository(activities).recompute_aggregate(
            cursor, snapshot_id=uuid4()
        )  # type: ignore[arg-type]
    after = activity_observability_snapshot()
    assert projection.transitioned_to_ready is True
    assert notifications.materialize_calls == 1
    assert after["audit_append_success"] - before.get("audit_append_success", 0) == 1
    assert after["notification_created"] - before.get("notification_created", 0) == 1
    assert (
        after["notification_deduplicated"] - before.get("notification_deduplicated", 0)
        == 1
    )
    assert after["outbox_queued"] - before.get("outbox_queued", 0) == 1
    assert after["outbox_deduplicated"] - before.get("outbox_deduplicated", 0) == 1
    assert (
        after["generation_ready_notification_latency_samples"]
        - before.get("generation_ready_notification_latency_samples", 0)
        == 1
    )
    record = caplog.records[-1]
    assert record.activity_event_type == "session.ready"
    assert record.activity_recipient_count == 2
    assert record.activity_channel_count == 4
    assert record.activity_notifications_inserted == 1
    assert record.activity_notifications_deduplicated == 1
    assert record.activity_outbox_inserted == 1
    assert record.activity_outbox_deduplicated == 1
    assert record.activity_duration_ms >= 0
    assert "회의 요약과 리서치 결과" not in caplog.text
    assert all(
        "회의 요약과 리서치 결과" not in repr(item.__dict__) for item in caplog.records
    )


def test_generation_ready_materialization_failure_observes_failure_not_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    before = activity_observability_snapshot()
    notifications = _ObservedNotifications(
        failure=RuntimeError("PRIVATE-MATERIALIZATION-DETAIL")
    )
    activities = ActivityService(_ObservedActivityRepository(), notifications)  # type: ignore[arg-type]
    with caplog.at_level(logging.INFO, logger="app.activity_service"):
        with pytest.raises(RuntimeError, match="PRIVATE-MATERIALIZATION-DETAIL"):
            GenerationRepository(activities).recompute_aggregate(
                _GenerationCursor(), snapshot_id=uuid4()
            )  # type: ignore[arg-type]
    after = activity_observability_snapshot()
    assert after["audit_append_failure"] - before.get("audit_append_failure", 0) == 1
    assert (
        after.get("audit_append_success", 0) - before.get("audit_append_success", 0)
        == 0
    )
    assert (
        after.get("generation_ready_notification_latency_samples", 0)
        - before.get("generation_ready_notification_latency_samples", 0)
        == 0
    )
    assert caplog.records[-1].activity_outcome == "failed"
    assert caplog.records[-1].activity_error_code == "invariant_failure"
    assert "PRIVATE-MATERIALIZATION-DETAIL" not in caplog.text
    assert all(
        "PRIVATE-MATERIALIZATION-DETAIL" not in repr(item.__dict__)
        for item in caplog.records
    )


def test_generation_ready_reprojection_is_a_zero_effect_noop() -> None:
    activities = _Activities()
    projection = GenerationRepository(activities).recompute_aggregate(  # type: ignore[arg-type]
        _GenerationCursor(current_state="ready"),
        snapshot_id=uuid4(),  # type: ignore[arg-type]
    )
    assert projection.transitioned_to_ready is False
    assert activities.appended == []
    assert activities.notifications.materialized == []


def test_generation_needs_attention_is_audited_without_notification() -> None:
    activities = _Activities()
    projection = GenerationRepository(activities).recompute_aggregate(  # type: ignore[arg-type]
        _GenerationCursor(run_states=("failed_terminal", "succeeded")),
        snapshot_id=uuid4(),  # type: ignore[arg-type]
    )
    assert projection.state is TalkSessionState.NEEDS_ATTENTION
    assert [event["event_type"] for event in activities.appended] == [
        "session.needs_attention"
    ]
    assert activities.notifications.materialized == []


def test_generation_retry_epoch_uses_a_new_analysis_dedupe_identity() -> None:
    keys: list[str] = []
    for epoch in (7, 8):
        cursor = _GenerationCursor(generation_epoch=epoch)
        activities = _Activities()
        GenerationRepository(activities).recompute_aggregate(  # type: ignore[arg-type]
            cursor,
            snapshot_id=uuid4(),  # type: ignore[arg-type]
        )
        keys.append(activities.notifications.materialized[0]["base_dedupe_key"])
    assert keys[0].endswith(":7")
    assert keys[1].endswith(":8")
    assert keys[0] != keys[1]


def test_generation_final_notification_and_outbox_dedupe_keys_match_prd() -> None:
    recipient_id, session_id = uuid4(), uuid4()

    class Cursor:
        def __init__(self) -> None:
            self.rowcount = 1
            self.statements: list[tuple[str, tuple[object, ...]]] = []

        def execute(self, query: str, parameters: tuple[object, ...]) -> None:
            self.statements.append((query, parameters))
            self.rowcount = len(parameters[-1])  # type: ignore[arg-type]

    cursor = Cursor()
    NotificationRepository().materialize(  # type: ignore[arg-type]
        cursor,
        recipients=(
            RecipientPreference(recipient_id, frozenset({"in_app", "email_intent"})),
        ),
        kind="analysis_completed",
        actor_id=None,
        resource_type="session",
        resource_id=session_id,
        action_kind="open_session",
        title="done",
        body="done",
        base_dedupe_key=f"analysis:{session_id}:9",
        template_key="analysis_completed",
        template_data={"session_id": str(session_id), "generation_epoch": 9},
    )
    assert "batch.recipient_id::text || ':in_app'" in cursor.statements[0][0]
    assert cursor.statements[0][1][7] == f"analysis:{session_id}:9"
    assert cursor.statements[0][1][-1] == [recipient_id]
    assert "batch.recipient_id::text || ':email_intent'" in cursor.statements[1][0]
    assert cursor.statements[1][1][1] == f"analysis:{session_id}:9"
    assert cursor.statements[1][1][-1] == [recipient_id]


def test_generation_notification_failure_escapes_for_transaction_rollback() -> None:
    activities = _Activities()
    activities.notifications.materialize = lambda *_args, **_kwargs: (
        _ for _ in ()
    ).throw(  # type: ignore[method-assign]
        RuntimeError("notification insert failed")
    )
    with pytest.raises(RuntimeError, match="notification insert failed"):
        GenerationRepository(activities).recompute_aggregate(  # type: ignore[arg-type]
            _GenerationCursor(),
            snapshot_id=uuid4(),  # type: ignore[arg-type]
        )


def test_stale_generation_fence_never_invokes_domain_or_activity_effect() -> None:
    claimed = ClaimedJob(
        uuid4(), "logical", "summary", {}, "owner", 1, uuid4(), uuid4()
    )
    queue = SimpleNamespace(
        claim_next=lambda *_args, **_kwargs: claimed,
        complete_with_effects=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            StaleLeaseError("stale")
        ),
    )
    runner = SimpleNamespace(
        execute=lambda *_args: SimpleNamespace(
            target_state=JobState.SUCCEEDED,
            result={},
            error_code=None,
            fenced_effect=lambda _repository: (
                lambda _cursor: pytest.fail("stale fence invoked effect")
            ),
        )
    )
    worker = FencedGenerationWorker(
        connection_factory=lambda: nullcontext(SimpleNamespace()),
        runner=runner,
        queue=queue,  # type: ignore[arg-type]
    )
    assert worker.run_once(owner="worker").stale_completion is True


class _InsertCursor:
    def __init__(self, inserted: list[UUID | None]) -> None:
        self.inserted = inserted
        self.audit_parameters: list[tuple[object, ...]] = []

    def execute(self, query: str, parameters: tuple[object, ...]) -> None:
        if "INSERT INTO audit_events" in query:
            self.audit_parameters.append(parameters)

    def fetchone(self) -> dict[str, UUID] | None:
        value = self.inserted.pop(0)
        return None if value is None else {"id": value}


def test_automatic_suggestion_audits_only_rows_actually_inserted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inserted_id = uuid4()
    cursor = _InsertCursor([inserted_id, None, uuid4()])
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "app.automatic_report_suggestions.ActivityService",
        lambda: SimpleNamespace(
            append=lambda _cursor, **kwargs: captured.append(kwargs)
        ),
    )
    execution = AutomaticSuggestionExecution(
        snapshot_id=uuid4(),
        session_id=uuid4(),
        room_id=uuid4(),
        author_id=uuid4(),
        report_content_hash="a" * 64,
        proposals=tuple(
            AutomaticSuggestionProposal(str(index), "add", uuid4(), "text", "reason")
            for index in range(3)
        ),
    )
    result, effect = execution.fenced_completion()
    effect(cursor)  # type: ignore[arg-type]
    assert len(captured) == 2
    assert all(event["actor_id"] is None for event in captured)
    assert result["suggestion_count"] == 2


def test_automatic_stale_fence_writes_no_suggestion_or_audit() -> None:
    claimed = ClaimedJob(
        uuid4(), "logical", "report_suggestions", {}, "owner", 1, uuid4(), uuid4()
    )
    execution = AutomaticSuggestionExecution(
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        "a" * 64,
        (AutomaticSuggestionProposal("one", "add", uuid4(), "text", "reason"),),
    )
    queue = SimpleNamespace(
        claim_next=lambda *_args, **_kwargs: claimed,
        complete_with_effects=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            StaleLeaseError("stale")
        ),
    )
    worker = FencedAutomaticSuggestionWorker(
        connection_factory=lambda: nullcontext(SimpleNamespace()),
        runner=SimpleNamespace(execute=lambda *_args: execution),
        queue=queue,  # type: ignore[arg-type]
    )
    outcome = worker.run_once(owner="worker")
    assert outcome.stale_completion is True


def test_automatic_audit_failure_escapes_for_transaction_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.automatic_report_suggestions.ActivityService",
        lambda: SimpleNamespace(
            append=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("audit insert failed")
            )
        ),
    )
    execution = AutomaticSuggestionExecution(
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        "a" * 64,
        (AutomaticSuggestionProposal("one", "add", uuid4(), "text", "reason"),),
    )
    _, effect = execution.fenced_completion()
    with pytest.raises(RuntimeError, match="audit insert failed"):
        effect(_InsertCursor([uuid4()]))  # type: ignore[arg-type]


def test_terminal_extraction_audit_uses_attempt_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt_id, revision_id = uuid4(), uuid4()
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "app.file_extraction_worker.ActivityService",
        lambda: SimpleNamespace(
            append=lambda _cursor, **kwargs: captured.append(kwargs)
        ),
    )

    class Cursor:
        def execute(self, query: str, _parameters: object) -> None:
            self._terminal = query.lstrip().startswith("UPDATE source_revisions")

        def fetchone(self) -> dict[str, UUID] | None:
            return {"id": revision_id} if self._terminal else None

    claimed = SimpleNamespace(attempt_id=attempt_id, lease_generation=3)
    revision = {
        "id": revision_id,
        "parser": SimpleNamespace(name="parser", version="1"),
        "mime_type": "text/plain",
        "room_id": uuid4(),
        "session_id": uuid4(),
    }
    _persist_failure(Cursor(), claimed, revision, "typed_failure", terminal=True)  # type: ignore[arg-type]
    assert (
        captured[0]["event_key"]
        == f"revision:{revision_id}:attempt:{attempt_id}:failed"
    )
    assert captured[0]["actor_id"] is None


def test_successful_extraction_ready_audit_uses_attempt_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt_id, revision_id = uuid4(), uuid4()
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "app.file_extraction_worker.ActivityService",
        lambda: SimpleNamespace(
            append=lambda _cursor, **kwargs: captured.append(kwargs)
        ),
    )

    class Cursor:
        rowcount = 1

        def execute(self, _query: str, _parameters: object) -> None:
            self.rowcount = 1

    claimed = SimpleNamespace(attempt_id=attempt_id, lease_generation=1)
    revision = {
        "id": revision_id,
        "room_id": uuid4(),
        "session_id": uuid4(),
    }
    result = {
        "parser": {"name": "parser", "version": "1"},
        "config_profile_hash": "profile",
        "blocks": [],
    }
    _persist_success(Cursor(), claimed, revision, result)  # type: ignore[arg-type]
    assert (
        captured[0]["event_key"] == f"revision:{revision_id}:attempt:{attempt_id}:ready"
    )


def test_retryable_extraction_failure_writes_zero_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "app.file_extraction_worker.ActivityService",
        lambda: SimpleNamespace(
            append=lambda _cursor, **kwargs: captured.append(kwargs)
        ),
    )
    revision = {
        "id": uuid4(),
        "parser": SimpleNamespace(name="parser", version="1"),
        "mime_type": "text/plain",
        "room_id": uuid4(),
        "session_id": uuid4(),
    }
    _persist_failure(
        SimpleNamespace(execute=lambda *_args: None),
        SimpleNamespace(attempt_id=uuid4(), lease_generation=1),
        revision,
        "retryable_failure",
        terminal=False,  # type: ignore[arg-type]
    )
    assert captured == []


def test_stale_extraction_completion_never_invokes_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision_id = uuid4()
    claimed = ClaimedJob(
        uuid4(),
        "logical",
        "extraction",
        {
            "revision_id": str(revision_id),
            "media_type": "text/plain",
            "parser": {"name": "builtin-utf8-text", "version": "1.0.0"},
        },
        "owner",
        1,
        uuid4(),
        uuid4(),
    )
    monkeypatch.setattr(
        "app.file_extraction_worker._reconcile_retryable_extractions",
        lambda _connection: None,
    )
    monkeypatch.setattr(
        "app.file_extraction_worker._load_revision",
        lambda *_args: {
            "id": revision_id,
            "mime_type": "text/plain",
            "parser": SimpleNamespace(name="builtin-utf8-text", version="1.0.0"),
            "storage_key": "local",
            "byte_size": 5,
            "sha256": hashlib.sha256(b"hello").hexdigest(),
            "filename": "safe.txt",
            "room_id": uuid4(),
            "session_id": uuid4(),
        },
    )
    queue = SimpleNamespace(
        claim_next=lambda *_args, **_kwargs: claimed,
        complete_with_effects=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            StaleLeaseError("stale")
        ),
    )
    worker = FileExtractionWorker(
        connection_factory=lambda: nullcontext(SimpleNamespace()),
        blob_store=SimpleNamespace(read=lambda *_args, **_kwargs: b"hello"),
        sandbox_adapter=SimpleNamespace(),
        queue=queue,  # type: ignore[arg-type]
    )
    assert worker.run_once("worker") is None


def test_extraction_activity_failure_escapes_the_fenced_effect_for_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.file_extraction_worker.ActivityService",
        lambda: SimpleNamespace(
            append=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("audit insert failed")
            )
        ),
    )

    class Cursor:
        def execute(self, query: str, _parameters: object) -> None:
            self._terminal = query.lstrip().startswith("UPDATE source_revisions")

        def fetchone(self) -> dict[str, UUID] | None:
            return {"id": revision["id"]} if self._terminal else None

    revision = {
        "id": uuid4(),
        "parser": SimpleNamespace(name="parser", version="1"),
        "mime_type": "text/plain",
        "room_id": uuid4(),
        "session_id": uuid4(),
    }
    with pytest.raises(RuntimeError, match="audit insert failed"):
        _persist_failure(
            Cursor(),
            SimpleNamespace(attempt_id=uuid4(), lease_generation=3),
            revision,
            "typed_failure",
            terminal=True,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("repair_count", [0, 1, 2])
def test_extraction_reconciliation_audits_only_returned_repairs(
    monkeypatch: pytest.MonkeyPatch,
    repair_count: int,
) -> None:
    repairs = [(uuid4(), uuid4()) for _ in range(repair_count)]
    room_id, session_id = uuid4(), uuid4()
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "app.file_extraction_worker.ActivityService",
        lambda: SimpleNamespace(
            append=lambda _cursor, **kwargs: captured.append(kwargs)
        ),
    )

    class Cursor:
        def __init__(self) -> None:
            self.rows: list[dict[str, UUID]] = []

        def __enter__(self) -> "Cursor":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, query: str, _parameters: object) -> None:
            normalized = " ".join(query.split())
            if "WITH terminal_jobs" in normalized:
                self.rows = [
                    {"id": job_id, "revision_id": revision_id}
                    for job_id, revision_id in repairs
                ]
            elif "SELECT session_row.room_id" in normalized:
                self.rows = [{"room_id": room_id, "session_id": session_id}]
            else:
                self.rows = []

        def fetchall(self) -> list[dict[str, UUID]]:
            rows, self.rows = self.rows, []
            return rows

        def fetchone(self) -> dict[str, UUID] | None:
            return self.rows.pop(0) if self.rows else None

    cursor = Cursor()
    connection = SimpleNamespace(
        transaction=lambda: nullcontext(), cursor=lambda: cursor
    )
    _reconcile_retryable_extractions(connection)  # type: ignore[arg-type]
    assert [event["event_key"] for event in captured] == [
        f"revision:{revision_id}:reconcile:{job_id}:failed"
        for job_id, revision_id in repairs
    ]


def test_queue_hashes_deferred_result_after_fenced_effect_mutation() -> None:
    claimed = ClaimedJob(
        uuid4(), "logical", "report_suggestions", {}, "owner", 1, uuid4(), uuid4()
    )
    result: dict[str, object] = {"suggestion_count": 0}

    class Cursor:
        def __init__(self) -> None:
            self.rowcount = 1
            self.result_parameters: tuple[object, ...] | None = None

        def __enter__(self) -> "Cursor":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, query: str, parameters: tuple[object, ...]) -> None:
            self.rowcount = 1
            if "INSERT INTO job_results" in query:
                self.result_parameters = parameters

    cursor = Cursor()
    connection = SimpleNamespace(
        transaction=lambda: nullcontext(), cursor=lambda: cursor
    )
    PostgresJobQueue().complete_with_effects(  # type: ignore[arg-type]
        connection,
        claimed,
        target_state=JobState.SUCCEEDED,
        result=result,
        effect=lambda _cursor: result.update(suggestion_count=2),
    )
    assert cursor.result_parameters is not None
    persisted_json = cursor.result_parameters[2]
    assert persisted_json.obj == {"suggestion_count": 2}  # type: ignore[union-attr]
    assert (
        cursor.result_parameters[3]
        == hashlib.sha256(canonical_json_bytes({"suggestion_count": 2})).hexdigest()
    )
