"""Route-adapter tests for the G005 private activity API surface."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import Response
import pytest
from starlette.requests import Request

import app.contracts as contracts
from app.comments_service import CommentMutation
from app.api_errors import ApiProblem
from app.comments_service import CommentReplayConflictError
from app.profile_service import StaleProfileVersionError
from app.profile_repository import ProfileInvariantError
from app.notification_repository import TimePage
from app.notification_activity_routes import resolve_visible_comment_session


class _CursorContext:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *_args: object) -> None:
        return None


class _Connection:
    def cursor(self) -> _CursorContext:
        return _CursorContext()


@contextmanager
def _connection() -> object:
    yield _Connection()


def _request(method: str = "GET") -> Request:
    return Request({"type": "http", "method": method, "path": "/", "headers": []})


def _install_identity(monkeypatch: object, user_id: object) -> None:
    monkeypatch.setattr(contracts, "open_connection", _connection)  # type: ignore[attr-defined]
    authenticated = SimpleNamespace(user=SimpleNamespace(id=user_id))
    monkeypatch.setattr(contracts, "_authenticated_read", lambda *_: authenticated)  # type: ignore[attr-defined]
    monkeypatch.setattr(contracts, "_authenticated_mutation", lambda *_: authenticated)  # type: ignore[attr-defined]


def test_notification_list_uses_only_authenticated_recipient_and_computed_href(
    monkeypatch: object,
) -> None:
    user_id, notification_id, resource_id = uuid4(), uuid4(), uuid4()
    _install_identity(monkeypatch, user_id)

    class Service:
        def list_notifications(
            self, _cursor: object, **kwargs: object
        ) -> tuple[TimePage, int]:
            assert kwargs == {"recipient_id": user_id, "page_cursor": None, "limit": 25}
            item = {
                "id": notification_id,
                "kind": "friend_request",
                "actor_id": uuid4(),
                "resource_type": "friend_request",
                "resource_id": resource_id,
                "action_kind": "respond_friend_request",
                "href": "/friends",
                "title": "친구 요청",
                "body": "새 친구 요청이 있습니다.",
                "created_at": datetime.now(UTC),
                "read_at": None,
            }
            return TimePage((item,), None), 1

    monkeypatch.setattr(contracts, "_notification_service", Service())  # type: ignore[attr-defined]
    page = contracts.list_notifications_contract(_request(), page_cursor=None, limit=25)
    assert page.unread_count == 1
    assert page.items[0].href == "/friends"
    assert not hasattr(page.items[0], "recipient_id")


def test_comment_create_passes_explicit_uuid_mentions_and_authenticated_author(
    monkeypatch: object,
) -> None:
    user_id, session_id, mention_id, comment_id = uuid4(), uuid4(), uuid4(), uuid4()
    _install_identity(monkeypatch, user_id)

    class Service:
        def create(self, _cursor: object, **kwargs: object) -> CommentMutation:
            assert kwargs["author_id"] == user_id
            assert kwargs["session_id"] == session_id
            assert kwargs["mentioned_user_ids"] == (mention_id,)
            return CommentMutation(comment_id, 1, False)

    monkeypatch.setattr(contracts, "_comments_service", Service())  # type: ignore[attr-defined]
    response = Response()
    result = contracts.create_session_comment_contract(
        session_id,
        contracts.CommentCreateRequest(
            client_request_id=uuid4(), body="hello", mentioned_user_ids=[mention_id]
        ),
        _request("POST"),
        response,
    )
    assert result.id == comment_id and result.idempotent is False


def test_private_routes_have_no_target_user_parameter_and_mutations_are_not_get() -> (
    None
):
    paths = contracts.contract_app.openapi()["paths"]
    private_paths = (
        "/api/notifications",
        "/api/notifications/{notification_id}/read",
        "/api/notifications/read-all",
        "/api/me/email-outbox",
        "/api/me/profile",
        "/api/me/preferences",
    )
    for path in private_paths:
        for operation in paths[path].values():
            parameters = operation.get("parameters", [])
            assert all(parameter["name"] != "user_id" for parameter in parameters)
    assert "post" in paths["/api/notifications/read-all"]
    assert "put" in paths["/api/me/profile"]
    assert "put" in paths["/api/me/preferences"]
    schemas = contracts.contract_app.openapi()["components"]["schemas"]
    assert "session_id" not in schemas["CommentUpdateRequest"]["properties"]
    assert "session_id" not in schemas["CommentDeleteRequest"]["properties"]


def test_profile_update_contract_rejects_email_as_an_immutable_field() -> None:
    schema = contracts.contract_app.openapi()["components"]["schemas"][
        "ProfileUpdateRequest"
    ]
    assert "email" not in schema["properties"]
    assert schema["additionalProperties"] is False

    with pytest.raises(ValueError):
        contracts.ProfileUpdateRequest.model_validate(
            {
                "expected_version": 0,
                "display_name": "Alice",
                "language": "ko",
                "email": "new@example.invalid",
            }
        )


def test_profile_invariant_is_safe_500_while_resource_absence_remains_404() -> None:
    with pytest.raises(ApiProblem) as invariant:
        contracts._raise_service_problem(
            ProfileInvariantError("private persistence detail")
        )
    assert (
        invariant.value.status_code,
        invariant.value.code,
        invariant.value.detail,
    ) == (500, "internal_error", "service is temporarily unavailable")

    with pytest.raises(ApiProblem) as absent:
        contracts._raise_service_problem(LookupError("private resource detail"))
    assert (absent.value.status_code, absent.value.code) == (404, "not_found")


def test_comment_session_resolution_is_membership_constrained_and_concealed() -> None:
    comment_id, requester_id, session_id = uuid4(), uuid4(), uuid4()

    class Cursor:
        statement = ""
        parameters: tuple[object, ...] = ()

        def execute(self, statement: str, parameters: tuple[object, ...]) -> None:
            self.statement = statement
            self.parameters = parameters

        def fetchone(self) -> dict[str, object]:
            return {"session_id": session_id}

    cursor = Cursor()
    assert (
        resolve_visible_comment_session(  # type: ignore[arg-type]
            cursor, comment_id=comment_id, requester_id=requester_id
        )
        == session_id
    )
    assert "room_memberships" in cursor.statement
    assert "left_at IS NULL" in cursor.statement
    assert cursor.parameters == (requester_id, comment_id)


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (PermissionError("hidden resource"), 404, "not_found"),
        (LookupError("hidden profile"), 404, "not_found"),
        (StaleProfileVersionError("stale"), 409, "conflict"),
        (CommentReplayConflictError("replay"), 409, "conflict"),
        (ValueError("invalid cursor"), 422, "invalid_request"),
    ],
)
def test_g005_error_mapping_is_stable_and_non_disclosing(
    error: Exception, status_code: int, code: str
) -> None:
    with pytest.raises(ApiProblem) as captured:
        contracts._raise_service_problem(error)
    assert captured.value.status_code == status_code
    assert captured.value.code == code
    assert str(error) not in captured.value.detail
