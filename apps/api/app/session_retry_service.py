"""Host-only retry of failed canonical generation jobs on the same snapshot.

Retry never creates a replacement snapshot, generation run, or logical job.
It requeues only a retryable terminal pair while holding the session parent
lock, so duplicate browser clicks cannot fork the aggregate's provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.activity_policy import build_event_key
from app.activity_service import ActivityService

class SessionRetryError(ValueError):
    """Base class for retry-state failures."""


class SessionRetryAccessError(PermissionError):
    """A non-member cannot learn whether a session has retryable work."""


class SessionRetryHostRequiredError(PermissionError):
    """A current non-host member attempted to requeue generation work."""


class SessionRetryUnavailableError(SessionRetryError):
    """The session does not currently contain a retryable canonical failure."""


@dataclass(frozen=True, slots=True)
class RetrySessionView:
    snapshot_id: UUID
    state: Literal["processing", "needs_attention", "ready", "closed"]
    requeued_kinds: tuple[Literal["summary", "research"], ...]


class SessionRetryService:
    """Requeue only existing retryable generation jobs for one hosted session."""

    def __init__(self, activity_service: ActivityService | None = None) -> None:
        self._activities = activity_service or ActivityService()

    def retry(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
    ) -> RetrySessionView:
        """Return a stable processing response or atomically requeue failures."""

        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT session_row.id, session_row.host_id, session_row.state,
                           session_row.room_id, session_row.generation_epoch,
                           session_row.state_version, session_row.retry_ordinal
                    FROM talk_sessions AS session_row
                    JOIN room_memberships AS membership
                      ON membership.room_id = session_row.room_id
                     AND membership.user_id = %s
                     AND membership.left_at IS NULL
                    WHERE session_row.id = %s
                    FOR UPDATE OF session_row
                    """,
                    (actor_id, session_id),
                )
                session = cursor.fetchone()
                if session is None:
                    raise SessionRetryAccessError("session is unavailable")
                if session["host_id"] != actor_id:
                    raise SessionRetryHostRequiredError("only the session host may retry")
                state = _session_state(session["state"])
                snapshot_id = _latest_snapshot_id(cursor, session_id)

                # A second retry click while the first one is already queued is
                # safely idempotent and does not create another logical job.
                if state == "processing":
                    return RetrySessionView(snapshot_id, "processing", ())
                if state != "needs_attention":
                    raise SessionRetryUnavailableError("session has no retryable generation work")

                cursor.execute(
                    """
                    SELECT id, kind, state
                    FROM generation_runs
                    WHERE snapshot_id = %s
                    FOR UPDATE
                    """,
                    (snapshot_id,),
                )
                runs = cursor.fetchall()
                retryable_kinds = tuple(
                    _generation_kind(row["kind"])
                    for row in runs
                    if row["state"] == "failed_retryable"
                )
                if not retryable_kinds:
                    raise SessionRetryUnavailableError("no retryable generation run exists")
                for kind in retryable_kinds:
                    cursor.execute(
                        """
                        UPDATE jobs
                        SET state = 'pending',
                            error_code = NULL,
                            updated_at = clock_timestamp()
                        WHERE snapshot_id = %s
                          AND kind = %s
                          AND state = 'failed_retryable'
                          AND lease_token IS NULL
                          AND lease_owner IS NULL
                          AND lease_until IS NULL
                        """,
                        (snapshot_id, kind),
                    )
                    if cursor.rowcount != 1:
                        raise SessionRetryUnavailableError(
                            "retryable generation job is unavailable"
                        )
                    cursor.execute(
                        """
                        UPDATE generation_runs
                        SET state = 'queued', error_code = NULL, completed_at = NULL
                        WHERE snapshot_id = %s AND kind = %s
                          AND state = 'failed_retryable'
                        """,
                        (snapshot_id, kind),
                    )
                    if cursor.rowcount != 1:
                        raise SessionRetryUnavailableError(
                            "retryable generation run is unavailable"
                        )
                cursor.execute(
                    """
                    UPDATE talk_sessions
                    SET state = 'processing', state_version = state_version + 1,
                        retry_ordinal = retry_ordinal + 1
                    WHERE id = %s AND state = 'needs_attention'
                    RETURNING state_version,retry_ordinal
                    """,
                    (session_id,),
                )
                if cursor.rowcount != 1:
                    raise SessionRetryUnavailableError("session changed while retry was locked")
                updated = cursor.fetchone()
                if updated is None:
                    raise SessionRetryUnavailableError("retry state counters were not returned")
                room_id = _uuid(session["room_id"], "session room id")
                generation_epoch = int(session["generation_epoch"])
                state_version = int(updated["state_version"])
                retry_ordinal = int(updated["retry_ordinal"])
                self._activities.record(
                    cursor,
                    event_key=build_event_key(
                        "session.retry_requested", session_id=session_id,
                        generation_epoch=generation_epoch, retry_ordinal=retry_ordinal,
                    ),
                    event_type="session.retry_requested", actor_id=actor_id,
                    scope_type="session", room_id=room_id, session_id=session_id,
                    entity_type="session", entity_id=session_id,
                    metadata={"generation_epoch": generation_epoch,
                              "retry_ordinal": retry_ordinal,
                              "requeued_count": len(retryable_kinds)},
                )
                self._activities.record(
                    cursor,
                    event_key=build_event_key(
                        "session.processing", session_id=session_id,
                        state_version=state_version,
                    ),
                    event_type="session.processing", actor_id=actor_id,
                    scope_type="session", room_id=room_id, session_id=session_id,
                    entity_type="session", entity_id=session_id,
                    metadata={"previous_state": "needs_attention", "state": "processing",
                              "state_version": state_version,
                              "generation_epoch": generation_epoch},
                )
        return RetrySessionView(snapshot_id, "processing", retryable_kinds)


def _latest_snapshot_id(
    cursor: psycopg.Cursor[dict[str, Any]],
    session_id: UUID,
) -> UUID:
    cursor.execute(
        """
        SELECT id
        FROM generation_snapshots
        WHERE session_id = %s
        ORDER BY generation_epoch DESC
        LIMIT 1
        """,
        (session_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise SessionRetryUnavailableError("session has no generation snapshot")
    value = row["id"]
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise RuntimeError("persisted snapshot id must be UUID")


def _generation_kind(value: object) -> Literal["summary", "research"]:
    if value in {"summary", "research"}:
        return value
    raise RuntimeError("persisted generation kind is invalid")


def _session_state(
    value: object,
) -> Literal["draft", "open", "closed", "processing", "ready", "needs_attention"]:
    if value in {"draft", "open", "closed", "processing", "ready", "needs_attention"}:
        return value
    raise RuntimeError("persisted session state is invalid")


def _uuid(value: object, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise RuntimeError(f"persisted {label} must be UUID")
