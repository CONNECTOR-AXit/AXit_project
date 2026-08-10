"""PostgreSQL implementation of the Phase 2 at-least-once fenced queue.

Claims are intentionally short transactions.  Parser/provider execution is
never performed here; callers receive a lease, work outside a transaction,
then persist one canonical result through the exact generation/token CAS.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain import JobState, StaleLeaseError


_ALLOWED_KINDS: Final[frozenset[str]] = frozenset(
    {"extraction", "summary", "research", "report_suggestions"}
)
_COMPLETION_STATES: Final[frozenset[JobState]] = frozenset(
    {
        JobState.SUCCEEDED,
        JobState.FAILED_RETRYABLE,
        JobState.FAILED_TERMINAL,
    }
)


class QueueInvariantError(RuntimeError):
    """Raised for invalid queue inputs or unexpected persisted queue shape."""


@dataclass(frozen=True, slots=True)
class DurableJob:
    """Stable logical job identity returned after enqueue/idempotency lookup."""

    id: UUID
    logical_key: str
    kind: str
    state: JobState
    lease_generation: int


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    """A worker-owned lease whose token must accompany every persistence CAS."""

    id: UUID
    logical_key: str
    kind: str
    payload: dict[str, object]
    owner: str
    lease_generation: int
    lease_token: UUID
    attempt_id: UUID


def canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    """Serialize a result deterministically before storing its integrity hash."""

    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise QueueInvariantError("queue payload must be finite JSON-compatible data") from error


class PostgresJobQueue:
    """Repository whose SQL, rather than process memory, is the queue authority."""

    def enqueue(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        logical_key: str,
        kind: str,
        payload: Mapping[str, object],
        snapshot_id: UUID | None = None,
    ) -> DurableJob:
        """Insert one logical job or return the existing idempotent job row."""

        _require_logical_key(logical_key)
        _require_kind(kind)
        payload_dict = dict(payload)
        canonical_json_bytes(payload_dict)
        job_id = uuid4()
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    INSERT INTO jobs (
                        id, logical_key, kind, snapshot_id, payload_json, state
                    ) VALUES (%s, %s, %s, %s, %s, 'pending')
                    ON CONFLICT (logical_key) DO NOTHING
                    RETURNING id, logical_key, kind, state, lease_generation
                    """,
                    (job_id, logical_key, kind, snapshot_id, Jsonb(payload_dict)),
                )
                row = cursor.fetchone()
                if row is None:
                    cursor.execute(
                        """
                        SELECT id, logical_key, kind, state, lease_generation
                        FROM jobs
                        WHERE logical_key = %s
                        """,
                        (logical_key,),
                    )
                    row = _required_row(cursor.fetchone(), "idempotent job")
        return _durable_job_from_row(row)

    def claim_next(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        owner: str,
        lease_seconds: int,
        kinds: Collection[str] | None = None,
    ) -> ClaimedJob | None:
        """Atomically claim one pending or expired-running job with DB time.

        ``FOR UPDATE SKIP LOCKED`` lets independent workers make progress
        without waiting for an external parser/provider call.  Reclaiming an
        expired row records the abandoned attempt before issuing a new lease.
        """

        _require_owner(owner)
        _require_lease_seconds(lease_seconds)
        claim_kinds = _normalize_claim_kinds(kinds)
        lease_token = uuid4()
        attempt_id = uuid4()
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                if claim_kinds is None:
                    cursor.execute(
                        """
                        SELECT id, logical_key, kind, payload_json, state,
                               lease_generation, lease_token
                        FROM jobs
                        WHERE state = 'pending'
                           OR (state = 'running' AND lease_until <= clock_timestamp())
                        ORDER BY created_at, id
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                        """
                    )
                elif not claim_kinds:
                    return None
                else:
                    cursor.execute(
                        """
                        SELECT id, logical_key, kind, payload_json, state,
                               lease_generation, lease_token
                        FROM jobs
                        WHERE (
                            state = 'pending'
                            OR (state = 'running' AND lease_until <= clock_timestamp())
                        )
                          AND kind = ANY(%s)
                        ORDER BY created_at, id
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                        """,
                        (list(claim_kinds),),
                    )
                row = cursor.fetchone()
                if row is None:
                    return None

                previous_generation = int(row["lease_generation"])
                if row["state"] == JobState.RUNNING.value:
                    cursor.execute(
                        """
                        UPDATE job_attempts
                        SET ended_at = clock_timestamp(),
                            status = 'expired',
                            error_code = 'lease_expired'
                        WHERE job_id = %s
                          AND lease_generation = %s
                          AND status = 'running'
                          AND ended_at IS NULL
                        """,
                        (row["id"], previous_generation),
                    )

                next_generation = previous_generation + 1
                cursor.execute(
                    """
                    UPDATE jobs
                    SET state = 'running',
                        attempts = attempts + 1,
                        lease_generation = %s,
                        lease_token = %s,
                        lease_owner = %s,
                        lease_until = clock_timestamp() + (%s * INTERVAL '1 second'),
                        heartbeat_at = clock_timestamp(),
                        error_code = NULL,
                        updated_at = clock_timestamp()
                    WHERE id = %s
                    """,
                    (next_generation, lease_token, owner, lease_seconds, row["id"]),
                )
                cursor.execute(
                    """
                    INSERT INTO job_attempts (
                        id, job_id, lease_generation, lease_token, owner, status
                    ) VALUES (%s, %s, %s, %s, %s, 'running')
                    """,
                    (attempt_id, row["id"], next_generation, lease_token, owner),
                )

        payload = row["payload_json"]
        if not isinstance(payload, dict):
            raise QueueInvariantError("persisted job payload must be a JSON object")
        return ClaimedJob(
            id=_as_uuid(row["id"], "job id"),
            logical_key=_as_nonempty_string(row["logical_key"], "logical key"),
            kind=_as_nonempty_string(row["kind"], "job kind"),
            payload=dict(payload),
            owner=owner,
            lease_generation=next_generation,
            lease_token=lease_token,
            attempt_id=attempt_id,
        )

    def heartbeat(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        claimed: ClaimedJob,
        *,
        lease_seconds: int,
    ) -> None:
        """Extend only the exact current lease or reject a stale worker."""

        _require_lease_seconds(lease_seconds)
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE jobs
                    SET heartbeat_at = clock_timestamp(),
                        lease_until = clock_timestamp() + (%s * INTERVAL '1 second'),
                        updated_at = clock_timestamp()
                    WHERE id = %s
                      AND state = 'running'
                      AND lease_generation = %s
                      AND lease_token = %s
                      AND lease_until > clock_timestamp()
                    """,
                    (
                        lease_seconds,
                        claimed.id,
                        claimed.lease_generation,
                        claimed.lease_token,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StaleLeaseError("job heartbeat lease is stale")

    def complete(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        claimed: ClaimedJob,
        *,
        target_state: JobState,
        result: Mapping[str, object],
        error_code: str | None = None,
    ) -> None:
        """Persist a terminal result without additional domain side effects."""

        self.complete_with_effects(
            connection,
            claimed,
            target_state=target_state,
            result=result,
            error_code=error_code,
        )

    def complete_with_effects(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        claimed: ClaimedJob,
        *,
        target_state: JobState,
        result: Mapping[str, object],
        error_code: str | None = None,
        effect: Callable[[Any], None] | None = None,
    ) -> None:
        """Persist a successful canonical result and exact lease completion atomically.

        The state CAS is evaluated before the insert.  If it affects zero
        rows, raising inside the transaction ensures a stale worker leaves no
        result behind.  Retryable/terminal failures retain only their typed
        error state in ``jobs``/``job_attempts`` so a later retry can still
        create the one canonical successful result. Any result insert failure
        also rolls the state back.  ``effect`` exists for Phase 3 generation
        persistence: it runs only after the lease/token CAS has succeeded and
        remains in this same transaction.  Therefore a stale worker cannot
        create a generated document/citation, and a failed domain write cannot
        leave a completed job without its canonical artifact.
        """

        if target_state not in _COMPLETION_STATES:
            raise QueueInvariantError("target_state must be a terminal queue state")
        if target_state is JobState.SUCCEEDED:
            if error_code is not None:
                raise QueueInvariantError("successful completion must not include an error_code")
        elif error_code is None or not error_code.strip():
            raise QueueInvariantError("failed completion requires a non-blank error_code")
        elif len(error_code) > 128:
            raise QueueInvariantError("error_code must be at most 128 characters")
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE jobs
                    SET state = %s,
                        lease_token = NULL,
                        lease_owner = NULL,
                        lease_until = NULL,
                        heartbeat_at = clock_timestamp(),
                        error_code = %s,
                        updated_at = clock_timestamp()
                    WHERE id = %s
                      AND state = 'running'
                      AND lease_generation = %s
                      AND lease_token = %s
                      AND lease_until > clock_timestamp()
                    """,
                    (
                        target_state.value,
                        error_code,
                        claimed.id,
                        claimed.lease_generation,
                        claimed.lease_token,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StaleLeaseError("job completion lease is stale")
                if effect is not None:
                    effect(cursor)
                if target_state is JobState.SUCCEEDED:
                    result_dict = dict(result)
                    encoded_result = canonical_json_bytes(result_dict)
                    result_hash = hashlib.sha256(encoded_result).hexdigest()
                    cursor.execute(
                        """
                        INSERT INTO job_results (id, job_id, result_json, result_hash)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (uuid4(), claimed.id, Jsonb(result_dict), result_hash),
                    )
                cursor.execute(
                    """
                    UPDATE job_attempts
                    SET ended_at = CURRENT_TIMESTAMP,
                        status = %s,
                        error_code = %s
                    WHERE job_id = %s
                      AND lease_generation = %s
                      AND lease_token = %s
                      AND status = 'running'
                      AND ended_at IS NULL
                    """,
                    (
                        "succeeded" if target_state is JobState.SUCCEEDED else "failed",
                        error_code,
                        claimed.id,
                        claimed.lease_generation,
                        claimed.lease_token,
                    ),
                )
                if cursor.rowcount != 1:
                    raise QueueInvariantError("current job attempt was not append-only running")

    def requeue_retryable(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        job_id: UUID,
        expected_lease_generation: int,
    ) -> None:
        """Retry the same logical row, never create a second logical key."""

        if expected_lease_generation < 1:
            raise QueueInvariantError("expected_lease_generation must be positive")
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE jobs
                    SET state = 'pending', error_code = NULL, updated_at = clock_timestamp()
                    WHERE id = %s
                      AND state = 'failed_retryable'
                      AND lease_generation = %s
                      AND lease_token IS NULL
                    """,
                    (job_id, expected_lease_generation),
                )
                if cursor.rowcount != 1:
                    raise StaleLeaseError("retry target is stale or not retryable")

    def fetch_job(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        job_id: UUID,
    ) -> DurableJob:
        """Fetch the persisted state needed by tests and worker supervision."""

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id, logical_key, kind, state, lease_generation
                FROM jobs WHERE id = %s
                """,
                (job_id,),
            )
            row = _required_row(cursor.fetchone(), "job")
        return _durable_job_from_row(row)

    def result_count(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        job_id: UUID,
    ) -> int:
        """Return whether a canonical result was persisted for one job."""

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) AS result_count FROM job_results WHERE job_id = %s",
                (job_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise QueueInvariantError("job result count query returned no row")
        return _as_int(row["result_count"], "job result count")


def _durable_job_from_row(row: Mapping[str, object]) -> DurableJob:
    return DurableJob(
        id=_as_uuid(row["id"], "job id"),
        logical_key=_as_nonempty_string(row["logical_key"], "logical key"),
        kind=_as_nonempty_string(row["kind"], "job kind"),
        state=JobState(_as_nonempty_string(row["state"], "job state")),
        lease_generation=_as_int(row["lease_generation"], "lease generation"),
    )


def _required_row(row: dict[str, Any] | None, label: str) -> dict[str, Any]:
    if row is None:
        raise QueueInvariantError(f"{label} does not exist")
    return row


def _as_uuid(value: object, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise QueueInvariantError(f"persisted {label} must be UUID")


def _as_nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QueueInvariantError(f"persisted {label} must be non-empty text")
    return value


def _as_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise QueueInvariantError(f"persisted {label} must be an integer")
    return value


def _require_logical_key(logical_key: str) -> None:
    if not logical_key.strip() or len(logical_key) > 500:
        raise QueueInvariantError("logical_key must be non-empty and at most 500 characters")


def _require_kind(kind: str) -> None:
    if kind not in _ALLOWED_KINDS:
        raise QueueInvariantError(f"unsupported job kind: {kind}")


def _normalize_claim_kinds(kinds: Collection[str] | None) -> tuple[str, ...] | None:
    if kinds is None:
        return None
    normalized = tuple(sorted(set(kinds)))
    for kind in normalized:
        _require_kind(kind)
    return normalized


def _require_owner(owner: str) -> None:
    if not owner.strip() or len(owner) > 200:
        raise QueueInvariantError("owner must be non-empty and at most 200 characters")


def _require_lease_seconds(lease_seconds: int) -> None:
    if lease_seconds < 1 or lease_seconds > 3_600:
        raise QueueInvariantError("lease_seconds must be between 1 and 3600")
