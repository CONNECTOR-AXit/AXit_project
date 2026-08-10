"""Wire-contract freeze for notification, audit, comments, and settings."""

from __future__ import annotations

from app.contracts import contract_app


EXPECTED_METHODS_BY_PATH = {
    "/api/notifications": {"get"},
    "/api/notifications/{notification_id}/read": {"post"},
    "/api/notifications/read-all": {"post"},
    "/api/me/email-outbox": {"get"},
    "/api/me/preferences": {"get", "put"},
    "/api/me/profile": {"get", "put"},
    "/api/audit-events": {"get"},
    "/api/sessions/{session_id}/comments": {"get", "post"},
    "/api/comments/{comment_id}": {"put", "delete"},
}


def test_openapi_exposes_every_approved_notification_audit_settings_route() -> None:
    paths = contract_app.openapi()["paths"]
    missing = sorted(set(EXPECTED_METHODS_BY_PATH) - set(paths))
    assert not missing, f"G001 RED: approved API routes are absent: {missing}"
    for path, expected_methods in EXPECTED_METHODS_BY_PATH.items():
        assert expected_methods <= set(paths[path]), path


def test_notification_page_contract_owns_action_resource_href_and_unread_count() -> (
    None
):
    schemas = contract_app.openapi()["components"]["schemas"]
    assert "NotificationPageResponse" in schemas, (
        "G001 RED: NotificationPageResponse schema is absent"
    )
    page = schemas["NotificationPageResponse"]
    assert set(page["required"]) == {"items", "next_cursor", "unread_count"}

    item = schemas["NotificationResponse"]
    required = set(item["required"])
    assert {
        "id",
        "kind",
        "resource_type",
        "resource_id",
        "action_kind",
        "href",
        "title",
        "body",
        "created_at",
        "read_at",
    } <= required
    assert "href" not in schemas.get("NotificationCreateRequest", {}).get(
        "properties", {}
    )


def test_profile_preferences_audit_and_outbox_contracts_exclude_private_delivery_data() -> (
    None
):
    schemas = contract_app.openapi()["components"]["schemas"]
    assert {
        "ProfileResponse",
        "NotificationPreferencesResponse",
        "AuditEventPageResponse",
        "EmailOutboxPageResponse",
    } <= set(schemas), "G001 RED: approved response schemas are absent"

    profile = schemas["ProfileResponse"]
    assert {
        "user_id",
        "email",
        "display_name",
        "job_title",
        "language",
        "profile_version",
        "profile_updated_at",
    } <= set(profile["required"])

    audit_page = schemas["AuditEventPageResponse"]
    assert {"coverage_started_at", "items", "next_cursor"} == set(
        audit_page["required"]
    )
    audit_event = schemas["AuditEventResponse"]
    assert "actor_display_name" in audit_event["required"]
    assert {
        item.get("type")
        for item in audit_event["properties"]["actor_display_name"]["anyOf"]
    } == {
        "string",
        "null",
    }

    outbox = schemas["EmailOutboxResponse"]
    properties = set(outbox["properties"])
    assert "email" not in properties
    assert "delivered_at" not in properties
    assert outbox["properties"]["status"].get("const") == "queued_local"


def test_comment_create_contract_declares_created_and_idempotent_replay_responses() -> (
    None
):
    responses = contract_app.openapi()["paths"]["/api/sessions/{session_id}/comments"][
        "post"
    ]["responses"]
    assert {"200", "201"} <= set(responses)
    assert responses["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CommentMutationResponse"
    }


def test_profile_contract_declares_internal_invariant_failure_without_reclassifying_404s() -> (
    None
):
    paths = contract_app.openapi()["paths"]
    for path in ("/api/me/profile", "/api/me/preferences"):
        for method in ("get", "put"):
            responses = paths[path][method]["responses"]
            assert {"404", "500"} <= set(responses)
            assert responses["500"]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }
