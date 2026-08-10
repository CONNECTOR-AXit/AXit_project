"""Pure, deterministic policy for durable product activity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID


SUPPORTED_AUDIT_EVENT_TYPES = frozenset(
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

INFRASTRUCTURE_AUDIT_EXCEPTIONS = frozenset(
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
        # Stateless AI suggestion fetch — nothing is persisted, so it is not a
        # durable domain event worth an activity/audit record.
        "suggestProjectDescriptions",
    }
)

MUTATION_SEAM_CLASSIFICATIONS: dict[str, str | tuple[str, ...]] = {
    "register": "account.registered",
    "login": "login",
    "logout": "logout",
    "createFriendRequest": "friendship.requested",
    "acceptFriendRequest": ("friendship.accepted", "room.member_added"),
    "rejectFriendRequest": "friendship.rejected",
    "createRoom": "room.created",
    "createRoomInvitation": "room.member_added",
    "createTalkSession": "session.created",
    "leaveRoom": "room.member_left",
    "archiveTalkSession": "session.archived",
    "submitText": "submission.created",
    "submitFile": "submission.created",
    "replaceTextSubmission": "submission.revised",
    "deleteSubmission": "submission.deleted",
    "retryExtraction": "source_revision.retry_requested",
    "closeSession": ("session.closed", "session.processing"),
    "reopenSession": "session.reopened",
    "retrySession": ("session.retry_requested", "session.processing"),
    "createReportSuggestion": "suggestion.created",
    "resolveReportSuggestion": ("suggestion.accepted", "suggestion.rejected"),
    "updateProfile": "profile.updated",
    "updateNotificationPreferences": "notification_preferences.updated",
    "readNotification": "readNotification",
    "readAllNotifications": "readAllNotifications",
    "createComment": "comment.created",
    "updateComment": "comment.updated",
    "deleteComment": "comment.deleted",
    "saveMergedDocument": "merged_document.saved",
    "createMergedDocumentVersion": "merged_document.version_created",
    "generation.complete": ("session.ready", "session.needs_attention"),
    "extraction.terminal": ("source_revision.ready", "source_revision.failed"),
    "extraction.reconcile": "source_revision.failed",
    "suggestion.automatic_create": "suggestion.created",
    "suggestProjectDescriptions": "suggestProjectDescriptions",
}

_FORBIDDEN_PARTS = (
    "password",
    "token",
    "cookie",
    "email",
    "comment_body",
    "source_text",
    "extracted_text",
    "storage_key",
    "provider_payload",
    "secret",
    "credential",
)


def safe_audit_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    """Copy bounded object metadata after recursively rejecting private content keys."""

    def validate(item: Any, path: str) -> Any:
        if isinstance(item, Mapping):
            result: dict[str, Any] = {}
            for raw_key, child in item.items():
                if not isinstance(raw_key, str):
                    raise ValueError("metadata keys must be strings")
                lowered = raw_key.lower()
                if any(part in lowered for part in _FORBIDDEN_PARTS):
                    raise ValueError(
                        f"forbidden sensitive metadata key: {path}{raw_key}"
                    )
                result[raw_key] = validate(child, f"{path}{raw_key}.")
            return result
        if isinstance(item, (list, tuple)):
            return [validate(child, path) for child in item]
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        if isinstance(item, UUID):
            return str(item)
        raise ValueError("metadata contains an unsupported value")

    result = validate(value, "")
    assert isinstance(result, dict)
    import json

    if (
        len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode())
        > 4096
    ):
        raise ValueError("metadata exceeds 4 KiB")
    return result


def build_event_key(event_type: str, **identity: object) -> str:
    if event_type not in SUPPORTED_AUDIT_EVENT_TYPES:
        raise ValueError("unsupported audit event type")

    def required(name: str) -> object:
        value = identity.get(name)
        if value is None:
            raise ValueError(f"missing event identity: {name}")
        return value

    if event_type == "account.registered":
        return f"account:{required('user_id')}:registered"
    if event_type == "profile.updated":
        return f"profile:{required('user_id')}:v{required('profile_version')}"
    if event_type == "notification_preferences.updated":
        return f"preferences:{required('user_id')}:v{required('preferences_version')}"
    if event_type.startswith("friendship."):
        state = event_type.rsplit(".", 1)[1]
        return f"friendship:{required('friendship_id')}:{state}:aud:{required('audience_user_id')}"
    if event_type == "room.created":
        return f"room:{required('room_id')}:created"
    if event_type == "room.member_added":
        return f"room:{required('room_id')}:member:{required('user_id')}:added"
    if event_type == "room.member_left":
        return f"room:{required('room_id')}:member:{required('user_id')}:left"
    if event_type == "session.created":
        return f"session:{required('session_id')}:created"
    if event_type == "session.archived":
        return f"session:{required('session_id')}:archived"
    if event_type == "session.retry_requested":
        return (
            f"session:{required('session_id')}:epoch:{required('generation_epoch')}:"
            f"retry:{required('retry_ordinal')}"
        )
    if event_type.startswith("session."):
        state = event_type.rsplit(".", 1)[1]
        return f"session:{required('session_id')}:state-v{required('state_version')}:{state}"
    if event_type == "submission.deleted":
        return f"submission:{required('submission_id')}:deleted"
    if event_type.startswith("submission."):
        state = event_type.rsplit(".", 1)[1]
        return f"submission:{required('submission_id')}:revision:{required('revision_no')}:{state}"
    if event_type == "source_revision.retry_requested":
        return f"revision:{required('revision_id')}:retry:{required('retry_nonce')}:requested"
    if event_type.startswith("source_revision."):
        state = event_type.rsplit(".", 1)[1]
        if identity.get("reconciled"):
            return f"revision:{required('revision_id')}:reconcile:{required('job_id')}:{state}"
        return f"revision:{required('revision_id')}:attempt:{required('job_attempt_id')}:{state}"
    if event_type == "suggestion.created":
        return f"suggestion:{required('suggestion_id')}:created"
    if event_type.startswith("suggestion."):
        state = event_type.rsplit(".", 1)[1]
        return f"suggestion:{required('suggestion_id')}:v{required('version')}:{state}"
    if event_type == "merged_document.saved":
        return (
            f"merged_document:{required('session_id')}:snapshot:{required('snapshot_id')}:"
            f"v{required('version')}:saved"
        )
    if event_type == "merged_document.version_created":
        return f"merged_document_version:{required('version_id')}:created"
    state = event_type.rsplit(".", 1)[1]
    return f"comment:{required('comment_id')}:v{required('version')}:{state}"


def plan_comment_recipients(
    *, actor_id: UUID, member_ids: Sequence[UUID], mentioned_user_ids: Sequence[UUID]
) -> dict[str, tuple[UUID, ...]]:
    members = set(member_ids)
    mentions = tuple(
        dict.fromkeys(
            user for user in mentioned_user_ids if user != actor_id and user in members
        )
    )
    mention_set = set(mentions)
    comments = tuple(
        dict.fromkeys(
            user for user in member_ids if user != actor_id and user not in mention_set
        )
    )
    return {"mention": mentions, "comment": comments}


def transitioned_to_ready(
    *, previous_state: str, projected_state: str, lease_is_current: bool
) -> bool:
    return lease_is_current and previous_state != "ready" and projected_state == "ready"


def should_materialize(*, domain_changed: bool) -> bool:
    return domain_changed


def compound_session_event_keys(
    *,
    operation: str,
    session_id: UUID,
    generation_epoch: int,
    state_version: int,
    retry_ordinal: int,
) -> tuple[str, str]:
    if operation == "close":
        return (
            f"session:{session_id}:state-v{state_version + 1}:closed",
            f"session:{session_id}:state-v{state_version + 2}:processing",
        )
    if operation == "retry":
        return (
            f"session:{session_id}:epoch:{generation_epoch}:retry:{retry_ordinal + 1}",
            f"session:{session_id}:state-v{state_version + 1}:processing",
        )
    raise ValueError("operation must be close or retry")
