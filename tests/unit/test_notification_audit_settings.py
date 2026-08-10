"""Pure policy contract for notification, audit, and settings activity.

These tests intentionally precede ``app.activity_policy``.  They must fail with
an explicit missing-policy assertion until the implementation lane supplies the
small pure API frozen below; collection itself must remain healthy.
"""

from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType
from uuid import UUID

import pytest

from app.contracts import contract_app


EXPECTED_EVENT_TYPES = frozenset(
    {
        "account.registered",
        "profile.updated",
        "notification_preferences.updated",
        "friendship.requested",
        "friendship.accepted",
        "friendship.rejected",
        "room.created",
        "room.member_added",
        "room.member_left",
        "session.created",
        "session.closed",
        "session.retry_requested",
        "session.processing",
        "session.ready",
        "session.needs_attention",
        "session.reopened",
        "session.archived",
        "submission.created",
        "submission.revised",
        "submission.deleted",
        "source_revision.ready",
        "source_revision.failed",
        "source_revision.retry_requested",
        "suggestion.created",
        "suggestion.accepted",
        "suggestion.rejected",
        "comment.created",
        "comment.updated",
        "comment.deleted",
        "merged_document.saved",
        "merged_document.version_created",
    }
)

EXPECTED_INFRASTRUCTURE_EXCEPTIONS = frozenset(
    {
        "login",
        "logout",
        "csrf.issue",
        "readNotification",
        "readAllNotifications",
        "audit.read",
        "email_outbox.insert",
        "job.claim",
        "job.lease",
        "job.heartbeat",
        "suggestProjectDescriptions",
    }
)

EXPECTED_MUTATION_SEAMS = frozenset(
    {
        "register",
        "login",
        "logout",
        "createFriendRequest",
        "acceptFriendRequest",
        "rejectFriendRequest",
        "createRoom",
        "createRoomInvitation",
        "createTalkSession",
        "leaveRoom",
        "archiveTalkSession",
        "submitText",
        "submitFile",
        "replaceTextSubmission",
        "deleteSubmission",
        "retryExtraction",
        "closeSession",
        "reopenSession",
        "retrySession",
        "createReportSuggestion",
        "resolveReportSuggestion",
        "updateProfile",
        "updateNotificationPreferences",
        "readNotification",
        "readAllNotifications",
        "createComment",
        "updateComment",
        "deleteComment",
        "saveMergedDocument",
        "createMergedDocumentVersion",
        "generation.complete",
        "extraction.terminal",
        "extraction.reconcile",
        "suggestion.automatic_create",
        "suggestProjectDescriptions",
    }
)


def _activity_policy() -> ModuleType:
    spec = importlib.util.find_spec("app.activity_policy")
    if spec is None:
        pytest.fail(
            "G001 RED: app.activity_policy is absent; implement the approved pure policy "
            "before wiring persistence or routes"
        )
    return importlib.import_module("app.activity_policy")


def test_registry_covers_every_supported_event_and_mutation_seam() -> None:
    activity_policy = _activity_policy()
    assert frozenset(activity_policy.SUPPORTED_AUDIT_EVENT_TYPES) == EXPECTED_EVENT_TYPES
    assert (
        frozenset(activity_policy.INFRASTRUCTURE_AUDIT_EXCEPTIONS)
        == EXPECTED_INFRASTRUCTURE_EXCEPTIONS
    )
    classifications = activity_policy.MUTATION_SEAM_CLASSIFICATIONS
    assert frozenset(classifications) == EXPECTED_MUTATION_SEAMS
    state_changing_operations = {
        operation["operationId"]
        for path_item in contract_app.openapi()["paths"].values()
        for method, operation in path_item.items()
        if method in {"post", "put", "patch", "delete"}
    }
    assert state_changing_operations <= set(classifications), (
        "every state-changing OpenAPI operation must be audited or an explicit "
        "infrastructure exception"
    )
    assert all(
        classification in EXPECTED_EVENT_TYPES
        or classification in EXPECTED_INFRASTRUCTURE_EXCEPTIONS
        or (
            isinstance(classification, tuple)
            and classification
            and set(classification) <= EXPECTED_EVENT_TYPES
        )
        for classification in classifications.values()
    )


