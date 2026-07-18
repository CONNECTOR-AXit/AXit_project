"""Unit contract for Phase 2's pure session, aggregate, and lease policies."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path

import pytest


API_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.domain import (  # noqa: E402
    ActorNotMemberError,
    AggregateAction,
    CloseBlockedError,
    CloseExclusion,
    DomainInvariantError,
    GenerationKind,
    GenerationRunState,
    GenerationRunView,
    HostAuthorizationError,
    JobLeaseView,
    JobNotClaimableError,
    JobState,
    RevisionProcessingState,
    RevisionStatus,
    SessionStateError,
    StaleLeaseError,
    TalkSessionState,
    allowed_session_targets,
    assert_host_actor,
    assert_session_transition,
    build_claim_intent,
    build_completion_intent,
    build_heartbeat_intent,
    build_requeue_intent,
    evaluate_close_eligibility,
    project_generation_aggregate,
    require_close_eligibility,
    require_open_session,
)


ALL_SESSION_STATES = tuple(TalkSessionState)
EXPECTED_SESSION_TRANSITIONS = {
    TalkSessionState.DRAFT: {TalkSessionState.OPEN},
    TalkSessionState.OPEN: {TalkSessionState.CLOSED},
    TalkSessionState.CLOSED: {TalkSessionState.PROCESSING},
    TalkSessionState.PROCESSING: {
        TalkSessionState.READY,
        TalkSessionState.NEEDS_ATTENTION,
    },
    TalkSessionState.NEEDS_ATTENTION: {TalkSessionState.PROCESSING},
    TalkSessionState.READY: set(),
}


def test_talk_session_transition_matrix_is_closed_and_exhaustive() -> None:
    for current, expected_targets in EXPECTED_SESSION_TRANSITIONS.items():
        assert allowed_session_targets(current) == frozenset(expected_targets)
        for target in ALL_SESSION_STATES:
            if target in expected_targets:
                assert_session_transition(current, target)
            else:
                with pytest.raises(SessionStateError):
                    assert_session_transition(current, target)


def test_only_open_sessions_accept_submit_replace_or_close_preconditions() -> None:
    require_open_session(TalkSessionState.OPEN)
    for state in ALL_SESSION_STATES:
        if state is TalkSessionState.OPEN:
            continue
        with pytest.raises(SessionStateError):
            require_open_session(state)


def test_host_policy_checks_membership_before_host_role() -> None:
    with pytest.raises(ActorNotMemberError):
        assert_host_actor("host", "host", ["member"])

    with pytest.raises(HostAuthorizationError):
        assert_host_actor("member", "host", ["host", "member"])

    assert_host_actor("host", "host", ["host", "member"])


def test_close_eligibility_exhaustively_requires_exclusions_for_every_unready_revision() -> None:
    states = tuple(RevisionProcessingState)
    for alpha_state, beta_state, excluded_ids in product(
        states,
        states,
        (frozenset(), frozenset({"alpha"}), frozenset({"beta"}), frozenset({"alpha", "beta"})),
    ):
        revisions = (
            RevisionStatus("beta", beta_state),
            RevisionStatus("alpha", alpha_state),
        )
        exclusions = tuple(
            CloseExclusion(revision_id, "host chose this snapshot scope")
            for revision_id in sorted(excluded_ids)
        )
        decision = evaluate_close_eligibility(revisions, exclusions)

        state_by_id = {"alpha": alpha_state, "beta": beta_state}
        expected_blocking = tuple(
            revision_id
            for revision_id in ("alpha", "beta")
            if state_by_id[revision_id] is not RevisionProcessingState.READY
            and revision_id not in excluded_ids
        )
        expected_included = tuple(
            revision_id
            for revision_id in ("alpha", "beta")
            if state_by_id[revision_id] is RevisionProcessingState.READY
            and revision_id not in excluded_ids
        )

        assert decision.blocking_revision_ids == expected_blocking
        assert decision.included_revision_ids == expected_included
        assert decision.excluded_revision_ids == tuple(sorted(excluded_ids))
        assert decision.eligible is (not expected_blocking)


def test_close_eligibility_records_explicit_ready_exclusions_and_rejects_bad_audit_inputs() -> None:
    ready = RevisionStatus("ready", RevisionProcessingState.READY)
    failed = RevisionStatus("failed", RevisionProcessingState.FAILED)
    decision = require_close_eligibility(
        (ready, failed),
        (
            CloseExclusion("ready", "host narrowed the snapshot"),
            CloseExclusion("failed", "parser failure is explicitly excluded"),
        ),
    )
    assert decision.included_revision_ids == ()
    assert decision.excluded_revision_ids == ("failed", "ready")

    with pytest.raises(CloseBlockedError) as blocked:
        require_close_eligibility((ready, failed), ())
    assert blocked.value.blocking_revision_ids == ("failed",)

    with pytest.raises(DomainInvariantError, match="current revisions"):
        evaluate_close_eligibility((ready,), (CloseExclusion("stale", "old revision"),))
    with pytest.raises(DomainInvariantError, match="duplicate current revision"):
        evaluate_close_eligibility((ready, ready), ())
    with pytest.raises(DomainInvariantError, match="duplicate close exclusion"):
        evaluate_close_eligibility(
            (ready,),
            (CloseExclusion("ready", "first"), CloseExclusion("ready", "second")),
        )
    with pytest.raises(DomainInvariantError, match="must not be blank"):
        CloseExclusion("ready", " \t")


def test_generation_aggregate_combination_table_is_exhaustive() -> None:
    for summary_state, research_state in product(GenerationRunState, repeat=2):
        runs = (
            GenerationRunView(GenerationKind.SUMMARY, summary_state),
            GenerationRunView(GenerationKind.RESEARCH, research_state),
        )
        projection = project_generation_aggregate(runs)

        if (
            summary_state is GenerationRunState.SUCCEEDED
            and research_state is GenerationRunState.SUCCEEDED
        ):
            assert projection.state is TalkSessionState.READY
            assert projection.reasons == ()
            assert projection.retry_available is False
            assert projection.action is AggregateAction.NONE
        elif summary_state.is_active or research_state.is_active:
            assert projection.state is TalkSessionState.PROCESSING
            assert projection.reasons == ()
            assert projection.retry_available is False
            assert projection.action is AggregateAction.NONE
        else:
            failed = (
                (GenerationKind.SUMMARY, summary_state),
                (GenerationKind.RESEARCH, research_state),
            )
            expected_codes = tuple(
                f"{kind.value}_{state.value}"
                for kind, state in failed
                if state.is_failure
            )
            expected_retry = any(
                state is GenerationRunState.FAILED_RETRYABLE
                for _, state in failed
            )
            assert projection.state is TalkSessionState.NEEDS_ATTENTION
            assert tuple(reason.code for reason in projection.reasons) == expected_codes
            assert tuple(reason.retryable for reason in projection.reasons) == tuple(
                state is GenerationRunState.FAILED_RETRYABLE
                for _, state in failed
                if state.is_failure
            )
            assert projection.retry_available is expected_retry
            assert projection.action is (
                AggregateAction.RETRY
                if expected_retry
                else AggregateAction.OPERATOR_OR_REPLAN
            )


def test_generation_aggregate_preserves_failure_codes_and_detects_missing_or_duplicate_runs() -> None:
    failed = project_generation_aggregate(
        (
            GenerationRunView(
                GenerationKind.SUMMARY,
                GenerationRunState.FAILED_RETRYABLE,
                error_code="provider_timeout",
            ),
            GenerationRunView(
                GenerationKind.RESEARCH,
                GenerationRunState.FAILED_TERMINAL,
                error_code="schema_rejected",
            ),
        )
    )
    assert [(reason.code, reason.kind, reason.retryable) for reason in failed.reasons] == [
        ("provider_timeout", GenerationKind.SUMMARY, True),
        ("schema_rejected", GenerationKind.RESEARCH, False),
    ]
    assert failed.retry_available is True

    missing = project_generation_aggregate(())
    assert missing.state is TalkSessionState.NEEDS_ATTENTION
    assert [(reason.code, reason.kind, reason.retryable) for reason in missing.reasons] == [
        ("invariant_error_missing_run", GenerationKind.SUMMARY, False),
        ("invariant_error_missing_run", GenerationKind.RESEARCH, False),
    ]
    assert missing.action is AggregateAction.OPERATOR_OR_REPLAN

    duplicate = project_generation_aggregate(
        (
            GenerationRunView(GenerationKind.SUMMARY, GenerationRunState.SUCCEEDED),
            GenerationRunView(GenerationKind.SUMMARY, GenerationRunState.SUCCEEDED),
        )
    )
    assert [(reason.code, reason.kind) for reason in duplicate.reasons] == [
        ("invariant_error_duplicate_run", GenerationKind.SUMMARY),
        ("invariant_error_missing_run", GenerationKind.RESEARCH),
    ]


NOW = datetime(2026, 7, 18, 2, 30, tzinfo=timezone.utc)
LEASE_DURATION = timedelta(seconds=30)


def test_claim_intent_supports_pending_and_expired_running_but_not_live_running() -> None:
    pending = JobLeaseView("job-1", JobState.PENDING, 0, None, None)
    initial = build_claim_intent(
        pending,
        owner_id="worker-a",
        new_lease_token="token-1",
        database_now=NOW,
        lease_duration=LEASE_DURATION,
    )
    assert initial.expected_state is JobState.PENDING
    assert initial.expected_lease_generation == 0
    assert initial.lease_generation == 1
    assert initial.reclaimed_expired_lease is False
    assert initial.lease_until == NOW + LEASE_DURATION

    expired = JobLeaseView(
        "job-1",
        JobState.RUNNING,
        1,
        "token-1",
        NOW - timedelta(microseconds=1),
    )
    reclaimed = build_claim_intent(
        expired,
        owner_id="worker-b",
        new_lease_token="token-2",
        database_now=NOW,
        lease_duration=LEASE_DURATION,
    )
    assert reclaimed.expected_lease_token == "token-1"
    assert reclaimed.lease_generation == 2
    assert reclaimed.reclaimed_expired_lease is True

    live = JobLeaseView(
        "job-1",
        JobState.RUNNING,
        1,
        "token-1",
        NOW + timedelta(microseconds=1),
    )
    with pytest.raises(JobNotClaimableError):
        build_claim_intent(
            live,
            owner_id="worker-b",
            new_lease_token="token-2",
            database_now=NOW,
            lease_duration=LEASE_DURATION,
        )


def test_lease_intents_reject_stale_worker_and_keep_completion_targets_closed() -> None:
    current = JobLeaseView(
        "job-2",
        JobState.RUNNING,
        2,
        "current-token",
        NOW + LEASE_DURATION,
    )
    heartbeat = build_heartbeat_intent(
        current,
        lease_generation=2,
        lease_token="current-token",
        database_now=NOW,
        lease_duration=LEASE_DURATION,
    )
    assert heartbeat.lease_until == NOW + LEASE_DURATION
    completion = build_completion_intent(
        current,
        lease_generation=2,
        lease_token="current-token",
        target_state=JobState.SUCCEEDED,
    )
    assert completion.target_state is JobState.SUCCEEDED

    for stale_generation, stale_token in ((1, "current-token"), (2, "old-token")):
        with pytest.raises(StaleLeaseError):
            build_completion_intent(
                current,
                lease_generation=stale_generation,
                lease_token=stale_token,
                target_state=JobState.SUCCEEDED,
            )

    with pytest.raises(DomainInvariantError, match="completion target"):
        build_completion_intent(
            current,
            lease_generation=2,
            lease_token="current-token",
            target_state=JobState.PENDING,
        )

    retryable = JobLeaseView("job-3", JobState.FAILED_RETRYABLE, 4, None, None)
    assert build_requeue_intent(retryable).expected_lease_generation == 4
    with pytest.raises(DomainInvariantError, match="failed_retryable"):
        build_requeue_intent(
            JobLeaseView("job-3", JobState.FAILED_TERMINAL, 4, None, None)
        )


def test_lease_intents_require_database_clock_and_positive_duration() -> None:
    pending = JobLeaseView("job-4", JobState.PENDING, 0, None, None)
    with pytest.raises(DomainInvariantError, match="timezone-aware"):
        build_claim_intent(
            pending,
            owner_id="worker-a",
            new_lease_token="token",
            database_now=NOW.replace(tzinfo=None),
            lease_duration=LEASE_DURATION,
        )
    with pytest.raises(DomainInvariantError, match="positive"):
        build_claim_intent(
            pending,
            owner_id="worker-a",
            new_lease_token="token",
            database_now=NOW,
            lease_duration=timedelta(0),
        )
