"""Pure policies for session lifecycle, closing, and result projection."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from app.domain.models import (
    ActorNotMemberError,
    AggregateAction,
    AggregateReason,
    CloseBlockedError,
    CloseEligibility,
    CloseExclusion,
    DomainInvariantError,
    GenerationAggregate,
    GenerationKind,
    GenerationRunState,
    GenerationRunView,
    HostAuthorizationError,
    RevisionProcessingState,
    RevisionStatus,
    SessionStateError,
    TalkSessionState,
)


CANONICAL_GENERATION_KINDS: Final[tuple[GenerationKind, ...]] = (
    GenerationKind.SUMMARY,
    GenerationKind.RESEARCH,
)

_ALLOWED_SESSION_TRANSITIONS: Final[
    dict[TalkSessionState, frozenset[TalkSessionState]]
] = {
    TalkSessionState.DRAFT: frozenset({TalkSessionState.OPEN}),
    TalkSessionState.OPEN: frozenset({TalkSessionState.CLOSED}),
    TalkSessionState.CLOSED: frozenset({TalkSessionState.PROCESSING}),
    TalkSessionState.PROCESSING: frozenset(
        {TalkSessionState.READY, TalkSessionState.NEEDS_ATTENTION}
    ),
    TalkSessionState.NEEDS_ATTENTION: frozenset({TalkSessionState.PROCESSING}),
    TalkSessionState.READY: frozenset(),
}


def allowed_session_targets(state: TalkSessionState) -> frozenset[TalkSessionState]:
    """Return the only legal next states for a delivery session."""

    return _ALLOWED_SESSION_TRANSITIONS[state]


def assert_session_transition(
    current: TalkSessionState,
    target: TalkSessionState,
) -> None:
    """Reject any state change outside the approved aggregate state graph."""

    if target not in allowed_session_targets(current):
        raise SessionStateError(f"cannot transition talk session {current} -> {target}")


def require_open_session(state: TalkSessionState) -> None:
    """Require the state shared by submit, replace, and close transactions."""

    if state is not TalkSessionState.OPEN:
        raise SessionStateError(f"talk session must be open, got {state}")


def assert_room_member(actor_id: str, member_user_ids: Iterable[str]) -> None:
    """Check membership before any resource-specific authorization decision."""

    if not actor_id.strip():
        raise DomainInvariantError("actor_id must not be blank")
    if actor_id not in set(member_user_ids):
        raise ActorNotMemberError("actor is not a room member")


def assert_host_actor(
    actor_id: str,
    host_user_id: str,
    member_user_ids: Iterable[str],
) -> None:
    """Require a current room member and then the designated session host.

    Membership intentionally precedes the host comparison so callers do not
    turn a host-only endpoint into a membership oracle.
    """

    assert_room_member(actor_id, member_user_ids)
    if not host_user_id.strip():
        raise DomainInvariantError("host_user_id must not be blank")
    if actor_id != host_user_id:
        raise HostAuthorizationError("only the room host may perform this action")


def evaluate_close_eligibility(
    current_revisions: Iterable[RevisionStatus],
    exclusions: Iterable[CloseExclusion],
) -> CloseEligibility:
    """Evaluate the close invariant using exactly the current revisions.

    A non-ready revision must have an explicit exclusion.  Explicitly
    excluding a ready revision is allowed: it is an intentional snapshot
    scope decision and remains auditable in ``snapshot_exclusions``.  This
    pure result is ordered by immutable revision ID so repositories can build
    a deterministic snapshot projection.
    """

    revisions_by_id: dict[str, RevisionStatus] = {}
    for revision in current_revisions:
        if revision.revision_id in revisions_by_id:
            raise DomainInvariantError(
                f"duplicate current revision: {revision.revision_id}"
            )
        revisions_by_id[revision.revision_id] = revision

    exclusions_by_id: dict[str, CloseExclusion] = {}
    for exclusion in exclusions:
        if exclusion.revision_id in exclusions_by_id:
            raise DomainInvariantError(
                f"duplicate close exclusion: {exclusion.revision_id}"
            )
        exclusions_by_id[exclusion.revision_id] = exclusion

    unknown_exclusions = sorted(set(exclusions_by_id) - set(revisions_by_id))
    if unknown_exclusions:
        raise DomainInvariantError(
            "close exclusions must reference current revisions: "
            + ", ".join(unknown_exclusions)
        )

    ordered_revision_ids = tuple(sorted(revisions_by_id))
    excluded_revision_ids = tuple(
        revision_id
        for revision_id in ordered_revision_ids
        if revision_id in exclusions_by_id
    )
    included_revision_ids = tuple(
        revision_id
        for revision_id in ordered_revision_ids
        if revision_id not in exclusions_by_id
        and revisions_by_id[revision_id].processing_state
        is RevisionProcessingState.READY
    )
    blocking_revision_ids = tuple(
        revision_id
        for revision_id in ordered_revision_ids
        if revisions_by_id[revision_id].processing_state
        is not RevisionProcessingState.READY
        and revision_id not in exclusions_by_id
    )
    return CloseEligibility(
        eligible=not blocking_revision_ids,
        included_revision_ids=included_revision_ids,
        excluded_revision_ids=excluded_revision_ids,
        blocking_revision_ids=blocking_revision_ids,
    )


def require_close_eligibility(
    current_revisions: Iterable[RevisionStatus],
    exclusions: Iterable[CloseExclusion],
) -> CloseEligibility:
    """Return a valid close decision or identify every blocking revision."""

    decision = evaluate_close_eligibility(current_revisions, exclusions)
    if not decision.eligible:
        raise CloseBlockedError(decision.blocking_revision_ids)
    return decision


def project_generation_aggregate(
    canonical_runs: Iterable[GenerationRunView],
) -> GenerationAggregate:
    """Project the host-visible session result state deterministically.

    This implements the approved two-kind combination table.  Missing or
    duplicate canonical runs are invariant failures rather than a transient
    ``processing`` state because the close transaction must create exactly one
    summary and research logical run for a snapshot/pipeline version.
    """

    runs_by_kind: dict[GenerationKind, list[GenerationRunView]] = {
        kind: [] for kind in CANONICAL_GENERATION_KINDS
    }
    for run in canonical_runs:
        runs_by_kind[run.kind].append(run)

    invariant_reasons = _canonical_run_invariant_reasons(runs_by_kind)
    if invariant_reasons:
        return GenerationAggregate(
            state=TalkSessionState.NEEDS_ATTENTION,
            reasons=invariant_reasons,
            retry_available=False,
            action=AggregateAction.OPERATOR_OR_REPLAN,
        )

    runs = tuple(runs_by_kind[kind][0] for kind in CANONICAL_GENERATION_KINDS)
    if all(run.state is GenerationRunState.SUCCEEDED for run in runs):
        return GenerationAggregate(
            state=TalkSessionState.READY,
            reasons=(),
            retry_available=False,
            action=AggregateAction.NONE,
        )

    if any(run.state.is_active for run in runs):
        return GenerationAggregate(
            state=TalkSessionState.PROCESSING,
            reasons=(),
            retry_available=False,
            action=AggregateAction.NONE,
        )

    failure_reasons = tuple(_failure_reason(run) for run in runs if run.state.is_failure)
    if not failure_reasons:
        raise DomainInvariantError("canonical generation runs cannot be projected")

    retry_available = any(reason.retryable for reason in failure_reasons)
    return GenerationAggregate(
        state=TalkSessionState.NEEDS_ATTENTION,
        reasons=failure_reasons,
        retry_available=retry_available,
        action=(
            AggregateAction.RETRY
            if retry_available
            else AggregateAction.OPERATOR_OR_REPLAN
        ),
    )


def _canonical_run_invariant_reasons(
    runs_by_kind: dict[GenerationKind, list[GenerationRunView]],
) -> tuple[AggregateReason, ...]:
    reasons: list[AggregateReason] = []
    for kind in CANONICAL_GENERATION_KINDS:
        count = len(runs_by_kind[kind])
        if count == 0:
            reasons.append(
                AggregateReason(
                    code="invariant_error_missing_run",
                    kind=kind,
                    retryable=False,
                )
            )
        elif count > 1:
            reasons.append(
                AggregateReason(
                    code="invariant_error_duplicate_run",
                    kind=kind,
                    retryable=False,
                )
            )
    return tuple(reasons)


def _failure_reason(run: GenerationRunView) -> AggregateReason:
    retryable = run.state.is_retryable_failure
    fallback = f"{run.kind.value}_{run.state.value}"
    return AggregateReason(
        code=run.error_code or fallback,
        kind=run.kind,
        retryable=retryable,
    )
