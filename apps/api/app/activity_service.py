"""Transactional activity append and local materialization orchestration."""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from threading import Lock
from typing import Literal
from typing import Any
from uuid import UUID, uuid4

import psycopg

from app.activity_policy import SUPPORTED_AUDIT_EVENT_TYPES, safe_audit_metadata
from app.activity_repository import (
    ActivityPage,
    ActivityRepository,
    ActivityScope,
    AppendedActivity,
)
from app.notification_repository import NotificationRepository
from app.notification_service import validate_notification_catalog


_LOGGER = logging.getLogger(__name__)
_OBSERVABILITY_LOCK = Lock()
_OBSERVABILITY_COUNTERS: Counter[str] = Counter()


def activity_observability_snapshot() -> dict[str, int]:
    """Return process-local seam outcomes, never durable commit truth.

    The caller owns the database transaction. Only the committed append-only
    ledger can establish durable success after this service returns.
    """

    with _OBSERVABILITY_LOCK:
        return dict(_OBSERVABILITY_COUNTERS)


def _observe_activity(
    *,
    outcome: Literal["recorded", "deduplicated", "failed"],
    event_type: str,
    scope_type: ActivityScope,
    correlation_id: str,
    actor_id: UUID | None,
    audience_user_id: UUID | None,
    room_id: UUID | None,
    session_id: UUID | None,
    duration_ms: int,
    notification_effect_count: int,
    recipient_count: int = 0,
    channel_count: int = 0,
    notifications_inserted: int = 0,
    notifications_deduplicated: int = 0,
    outbox_inserted: int = 0,
    outbox_deduplicated: int = 0,
    error_code: str | None = None,
) -> None:
    safe_event_type = (
        event_type if event_type in SUPPORTED_AUDIT_EVENT_TYPES else "unsupported"
    )
    with _OBSERVABILITY_LOCK:
        _OBSERVABILITY_COUNTERS["attempted"] += 1
        _OBSERVABILITY_COUNTERS[outcome] += 1
        _OBSERVABILITY_COUNTERS[f"audit_append_{outcome}"] += 1
        if outcome == "recorded":
            _OBSERVABILITY_COUNTERS["audit_append_success"] += 1
        elif outcome == "failed":
            _OBSERVABILITY_COUNTERS["audit_append_failure"] += 1
        _OBSERVABILITY_COUNTERS["notifications_inserted"] += notifications_inserted
        _OBSERVABILITY_COUNTERS["notification_created"] += notifications_inserted
        _OBSERVABILITY_COUNTERS["notification_deduplicated"] += (
            notifications_deduplicated
        )
        _OBSERVABILITY_COUNTERS["outbox_inserted"] += outbox_inserted
        _OBSERVABILITY_COUNTERS["outbox_queued"] += outbox_inserted
        _OBSERVABILITY_COUNTERS["outbox_deduplicated"] += outbox_deduplicated
        if safe_event_type == "session.ready" and outcome == "recorded":
            _OBSERVABILITY_COUNTERS[
                "generation_ready_notification_latency_samples"
            ] += 1
            _OBSERVABILITY_COUNTERS[
                "generation_ready_notification_latency_ms_total"
            ] += duration_ms
    _LOGGER.info(
        "activity outcome=%s event_type=%s duration_ms=%d error_code=%s",
        outcome,
        safe_event_type,
        duration_ms,
        error_code,
        extra={
            "correlation_id": correlation_id,
            "activity_outcome": outcome,
            "activity_event_type": safe_event_type,
            "activity_scope_type": scope_type,
            "activity_actor_id": str(actor_id) if actor_id is not None else None,
            "activity_audience_user_id": str(audience_user_id)
            if audience_user_id is not None
            else None,
            "activity_room_id": str(room_id) if room_id is not None else None,
            "activity_session_id": str(session_id) if session_id is not None else None,
            "activity_recipient_count": recipient_count,
            "activity_channel_count": channel_count,
            "activity_notification_effect_count": notification_effect_count,
            "activity_notifications_inserted": notifications_inserted,
            "activity_notifications_deduplicated": notifications_deduplicated,
            "activity_outbox_inserted": outbox_inserted,
            "activity_outbox_deduplicated": outbox_deduplicated,
            "activity_duration_ms": duration_ms,
            "activity_error_code": error_code,
            "activity_commit_state": "caller_owned_pending",
        },
    )


