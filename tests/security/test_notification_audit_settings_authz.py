"""Security/privacy contract for the new private activity surfaces."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from app.contracts import contract_app


pytestmark = pytest.mark.security
ROOT = Path(__file__).resolve().parents[2]


def _activity_policy() -> ModuleType:
    spec = importlib.util.find_spec("app.activity_policy")
    if spec is None:
        pytest.fail("G001 RED: app.activity_policy redaction guard is absent")
    return importlib.import_module("app.activity_policy")


def test_private_activity_routes_never_accept_a_target_user_id() -> None:
    paths = contract_app.openapi()["paths"]
    expected_paths = {
        "/api/notifications",
        "/api/notifications/{notification_id}/read",
        "/api/notifications/read-all",
        "/api/me/email-outbox",
        "/api/me/preferences",
        "/api/me/profile",
    }
    missing = sorted(expected_paths - set(paths))
    assert not missing, f"G001 RED: private activity routes are absent: {missing}"
    for path in expected_paths:
        assert "user_id" not in path
        for operation in paths[path].values():
            parameters = operation.get("parameters", [])
            assert not any(parameter.get("name") == "user_id" for parameter in parameters)


def test_redaction_rejects_nested_secrets_and_raw_user_content() -> None:
    activity_policy = _activity_policy()
    payload = {
        "actor_id": "safe",
        "nested": {
            "cookie": "session-secret",
            "comment_body": "<script>alert(1)</script>",
            "email": "alice@example.test",
        },
    }
    with pytest.raises(ValueError):
        activity_policy.safe_audit_metadata(payload)


def test_email_intent_implementation_has_no_external_sender_dependency() -> None:
    candidate_files = [
        ROOT / "apps" / "api" / "app" / "activity_service.py",
        ROOT / "apps" / "api" / "app" / "notification_service.py",
    ]
    existing = [path for path in candidate_files if path.is_file()]
    assert existing, "G001 RED: local email-intent service is absent"
    source = "\n".join(path.read_text(encoding="utf-8") for path in existing)
    forbidden_dependencies = ("smtplib", "SMTP(", "httpx", "requests", "aiohttp")
    assert not any(name in source for name in forbidden_dependencies)
