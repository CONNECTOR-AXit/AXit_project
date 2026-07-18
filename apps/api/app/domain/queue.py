"""Pure fencing/CAS intent construction for the durable PostgreSQL queue."""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta

from app.domain.models import (
    DomainInvariantError,
    JobClaimIntent,
    JobCompletionIntent,
    JobHeartbeatIntent,
    JobLeaseView,
    JobNotClaimableError,
    JobRequeueIntent,
    JobState,
    StaleLeaseError,
)


_COMPLETION_STATES = frozenset(
    {
        JobState.SUCCEEDED,
        JobState.FAILED_RETRYABLE,
        JobState.FAILED_TERMINAL,
    }
)


def build_claim_intent(
    job: JobLeaseView,
    *,
    owner_id: str,
    new_lease_token: str,
    database_now: datetime,
    lease_duration: timedelta,
) -> JobClaimIntent:
    """Build a DB-clock-based claim intent for a pending or expired job.

    The repository must still enforce all fields in one ``UPDATE``/claim
    transaction, including the expired-running predicate against PostgreSQL's
    clock.  This function only makes the policy observable and unit-testable.
    ``new_lease_token`` must come from a cryptographically secure adapter.
    """

    _require_identifier("owner_id", owner_id)
    _require_identifier("new_lease_token", new_lease_token)
    _require_aware("database_now", database_now)
    _require_positive_duration(lease_duration)

    if job.state is JobState.PENDING:
        reclaimed_expired_lease = False
    elif job.state is JobState.RUNNING and job.lease_until is not None:
        _require_aware("job.lease_until", job.lease_until)
        if job.lease_until > database_now:
            raise JobNotClaimableError("running job lease has not expired")
        reclaimed_expired_lease = True
    else:
        raise JobNotClaimableError(
            f"job in {job.state} cannot be claimed without an explicit requeue"
        )

    return JobClaimIntent(
        job_id=job.job_id,
        expected_state=job.state,
        expected_lease_generation=job.lease_generation,
        expected_lease_token=job.lease_token,
        owner_id=owner_id,
        lease_generation=job.lease_generation + 1,
        lease_token=new_lease_token,
        lease_until=database_now + lease_duration,
        reclaimed_expired_lease=reclaimed_expired_lease,
    )


def build_heartbeat_intent(
    job: JobLeaseView,
    *,
    lease_generation: int,
    lease_token: str,
    database_now: datetime,
    lease_duration: timedelta,
) -> JobHeartbeatIntent:
    """Build an exact-generation/token CAS heartbeat extension."""

    _assert_current_lease(job, lease_generation=lease_generation, lease_token=lease_token)
    _require_aware("database_now", database_now)
    _require_positive_duration(lease_duration)
    return JobHeartbeatIntent(
        job_id=job.job_id,
        lease_generation=lease_generation,
        lease_token=lease_token,
        lease_until=database_now + lease_duration,
    )


def build_completion_intent(
    job: JobLeaseView,
    *,
    lease_generation: int,
    lease_token: str,
    target_state: JobState,
) -> JobCompletionIntent:
    """Build exact CAS preconditions for a completion transaction.

    The repository must insert/upsert the canonical result and apply the
    matching ``running`` transition in one transaction.  A zero-row CAS must
    roll that transaction back so a stale worker cannot persist a result.
    """

    _assert_current_lease(job, lease_generation=lease_generation, lease_token=lease_token)
    if target_state not in _COMPLETION_STATES:
        raise DomainInvariantError(
            "completion target must be succeeded, failed_retryable, or failed_terminal"
        )
    return JobCompletionIntent(
        job_id=job.job_id,
        lease_generation=lease_generation,
        lease_token=lease_token,
        target_state=target_state,
    )


def build_requeue_intent(job: JobLeaseView) -> JobRequeueIntent:
    """Return CAS preconditions for retrying the same logical job row."""

    if job.state is not JobState.FAILED_RETRYABLE:
        raise DomainInvariantError("only failed_retryable jobs may be requeued")
    return JobRequeueIntent(
        job_id=job.job_id,
        expected_lease_generation=job.lease_generation,
    )


def _assert_current_lease(
    job: JobLeaseView,
    *,
    lease_generation: int,
    lease_token: str,
) -> None:
    if lease_generation < 1:
        raise StaleLeaseError("lease generation must be positive")
    _require_identifier("lease_token", lease_token)
    if (
        job.state is not JobState.RUNNING
        or job.lease_generation != lease_generation
        or job.lease_token is None
        or not hmac.compare_digest(job.lease_token, lease_token)
    ):
        raise StaleLeaseError("job lease generation or token is stale")


def _require_identifier(field_name: str, value: str) -> None:
    if not value.strip():
        raise DomainInvariantError(f"{field_name} must not be blank")


def _require_aware(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainInvariantError(f"{field_name} must be timezone-aware")


def _require_positive_duration(value: timedelta) -> None:
    if value <= timedelta(0):
        raise DomainInvariantError("lease_duration must be positive")