def _duration_ms(started_ns: int) -> int:
    return max(0, (time.monotonic_ns() - started_ns) // 1_000_000)


def _error_code(error: Exception) -> str:
    """Classify failures without logging exception text or payload-bearing values."""

    if isinstance(error, PermissionError):
        return "authorization_denied"
    if isinstance(error, ValueError):
        return "invalid_input"
    if isinstance(error, psycopg.Error):
        return "persistence_error"
    if isinstance(error, RuntimeError):
        return "invariant_failure"
    return "internal_error"


def _observe_unauthorized_list(
    *,
    requester_id: UUID,
    scope: str,
    scope_id: UUID | None,
    correlation_id: str,
    duration_ms: int,
) -> None:
    with _OBSERVABILITY_LOCK:
        _OBSERVABILITY_COUNTERS["unauthorized_access"] += 1
    _LOGGER.info(
        "activity outcome=unauthorized event_type=audit.read duration_ms=%d error_code=authorization_denied",
        duration_ms,
        extra={
            "correlation_id": correlation_id,
            "activity_outcome": "unauthorized",
            "activity_event_type": "audit.read",
            "activity_scope_type": scope,
            "activity_actor_id": str(requester_id),
            "activity_audience_user_id": None,
            "activity_room_id": str(scope_id)
            if scope == "room" and scope_id is not None
            else None,
            "activity_session_id": str(scope_id)
            if scope == "session" and scope_id is not None
            else None,
            "activity_recipient_count": 0,
            "activity_channel_count": 0,
            "activity_notification_effect_count": 0,
            "activity_notifications_inserted": 0,
            "activity_notifications_deduplicated": 0,
            "activity_outbox_inserted": 0,
            "activity_outbox_deduplicated": 0,
            "activity_duration_ms": duration_ms,
            "activity_error_code": "authorization_denied",
            "activity_commit_state": "not_applicable",
        },
    )


@dataclass(frozen=True, slots=True)
class NotificationEffect:
    recipient_ids: tuple[UUID, ...]
    kind: str
    resource_type: str
    resource_id: UUID
    action_kind: str
    title: str
    body: str
    template_key: str
    template_data: dict[str, Any]
    dedupe_key: str | None = None


@dataclass(frozen=True, slots=True)
class RecordedActivity:
    activity: AppendedActivity | None
    notifications_inserted: int
    outbox_inserted: int


class ActivityService:
    def __init__(
        self,
        activity_repository: ActivityRepository | None = None,
        notification_repository: NotificationRepository | None = None,
    ) -> None:
        self.activities = activity_repository or ActivityRepository()
        self.notifications = notification_repository or NotificationRepository()

    def append(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        event_key: str,
        event_type: str,
        actor_id: UUID | None,
        scope_type: ActivityScope,
        audience_user_id: UUID | None = None,
        room_id: UUID | None = None,
        session_id: UUID | None = None,
        entity_type: str,
        entity_id: UUID,
        metadata: dict[str, Any] | None = None,
    ) -> AppendedActivity | None:
        started_ns = time.monotonic_ns()
        correlation_id = uuid4().hex
        try:
            activity = self._append(
                cursor,
                event_key=event_key,
                event_type=event_type,
                actor_id=actor_id,
                scope_type=scope_type,
                audience_user_id=audience_user_id,
                room_id=room_id,
                session_id=session_id,
                entity_type=entity_type,
                entity_id=entity_id,
                metadata=metadata,
            )
        except Exception as error:
            _observe_activity(
                outcome="failed",
                event_type=event_type,
                scope_type=scope_type,
                correlation_id=correlation_id,
                actor_id=actor_id,
                audience_user_id=audience_user_id,
                room_id=room_id,
                session_id=session_id,
                duration_ms=_duration_ms(started_ns),
                notification_effect_count=0,
                error_code=_error_code(error),
            )
            raise
        _observe_activity(
            outcome="recorded" if activity is not None else "deduplicated",
            event_type=event_type,
            scope_type=scope_type,
            correlation_id=correlation_id,
            actor_id=actor_id,
            audience_user_id=audience_user_id,
            room_id=room_id,
            session_id=session_id,
            duration_ms=_duration_ms(started_ns),
            notification_effect_count=0,
        )
        return activity

    def _append(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        event_key: str,
        event_type: str,
        actor_id: UUID | None,
        scope_type: ActivityScope,
        audience_user_id: UUID | None,
        room_id: UUID | None,
        session_id: UUID | None,
        entity_type: str,
        entity_id: UUID,
        metadata: dict[str, Any] | None,
    ) -> AppendedActivity | None:
        if event_type not in SUPPORTED_AUDIT_EVENT_TYPES:
            raise ValueError("unsupported audit event type")
        return self.activities.append(
            cursor,
            event_key=event_key,
            event_type=event_type,
            actor_id=actor_id,
            scope_type=scope_type,
            audience_user_id=audience_user_id,
            room_id=room_id,
            session_id=session_id,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata=safe_audit_metadata(metadata or {}),
        )

    def record(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        event_key: str,
        event_type: str,
        actor_id: UUID | None,
        scope_type: ActivityScope,
        entity_type: str,
        entity_id: UUID,
        audience_user_id: UUID | None = None,
        room_id: UUID | None = None,
        session_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        notification_effects: Sequence[NotificationEffect] = (),
    ) -> RecordedActivity:
        """Stage audit and effects in the caller-owned transaction.

        Observability reports this seam outcome as ``caller_owned_pending``;
        it does not claim the caller subsequently committed the transaction.
        """
        started_ns = time.monotonic_ns()
        correlation_id = uuid4().hex
        recipient_ids: set[UUID] = set()
        channel_count = 0
        planned_notifications = 0
        planned_outbox = 0
        try:
            activity = self._append(
                cursor,
                event_key=event_key,
                event_type=event_type,
                actor_id=actor_id,
                scope_type=scope_type,
                audience_user_id=audience_user_id,
                room_id=room_id,
                session_id=session_id,
                entity_type=entity_type,
                entity_id=entity_id,
                metadata=metadata,
            )
            if activity is None:
                _observe_activity(
                    outcome="deduplicated",
                    event_type=event_type,
                    scope_type=scope_type,
                    correlation_id=correlation_id,
                    actor_id=actor_id,
                    audience_user_id=audience_user_id,
                    room_id=room_id,
                    session_id=session_id,
                    duration_ms=_duration_ms(started_ns),
                    notification_effect_count=len(notification_effects),
                )
                return RecordedActivity(None, 0, 0)
            notifications_inserted = 0
            outbox_inserted = 0
            for effect in notification_effects:
                validate_notification_catalog(
                    action_kind=effect.action_kind, resource_type=effect.resource_type
                )
                if len(effect.title) > 120 or len(effect.body) > 240:
                    raise ValueError("notification text exceeds approved bounds")
                safe_template = safe_audit_metadata(effect.template_data)
                if (
                    len(
                        json.dumps(
                            safe_template, ensure_ascii=False, separators=(",", ":")
                        ).encode()
                    )
                    > 2048
                ):
                    raise ValueError("outbox template data exceeds 2 KiB")
                recipients = self.notifications.snapshot_preferences(
                    cursor, recipient_ids=effect.recipient_ids, kind=effect.kind
                )
                recipient_ids.update(recipient.user_id for recipient in recipients)
                channel_count += sum(
                    len(recipient.channels) for recipient in recipients
                )
                planned_notifications += sum(
                    "in_app" in recipient.channels for recipient in recipients
                )
                planned_outbox += sum(
                    "email_intent" in recipient.channels for recipient in recipients
                )
                in_app, outbox = self.notifications.materialize(
                    cursor,
                    recipients=recipients,
                    kind=effect.kind,
                    actor_id=actor_id,
                    resource_type=effect.resource_type,
                    resource_id=effect.resource_id,
                    action_kind=effect.action_kind,
                    title=effect.title,
                    body=effect.body,
                    base_dedupe_key=effect.dedupe_key or event_key,
                    template_key=effect.template_key,
                    template_data=safe_template,
                )
                notifications_inserted += in_app
                outbox_inserted += outbox
        except Exception as error:
            _observe_activity(
                outcome="failed",
                event_type=event_type,
                scope_type=scope_type,
                correlation_id=correlation_id,
                actor_id=actor_id,
                audience_user_id=audience_user_id,
                room_id=room_id,
                session_id=session_id,
                duration_ms=_duration_ms(started_ns),
                notification_effect_count=len(notification_effects),
                recipient_count=len(recipient_ids),
                channel_count=channel_count,
                error_code=_error_code(error),
            )
            raise
        _observe_activity(
            outcome="recorded",
            event_type=event_type,
            scope_type=scope_type,
            correlation_id=correlation_id,
            actor_id=actor_id,
            audience_user_id=audience_user_id,
            room_id=room_id,
            session_id=session_id,
            duration_ms=_duration_ms(started_ns),
            notification_effect_count=len(notification_effects),
            recipient_count=len(recipient_ids),
            channel_count=channel_count,
            notifications_inserted=notifications_inserted,
            notifications_deduplicated=max(
                0, planned_notifications - notifications_inserted
            ),
            outbox_inserted=outbox_inserted,
            outbox_deduplicated=max(0, planned_outbox - outbox_inserted),
        )
        return RecordedActivity(activity, notifications_inserted, outbox_inserted)

    def list(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        requester_id: UUID,
        scope: Literal["all", "personal", "room", "session"],
        scope_id: UUID | None,
        page_cursor: str | None,
        limit: int = 50,
    ) -> ActivityPage:
        started_ns = time.monotonic_ns()
        correlation_id = uuid4().hex
        try:
            return self.activities.list_authorized(
                cursor,
                requester_id=requester_id,
                scope=scope,
                scope_id=scope_id,
                page_cursor=page_cursor,
                limit=limit,
            )
        except PermissionError:
            _observe_unauthorized_list(
                requester_id=requester_id,
                scope=scope,
                scope_id=scope_id,
                correlation_id=correlation_id,
                duration_ms=_duration_ms(started_ns),
            )
            raise
