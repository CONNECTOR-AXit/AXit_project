"""Pure domain types for the first durable Meeting RAG milestone.

These types deliberately do not know about FastAPI, PostgreSQL, or ORM
objects.  Repository code is responsible for mapping persisted records into
these value objects before applying the policies in this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DomainInvariantError(ValueError):
    """Raised when a caller presents an impossible domain aggregate."""


class SessionStateError(ValueError):
    """Raised when a talk-session transition is not permitted."""


class ActorNotMemberError(PermissionError):
    """Raised before evaluating privileged actions for a non-member."""


class HostAuthorizationError(PermissionError):
    """Raised when a room member attempts a host-only action."""


class CloseBlockedError(ValueError):
    """Raised when a close request omits an explicit unready exclusion."""

    def __init__(self, blocking_revision_ids: tuple[str, ...]) -> None:
        self.blocking_revision_ids = blocking_revision_ids
        super().__init__(
            "current revisions are not ready or explicitly excluded: "
            + ", ".join(blocking_revision_ids)
        )


class JobNotClaimableError(ValueError):
    """Raised when a job is neither pending nor expired-running."""


class StaleLeaseError(ValueError):
    """Raised when a worker's generation/token no longer owns a job lease."""


class TalkSessionState(StrEnum):
    """Persisted aggregate state for a delivery-style talk session."""

    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"
    PROCESSING = "processing"
    READY = "ready"
    NEEDS_ATTENTION = "needs_attention"


class RevisionProcessingState(StrEnum):
    """Processing state for a current source revision."""

    UPLOADED = "uploaded"
    QUEUED = "queued"
    EXTRACTING = "extracting"
    READY = "ready"
    FAILED = "failed"


class GenerationKind(StrEnum):
    """The two independently executed canonical generation artifacts."""

    SUMMARY = "summary"
    RESEARCH = "research"


class GenerationRunState(StrEnum):
    """Lifecycle state for one canonical summary or research run."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"

    @property
    def is_active(self) -> bool:
        """Whether the canonical run still has work in progress."""

        return self in {self.QUEUED, self.RUNNING}

    @property
    def is_failure(self) -> bool:
        """Whether the run has stopped without producing its artifact."""

        return self in {self.FAILED_RETRYABLE, self.FAILED_TERMINAL}

    @property
    def is_retryable_failure(self) -> bool:
        """Whether the host may retry this canonical kind."""

        return self is self.FAILED_RETRYABLE


class JobState(StrEnum):
    """Durable logical-job state used by the queue repository."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


class AggregateAction(StrEnum):
    """Host-visible next action derived from generation run states."""

    NONE = "none"
    RETRY = "retry"
    OPERATOR_OR_REPLAN = "operator_or_replan"


@dataclass(frozen=True, slots=True)
class RevisionStatus:
    """The only revision data needed to decide whether a session may close."""

    revision_id: str
    processing_state: RevisionProcessingState

    def __post_init__(self) -> None:
        _require_identifier("revision_id", self.revision_id)


@dataclass(frozen=True, slots=True)
class CloseExclusion:
    """A host's explicit exclusion request for one current revision.

    The repository persists actor and timestamp audit fields alongside this
    value.  They are intentionally absent here because the policy only needs
    an immutable revision identity and a human-readable reason.
    """

    revision_id: str
    reason: str

    def __post_init__(self) -> None:
        _require_identifier("revision_id", self.revision_id)
        if not self.reason.strip():
            raise DomainInvariantError("exclusion reason must not be blank")


@dataclass(frozen=True, slots=True)
class CloseEligibility:
    """Deterministic close decision derived from current revisions."""

    eligible: bool
    included_revision_ids: tuple[str, ...]
    excluded_revision_ids: tuple[str, ...]
    blocking_revision_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GenerationRunView:
    """Minimal canonical-run data needed for an aggregate projection."""

    kind: GenerationKind
    state: GenerationRunState
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.error_code is not None and not self.error_code.strip():
            raise DomainInvariantError("generation error_code must not be blank")


@dataclass(frozen=True, slots=True)
class AggregateReason:
    """A stable, machine-readable explanation for ``needs_attention``."""

    code: str
    kind: GenerationKind | None
    retryable: bool

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise DomainInvariantError("aggregate reason code must not be blank")


@dataclass(frozen=True, slots=True)
class GenerationAggregate:
    """Projected talk-session outcome from the two canonical run states."""

    state: TalkSessionState
    reasons: tuple[AggregateReason, ...]
    retry_available: bool
    action: AggregateAction


@dataclass(frozen=True, slots=True)
class JobLeaseView:
    """Persisted job fields required to create a fencing-aware intent."""

    job_id: str
    state: JobState
    lease_generation: int
    lease_token: str | None
    lease_until: datetime | None

    def __post_init__(self) -> None:
        _require_identifier("job_id", self.job_id)
        if self.lease_generation < 0:
            raise DomainInvariantError("lease_generation must not be negative")
        if self.lease_token is not None and not self.lease_token.strip():
            raise DomainInvariantError("lease_token must not be blank")
        if self.state is JobState.RUNNING:
            if self.lease_generation == 0:
                raise DomainInvariantError("running job must have a lease generation")
            if self.lease_token is None or self.lease_until is None:
                raise DomainInvariantError("running job must have a token and expiry")


@dataclass(frozen=True, slots=True)
class JobClaimIntent:
    """CAS preconditions and replacement lease for a short claim transaction."""

    job_id: str
    expected_state: JobState
    expected_lease_generation: int
    expected_lease_token: str | None
    owner_id: str
    lease_generation: int
    lease_token: str
    lease_until: datetime
    reclaimed_expired_lease: bool


@dataclass(frozen=True, slots=True)
class JobHeartbeatIntent:
    """CAS preconditions and extended expiry for an owned running job."""

    job_id: str
    lease_generation: int
    lease_token: str
    lease_until: datetime


@dataclass(frozen=True, slots=True)
class JobCompletionIntent:
    """CAS preconditions for atomically persisting a completed logical job."""

    job_id: str
    lease_generation: int
    lease_token: str
    target_state: JobState


@dataclass(frozen=True, slots=True)
class JobRequeueIntent:
    """CAS preconditions for retrying the same logical job row."""

    job_id: str
    expected_lease_generation: int


def _require_identifier(field_name: str, value: str) -> None:
    if not value.strip():
        raise DomainInvariantError(f"{field_name} must not be blank")