@pytest.mark.parametrize(
    ("event_type", "identity", "expected"),
    [
        (
            "account.registered",
            {"user_id": "00000000-0000-0000-0000-000000000001"},
            "account:00000000-0000-0000-0000-000000000001:registered",
        ),
        (
            "friendship.accepted",
            {
                "friendship_id": "00000000-0000-0000-0000-000000000002",
                "audience_user_id": "00000000-0000-0000-0000-000000000003",
            },
            "friendship:00000000-0000-0000-0000-000000000002:accepted:aud:"
            "00000000-0000-0000-0000-000000000003",
        ),
        (
            "session.ready",
            {
                "session_id": "00000000-0000-0000-0000-000000000004",
                "state_version": 9,
            },
            "session:00000000-0000-0000-0000-000000000004:state-v9:ready",
        ),
        (
            "comment.updated",
            {
                "comment_id": "00000000-0000-0000-0000-000000000005",
                "version": 2,
            },
            "comment:00000000-0000-0000-0000-000000000005:v2:updated",
        ),
        (
            "source_revision.failed",
            {
                "revision_id": "00000000-0000-0000-0000-000000000006",
                "job_id": "00000000-0000-0000-0000-000000000007",
                "reconciled": True,
            },
            "revision:00000000-0000-0000-0000-000000000006:reconcile:"
            "00000000-0000-0000-0000-000000000007:failed",
        ),
    ],
)
def test_event_keys_are_deterministic_catalog_identities(
    event_type: str,
    identity: dict[str, object],
    expected: str,
) -> None:
    activity_policy = _activity_policy()
    assert activity_policy.build_event_key(event_type, **identity) == expected
    assert activity_policy.build_event_key(event_type, **identity) == expected


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "password",
        "token",
        "cookie",
        "email",
        "comment_body",
        "source_text",
        "extracted_text",
        "storage_key",
        "provider_payload",
    ],
)
def test_audit_metadata_rejects_sensitive_or_raw_content_at_any_depth(
    forbidden_key: str,
) -> None:
    activity_policy = _activity_policy()
    with pytest.raises(ValueError, match="forbidden|sensitive|metadata"):
        activity_policy.safe_audit_metadata(
            {"entity_id": "safe-id", "nested": {forbidden_key: "must-not-persist"}}
        )


def test_comment_recipients_prioritize_mentions_without_duplicates_or_actor() -> None:
    activity_policy = _activity_policy()
    actor = UUID("00000000-0000-0000-0000-000000000001")
    alice = UUID("00000000-0000-0000-0000-000000000002")
    bob = UUID("00000000-0000-0000-0000-000000000003")
    carol = UUID("00000000-0000-0000-0000-000000000004")

    plan = activity_policy.plan_comment_recipients(
        actor_id=actor,
        member_ids=(actor, alice, bob, carol),
        mentioned_user_ids=(alice, alice, actor),
    )

    assert plan == {
        "mention": (alice,),
        "comment": (bob, carol),
    }


@pytest.mark.parametrize(
    ("previous", "projected", "lease_is_current", "expected"),
    [
        ("processing", "ready", True, True),
        ("ready", "ready", True, False),
        ("processing", "needs_attention", True, False),
        ("processing", "ready", False, False),
    ],
)
def test_analysis_completion_requires_a_first_fenced_ready_transition(
    previous: str,
    projected: str,
    lease_is_current: bool,
    expected: bool,
) -> None:
    activity_policy = _activity_policy()
    assert (
        activity_policy.transitioned_to_ready(
            previous_state=previous,
            projected_state=projected,
            lease_is_current=lease_is_current,
        )
        is expected
    )


def test_noop_mutations_never_materialize_audit_notification_or_outbox() -> None:
    activity_policy = _activity_policy()
    assert activity_policy.should_materialize(domain_changed=False) is False
    assert activity_policy.should_materialize(domain_changed=True) is True


def test_compound_close_and_retry_event_keys_preserve_append_order() -> None:
    activity_policy = _activity_policy()
    session_id = UUID("00000000-0000-0000-0000-000000000099")
    assert activity_policy.compound_session_event_keys(
        operation="close",
        session_id=session_id,
        generation_epoch=3,
        state_version=7,
        retry_ordinal=2,
    ) == (
        f"session:{session_id}:state-v8:closed",
        f"session:{session_id}:state-v9:processing",
    )
    assert activity_policy.compound_session_event_keys(
        operation="retry",
        session_id=session_id,
        generation_epoch=4,
        state_version=11,
        retry_ordinal=2,
    ) == (
        f"session:{session_id}:epoch:4:retry:3",
        f"session:{session_id}:state-v12:processing",
    )
