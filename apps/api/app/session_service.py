"""Durable close transaction for a talk session's first generation epoch."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.activity_policy import build_event_key
from app.activity_service import ActivityService
from app.domain import (
    CloseExclusion,
    RevisionProcessingState,
    RevisionStatus,
    TalkSessionState,
    require_close_eligibility,
)


_CANONICAL_GENERATION_KINDS: Final[tuple[str, str]] = ("summary", "research")
_MOCK_PROVIDER: Final = "mock"
_MOCK_MODEL: Final = "fixture-v1"
_PROMPT_VERSION: Final = "phase2-contract-v1"


class SessionAccessError(PermissionError):
    """Hide non-member session existence before state details are inspected."""


class SessionHostRequiredError(PermissionError):
    """Raised only after membership is established for a host-only close."""


class SessionStateError(ValueError):
    """Raised when a session cannot provide an idempotent close response."""


class ExtractionRunMissingError(ValueError):
    """A ready revision cannot be snapshotted without a pinned successful run."""


class ExtractionAnchorSchemaMismatchError(ValueError):
    """Approved extraction runs must pin one exact snapshot anchor schema."""


@dataclass(frozen=True, slots=True)
class CloseExclusionRequest:
    revision_id: UUID
    reason: str


@dataclass(frozen=True, slots=True)
class ClosedSnapshot:
    snapshot_id: UUID
    generation_epoch: int
    state: TalkSessionState
    idempotent: bool


class SessionCloseService:
    """Apply parent-lock, audit, snapshot, and job creation in one transaction."""

    def __init__(self, activity_service: ActivityService | None = None) -> None:
        self._activities = activity_service or ActivityService()

    def close(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
        exclusions: Iterable[CloseExclusionRequest],
        pipeline_version: str,
        anchor_schema_version: str | None = None,
    ) -> ClosedSnapshot:
        """Close exactly one open session or return its canonical snapshot.

        Membership is joined into the parent-row lock query so callers who are
        not current room members never receive a state/host distinction.  The
        resulting transaction follows the approved order: lock parent, check
        open/host policy, record exclusions, pin snapshot/revisions/runs, and
        create both logical jobs before exposing ``processing``.
        """

        if not pipeline_version.strip():
            raise ValueError("pipeline_version must not be blank")
        if anchor_schema_version is not None and not anchor_schema_version.strip():
            raise ValueError("anchor_schema_version must not be blank")
        requested_exclusions = tuple(exclusions)
        domain_exclusions = tuple(
            CloseExclusion(str(item.revision_id), item.reason)
            for item in requested_exclusions
        )

        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT session_row.id, session_row.host_id, session_row.topic,
                           session_row.state, session_row.generation_epoch,
                           session_row.state_version, session_row.retry_ordinal,
                           session_row.room_id
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
                    raise SessionAccessError("session is unavailable")
                if session["host_id"] != actor_id:
                    raise SessionHostRequiredError("only the session host may close")

                state = TalkSessionState(str(session["state"]))
                if state is not TalkSessionState.OPEN:
                    return _existing_snapshot_or_raise(cursor, session_id, state)

                cursor.execute(
                    """
                    SELECT revision.id, revision.processing_state,
                           revision.approved_extraction_run_id,
                           approved_run.status AS approved_extraction_status,
                           approved_run.anchor_schema_version AS approved_anchor_schema_version
                    FROM source_revisions AS revision
                    JOIN submissions AS submission ON submission.id = revision.submission_id
                    LEFT JOIN extraction_runs AS approved_run
                      ON approved_run.id = revision.approved_extraction_run_id
                     AND approved_run.source_revision_id = revision.id
                    WHERE submission.session_id = %s AND revision.is_current
                      AND submission.deleted_at IS NULL
                    ORDER BY revision.id
                    """,
                    (session_id,),
                )
                revision_rows = cursor.fetchall()
                current_revisions = tuple(
                    RevisionStatus(
                        str(row["id"]),
                        RevisionProcessingState(str(row["processing_state"])),
                    )
                    for row in revision_rows
                )
                eligibility = require_close_eligibility(
                    current_revisions,
                    domain_exclusions,
                )

                revision_by_id = {str(row["id"]): row["id"] for row in revision_rows}
                for requested in requested_exclusions:
                    cursor.execute(
                        """
                        INSERT INTO snapshot_exclusions (
                            id, session_id, source_revision_id, reason, actor_id
                        ) VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            uuid4(),
                            session_id,
                            revision_by_id[str(requested.revision_id)],
                            requested.reason,
                            actor_id,
                        ),
                    )

                included_revision_ids = tuple(
                    revision_by_id[revision_id]
                    for revision_id in eligibility.included_revision_ids
                )
                extraction_runs = {
                    _require_uuid(row["id"], "source revision id"): (
                        _require_uuid(
                            row["approved_extraction_run_id"], "approved extraction run id"
                        ),
                        _require_nonempty_text(
                            row["approved_anchor_schema_version"],
                            "approved anchor schema version",
                        ),
                    )
                    for row in revision_rows
                    if row["approved_extraction_run_id"] is not None
                    and row["approved_extraction_status"] == "succeeded"
                }
                missing_runs = sorted(
                    str(revision_id)
                    for revision_id in included_revision_ids
                    if revision_id not in extraction_runs
                )
                if missing_runs:
                    raise ExtractionRunMissingError(
                        "ready revisions require successful approved extraction runs: "
                        + ", ".join(missing_runs)
                    )
                pinned_anchor_schema_versions = {
                    extraction_runs[revision_id][1]
                    for revision_id in included_revision_ids
                }
                if len(pinned_anchor_schema_versions) != 1:
                    raise ExtractionAnchorSchemaMismatchError(
                        "included approved extraction runs must use exactly one anchor schema version"
                    )
                pinned_anchor_schema_version = pinned_anchor_schema_versions.pop()
                if (
                    anchor_schema_version is not None
                    and anchor_schema_version != pinned_anchor_schema_version
                ):
                    raise ExtractionAnchorSchemaMismatchError(
                        "requested anchor schema version does not match approved extraction runs"
                    )

                next_epoch = int(session["generation_epoch"]) + 1
                snapshot_id = uuid4()
                # These two updates make the approved open -> closed ->
                # processing transition explicit while remaining unobservable
                # outside this transaction.
                cursor.execute(
                    """
                    UPDATE talk_sessions
                    SET state = 'closed', closed_at = CURRENT_TIMESTAMP,
                        state_version = state_version + 1
                    WHERE id = %s AND state = 'open'
                    RETURNING state_version
                    """,
                    (session_id,),
                )
                if cursor.rowcount != 1:
                    raise SessionStateError("session changed while its parent lock was held")
                closed_row = cursor.fetchone()
                if closed_row is None:
                    raise SessionStateError("closed state version was not returned")
                room_id = _require_uuid(session["room_id"], "session room id")
                closed_version = int(closed_row["state_version"])
                self._activities.record(
                    cursor,
                    event_key=build_event_key(
                        "session.closed", session_id=session_id,
                        state_version=closed_version,
                    ),
                    event_type="session.closed", actor_id=actor_id,
                    scope_type="session", room_id=room_id, session_id=session_id,
                    entity_type="session", entity_id=session_id,
                    metadata={"previous_state": "open", "state": "closed",
                              "state_version": closed_version},
                )
                cursor.execute(
                    """
                    INSERT INTO generation_snapshots (
                        id, session_id, generation_epoch, created_by, topic_copy,
                        pipeline_version, anchor_schema_version
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        snapshot_id,
                        session_id,
                        next_epoch,
                        actor_id,
                        session["topic"],
                        pipeline_version,
                        pinned_anchor_schema_version,
                    ),
                )
                for revision_id in included_revision_ids:
                    cursor.execute(
                        """
                        INSERT INTO snapshot_revisions (
                            snapshot_id, source_revision_id, extraction_run_id
                        ) VALUES (%s, %s, %s)
                        """,
                        (snapshot_id, revision_id, extraction_runs[revision_id][0]),
                    )
                for kind in _CANONICAL_GENERATION_KINDS:
                    cursor.execute(
                        """
                        INSERT INTO generation_runs (
                            id, snapshot_id, kind, provider, model, prompt_version,
                            pipeline_version, state
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'queued')
                        """,
                        (
                            uuid4(),
                            snapshot_id,
                            kind,
                            _MOCK_PROVIDER,
                            _MOCK_MODEL,
                            _PROMPT_VERSION,
                            pipeline_version,
                        ),
                    )
                    logical_key = f"generation:{snapshot_id}:{kind}:{pipeline_version}"
                    cursor.execute(
                        """
                        INSERT INTO jobs (
                            id, logical_key, kind, snapshot_id, payload_json, state
                        ) VALUES (%s, %s, %s, %s, %s, 'pending')
                        """,
                        (
                            uuid4(),
                            logical_key,
                            kind,
                            snapshot_id,
                            Jsonb(
                                {
                                    "snapshot_id": str(snapshot_id),
                                    "kind": kind,
                                    "pipeline_version": pipeline_version,
                                }
                            ),
                        ),
                    )
                cursor.execute(
                    """
                    UPDATE talk_sessions
                    SET state = 'processing', generation_epoch = %s,
                        state_version = state_version + 1, retry_ordinal = 0
                    WHERE id = %s AND state = 'closed'
                    RETURNING state_version
                    """,
                    (next_epoch, session_id),
                )
                if cursor.rowcount != 1:
                    raise SessionStateError("session could not enter processing")
                processing_row = cursor.fetchone()
                if processing_row is None:
                    raise SessionStateError("processing state version was not returned")
                processing_version = int(processing_row["state_version"])
                self._activities.record(
                    cursor,
                    event_key=build_event_key(
                        "session.processing", session_id=session_id,
                        state_version=processing_version,
                    ),
                    event_type="session.processing", actor_id=actor_id,
                    scope_type="session", room_id=room_id, session_id=session_id,
                    entity_type="session", entity_id=session_id,
                    metadata={"previous_state": "closed", "state": "processing",
                              "state_version": processing_version,
                              "generation_epoch": next_epoch},
                )

        return ClosedSnapshot(
            snapshot_id=snapshot_id,
            generation_epoch=next_epoch,
            state=TalkSessionState.PROCESSING,
            idempotent=False,
        )

    def reopen(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
    ) -> TalkSessionState:
        """Send an already-analyzed session back to ``open`` for more input.

        Only valid from a terminal analysis state (``ready`` or
        ``needs_attention``) — closing again later pins whatever is current
        at that moment into a brand-new snapshot (a new ``generation_epoch``),
        so every prior snapshot/run/document stays exactly as it was and
        keeps working from its own ``snapshot_id``. Nothing here rewrites or
        deletes earlier analysis history.
        """

        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT session_row.id, session_row.host_id, session_row.state,
                           session_row.room_id
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
                    raise SessionAccessError("session is unavailable")
                if session["host_id"] != actor_id:
                    raise SessionHostRequiredError("only the session host may reopen")

                state = TalkSessionState(str(session["state"]))
                # A report remains viewable after the first reopen, so users can
                # revisit it and press reanalysis again while the session is
                # already open. Treat that repeat intent as an idempotent success
                # instead of surfacing a misleading 409 state conflict.
                if state is TalkSessionState.OPEN:
                    return TalkSessionState.OPEN
                if state not in (TalkSessionState.READY, TalkSessionState.NEEDS_ATTENTION):
                    raise SessionStateError(
                        f"talk session must be ready or needs_attention, got {state}"
                    )

                cursor.execute(
                    """
                    UPDATE talk_sessions
                    SET state = 'open', closed_at = NULL, state_version = state_version + 1
                    WHERE id = %s AND state = %s
                    RETURNING state_version
                    """,
                    (session_id, state.value),
                )
                if cursor.rowcount != 1:
                    raise SessionStateError("session changed while its parent lock was held")
                reopened_row = cursor.fetchone()
                if reopened_row is None:
                    raise SessionStateError("reopened state version was not returned")
                reopened_version = int(reopened_row["state_version"])
                room_id = _require_uuid(session["room_id"], "session room id")
                self._activities.record(
                    cursor,
                    event_key=build_event_key(
                        "session.reopened", session_id=session_id,
                        state_version=reopened_version,
                    ),
                    event_type="session.reopened", actor_id=actor_id,
                    scope_type="session", room_id=room_id, session_id=session_id,
                    entity_type="session", entity_id=session_id,
                    metadata={"previous_state": state.value, "state": "open",
                              "state_version": reopened_version},
                )
        return TalkSessionState.OPEN


def _existing_snapshot_or_raise(
    cursor: psycopg.Cursor[dict[str, Any]],
    session_id: UUID,
    state: TalkSessionState,
) -> ClosedSnapshot:
    if state not in {
        TalkSessionState.CLOSED,
        TalkSessionState.PROCESSING,
        TalkSessionState.READY,
        TalkSessionState.NEEDS_ATTENTION,
    }:
        raise SessionStateError(f"session must be open, got {state.value}")
    cursor.execute(
        """
        SELECT id, generation_epoch
        FROM generation_snapshots
        WHERE session_id = %s
        ORDER BY generation_epoch DESC
        LIMIT 1
        """,
        (session_id,),
    )
    snapshot = cursor.fetchone()
    if snapshot is None:
        raise SessionStateError("closed session has no canonical generation snapshot")
    return ClosedSnapshot(
        snapshot_id=_require_uuid(snapshot["id"], "snapshot id"),
        generation_epoch=int(snapshot["generation_epoch"]),
        state=state,
        idempotent=True,
    )


def _require_uuid(value: object, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise SessionStateError(f"{label} must be UUID")


def _require_nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExtractionAnchorSchemaMismatchError(f"{label} must be non-empty text")
    return value
