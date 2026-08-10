"""Browser-facing read contracts needed by the meeting workspace.

These tests intentionally drive the FastAPI adapter with distinct cookie jars.
That prevents a privileged client's cookies from hiding membership or IDOR
regressions in the read endpoints.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.main import app
from app.migrations import upgrade_database


pytestmark = pytest.mark.integration

_ORIGIN = "http://localhost:3000"
_HOST = "localhost:3000"


@contextmanager
def _temporary_database() -> Iterator[str]:
    configured_url = os.environ.get("AXIT_TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("AXIT_TEST_DATABASE_URL is required for workspace API integration")
    database_name = "axit_workspace_api_" + uuid4().hex
    maintenance_url = make_conninfo(configured_url, dbname="postgres")
    target_url = make_conninfo(configured_url, dbname=database_name)
    with psycopg.connect(maintenance_url, autocommit=True) as maintenance:
        maintenance.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )
        try:
            yield target_url
        finally:
            maintenance.execute(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            maintenance.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    sql.Identifier(database_name)
                )
            )


@pytest.fixture
def workspace_database_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    with _temporary_database() as database_url:
        upgrade_database(database_url)
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("PUBLIC_ORIGIN", _ORIGIN)
        monkeypatch.setenv("PUBLIC_HOST", _HOST)
        monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
        yield database_url


def _read_headers() -> dict[str, str]:
    return {"X-AXit-Original-Host": _HOST}


def _pre_auth_headers() -> dict[str, str]:
    return {**_read_headers(), "Origin": _ORIGIN}


def _mutation_headers(csrf_token: str) -> dict[str, str]:
    return {**_pre_auth_headers(), "X-CSRF-Token": csrf_token}


def _register_and_login(
    client: TestClient,
    *,
    email: str,
    display_name: str,
) -> tuple[dict[str, object], str]:
    password = f"{display_name.lower()}-local-password"
    registered = client.post(
        "/api/auth/register",
        headers=_pre_auth_headers(),
        json={"email": email, "password": password, "display_name": display_name},
    )
    assert registered.status_code == 201, registered.text
    login = client.post(
        "/api/auth/login",
        headers=_pre_auth_headers(),
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    csrf = client.get("/api/csrf", headers=_read_headers())
    assert csrf.status_code == 200, csrf.text
    return registered.json(), str(csrf.json()["csrf_token"])


def _accept_friendship(
    requester_client: TestClient,
    requester_csrf: str,
    addressee_client: TestClient,
    addressee_csrf: str,
    *,
    addressee_id: object,
) -> str:
    created = requester_client.post(
        "/api/friend-requests",
        headers=_mutation_headers(requester_csrf),
        json={"addressee_id": addressee_id},
    )
    assert created.status_code == 201, created.text
    request_id = str(created.json()["id"])
    accepted = addressee_client.post(
        f"/api/friend-requests/{request_id}/accept",
        headers=_mutation_headers(addressee_csrf),
    )
    assert accepted.status_code == 200, accepted.text
    return request_id


def _create_shared_room(
    alice_client: TestClient,
    alice_csrf: str,
    bob_client: TestClient,
    bob_csrf: str,
    *,
    bob_id: object,
) -> str:
    _accept_friendship(
        alice_client,
        alice_csrf,
        bob_client,
        bob_csrf,
        addressee_id=bob_id,
    )
    room = alice_client.post(
        "/api/rooms",
        headers=_mutation_headers(alice_csrf),
        json={"name": "Frontend workspace"},
    )
    assert room.status_code == 201, room.text
    room_id = str(room.json()["id"])
    invitation = alice_client.post(
        f"/api/rooms/{room_id}/invitations",
        headers=_mutation_headers(alice_csrf),
        json={"invitee_id": bob_id},
    )
    assert invitation.status_code == 201, invitation.text
    return room_id


def _assert_hidden_resource(response: object) -> None:
    assert hasattr(response, "status_code")
    assert getattr(response, "status_code") == 404
    body = getattr(response, "json")()
    assert set(body) == {"code", "detail"}
    assert isinstance(body["code"], str) and body["code"]
    assert isinstance(body["detail"], str) and body["detail"]


def test_list_friend_requests_returns_only_requests_involving_the_actor(
    workspace_database_url: str,
) -> None:
    with (
        TestClient(app, base_url=_ORIGIN) as alice_client,
        TestClient(app, base_url=_ORIGIN) as bob_client,
        TestClient(app, base_url=_ORIGIN) as eve_client,
        TestClient(app, base_url=_ORIGIN) as mallory_client,
    ):
        alice, alice_csrf = _register_and_login(
            alice_client, email="alice@example.test", display_name="Alice"
        )
        bob, _ = _register_and_login(
            bob_client, email="bob@example.test", display_name="Bob"
        )
        eve, eve_csrf = _register_and_login(
            eve_client, email="eve@example.test", display_name="Eve"
        )
        mallory, _ = _register_and_login(
            mallory_client, email="mallory@example.test", display_name="Mallory"
        )

        actor_request = alice_client.post(
            "/api/friend-requests",
            headers=_mutation_headers(alice_csrf),
            json={"addressee_id": bob["id"]},
        )
        assert actor_request.status_code == 201, actor_request.text
        unrelated_request = eve_client.post(
            "/api/friend-requests",
            headers=_mutation_headers(eve_csrf),
            json={"addressee_id": mallory["id"]},
        )
        assert unrelated_request.status_code == 201, unrelated_request.text

        response = alice_client.get("/api/friend-requests", headers=_read_headers())

        assert response.status_code == 200, response.text
        requests = response.json()
        assert [item["id"] for item in requests] == [actor_request.json()["id"]]
        assert requests[0]["requester"]["id"] == alice["id"]
        assert requests[0]["addressee"]["id"] == bob["id"]
        assert unrelated_request.json()["id"] not in {item["id"] for item in requests}


def test_list_room_members_returns_roles_only_to_current_members(
    workspace_database_url: str,
) -> None:
    with (
        TestClient(app, base_url=_ORIGIN) as alice_client,
        TestClient(app, base_url=_ORIGIN) as bob_client,
        TestClient(app, base_url=_ORIGIN) as eve_client,
    ):
        alice, alice_csrf = _register_and_login(
            alice_client, email="alice@example.test", display_name="Alice"
        )
        bob, bob_csrf = _register_and_login(
            bob_client, email="bob@example.test", display_name="Bob"
        )
        _register_and_login(eve_client, email="eve@example.test", display_name="Eve")
        room_id = _create_shared_room(
            alice_client,
            alice_csrf,
            bob_client,
            bob_csrf,
            bob_id=bob["id"],
        )

        response = bob_client.get(
            f"/api/rooms/{room_id}/members", headers=_read_headers()
        )

        assert response.status_code == 200, response.text
        members_by_id = {item["user"]["id"]: item for item in response.json()}
        assert members_by_id[alice["id"]]["role"] == "host"
        assert members_by_id[alice["id"]]["user"]["display_name"] == "Alice"
        assert members_by_id[bob["id"]]["role"] == "member"
        assert members_by_id[bob["id"]]["user"]["display_name"] == "Bob"
        _assert_hidden_resource(
            eve_client.get(f"/api/rooms/{room_id}/members", headers=_read_headers())
        )


def test_list_room_sessions_returns_sessions_only_to_current_members(
    workspace_database_url: str,
) -> None:
    with (
        TestClient(app, base_url=_ORIGIN) as alice_client,
        TestClient(app, base_url=_ORIGIN) as bob_client,
        TestClient(app, base_url=_ORIGIN) as eve_client,
    ):
        _, alice_csrf = _register_and_login(
            alice_client, email="alice@example.test", display_name="Alice"
        )
        bob, bob_csrf = _register_and_login(
            bob_client, email="bob@example.test", display_name="Bob"
        )
        _register_and_login(eve_client, email="eve@example.test", display_name="Eve")
        room_id = _create_shared_room(
            alice_client,
            alice_csrf,
            bob_client,
            bob_csrf,
            bob_id=bob["id"],
        )
        created_sessions = []
        for topic in ("First agenda", "Second agenda"):
            created = alice_client.post(
                f"/api/rooms/{room_id}/sessions",
                headers=_mutation_headers(alice_csrf),
                json={"topic": topic, "description": "Workspace listing fixture"},
            )
            assert created.status_code == 201, created.text
            created_sessions.append(created.json())

        response = bob_client.get(
            f"/api/rooms/{room_id}/sessions", headers=_read_headers()
        )

        assert response.status_code == 200, response.text
        assert response.json() == created_sessions
        _assert_hidden_resource(
            eve_client.get(f"/api/rooms/{room_id}/sessions", headers=_read_headers())
        )


def test_archive_project_is_host_only_and_hides_the_session_from_members(
    workspace_database_url: str,
) -> None:
    with (
        TestClient(app, base_url=_ORIGIN) as alice_client,
        TestClient(app, base_url=_ORIGIN) as bob_client,
    ):
        _, alice_csrf = _register_and_login(
            alice_client, email="alice@example.test", display_name="Alice"
        )
        bob, bob_csrf = _register_and_login(
            bob_client, email="bob@example.test", display_name="Bob"
        )
        room_id = _create_shared_room(
            alice_client,
            alice_csrf,
            bob_client,
            bob_csrf,
            bob_id=bob["id"],
        )
        created = alice_client.post(
            f"/api/rooms/{room_id}/sessions",
            headers=_mutation_headers(alice_csrf),
            json={"topic": "Archive me", "description": "Project removal fixture"},
        )
        assert created.status_code == 201, created.text
        session_id = str(created.json()["id"])

        denied = bob_client.delete(
            f"/api/sessions/{session_id}", headers=_mutation_headers(bob_csrf)
        )
        assert denied.status_code == 403, denied.text

        archived = alice_client.delete(
            f"/api/sessions/{session_id}", headers=_mutation_headers(alice_csrf)
        )
        assert archived.status_code == 204, archived.text
        assert (
            alice_client.get(
                f"/api/rooms/{room_id}/sessions", headers=_read_headers()
            ).json()
            == []
        )
        assert (
            bob_client.get(
                f"/api/rooms/{room_id}/sessions", headers=_read_headers()
            ).json()
            == []
        )
        _assert_hidden_resource(
            alice_client.get(f"/api/sessions/{session_id}", headers=_read_headers())
        )


def test_participant_can_leave_a_project_room_but_host_cannot(
    workspace_database_url: str,
) -> None:
    with (
        TestClient(app, base_url=_ORIGIN) as alice_client,
        TestClient(app, base_url=_ORIGIN) as bob_client,
    ):
        _, alice_csrf = _register_and_login(
            alice_client, email="alice@example.test", display_name="Alice"
        )
        bob, bob_csrf = _register_and_login(
            bob_client, email="bob@example.test", display_name="Bob"
        )
        room_id = _create_shared_room(
            alice_client,
            alice_csrf,
            bob_client,
            bob_csrf,
            bob_id=bob["id"],
        )

        host_denied = alice_client.delete(
            f"/api/rooms/{room_id}/membership",
            headers=_mutation_headers(alice_csrf),
        )
        assert host_denied.status_code == 403, host_denied.text

        left = bob_client.delete(
            f"/api/rooms/{room_id}/membership",
            headers=_mutation_headers(bob_csrf),
        )
        assert left.status_code == 204, left.text
        assert bob_client.get("/api/rooms", headers=_read_headers()).json() == []
        _assert_hidden_resource(
            bob_client.get(f"/api/rooms/{room_id}/sessions", headers=_read_headers())
        )
        assert (
            alice_client.get("/api/rooms", headers=_read_headers()).json()[0]["id"]
            == room_id
        )


def test_list_session_submissions_returns_current_revision_metadata_and_author(
    workspace_database_url: str,
) -> None:
    with (
        TestClient(app, base_url=_ORIGIN) as alice_client,
        TestClient(app, base_url=_ORIGIN) as bob_client,
        TestClient(app, base_url=_ORIGIN) as eve_client,
    ):
        alice, alice_csrf = _register_and_login(
            alice_client, email="alice@example.test", display_name="Alice"
        )
        bob, bob_csrf = _register_and_login(
            bob_client, email="bob@example.test", display_name="Bob"
        )
        _register_and_login(eve_client, email="eve@example.test", display_name="Eve")
        room_id = _create_shared_room(
            alice_client,
            alice_csrf,
            bob_client,
            bob_csrf,
            bob_id=bob["id"],
        )
        session = alice_client.post(
            f"/api/rooms/{room_id}/sessions",
            headers=_mutation_headers(alice_csrf),
            json={"topic": "Submission list", "description": "Current revisions only"},
        )
        assert session.status_code == 201, session.text
        session_id = str(session.json()["id"])
        alice_submission = alice_client.post(
            f"/api/sessions/{session_id}/submissions/text",
            headers=_mutation_headers(alice_csrf),
            json={"title": "Alice 준비 자료", "text": "Alice: superseded source"},
        )
        assert alice_submission.status_code == 201, alice_submission.text
        old_revision_id = alice_submission.json()["current_revision_id"]
        replaced = alice_client.put(
            f"/api/submissions/{alice_submission.json()['id']}",
            headers=_mutation_headers(alice_csrf),
            json={"text": "Alice: current source"},
        )
        assert replaced.status_code == 200, replaced.text
        bob_submission = bob_client.post(
            f"/api/sessions/{session_id}/submissions/text",
            headers=_mutation_headers(bob_csrf),
            json={"text": "Bob: current source"},
        )
        assert bob_submission.status_code == 201, bob_submission.text

        response = bob_client.get(
            f"/api/sessions/{session_id}/submissions", headers=_read_headers()
        )

        assert response.status_code == 200, response.text
        submissions_by_id = {item["id"]: item for item in response.json()}
        assert set(submissions_by_id) == {
            alice_submission.json()["id"],
            bob_submission.json()["id"],
        }
        alice_item = submissions_by_id[alice_submission.json()["id"]]
        assert set(alice_item) == {
            "id",
            "session_id",
            "author_id",
            "kind",
            "title",
            "current_revision_id",
            "processing_state",
            "filename",
            "mime_type",
            "byte_size",
            "author",
            "created_at",
        }
        assert alice_item["title"] == "Alice 준비 자료"
        assert datetime.fromisoformat(alice_item["created_at"]).tzinfo is not None
        assert set(alice_item["author"]) == {"id", "email", "display_name"}
        serialized = response.text.lower()
        for forbidden_field in (
            "source_text",
            "source_sha256",
            "storage_key",
            "extraction_profile_hash",
            "text_fingerprint",
        ):
            assert forbidden_field not in serialized
        assert (
            alice_item["current_revision_id"] == replaced.json()["current_revision_id"]
        )
        assert alice_item["current_revision_id"] != old_revision_id
        assert (
            alice_item["filename"]
            == f"text-submission-{alice_submission.json()['id']}.txt"
        )
        assert alice_item["mime_type"] == "text/plain"
        assert alice_item["byte_size"] == len("Alice: current source".encode("utf-8"))
        assert alice_item["author"]["id"] == alice["id"]
        assert alice_item["author"]["display_name"] == "Alice"
        assert bob_submission.json()["current_revision_id"] in {
            item["current_revision_id"] for item in response.json()
        }
        assert old_revision_id not in {
            item["current_revision_id"] for item in response.json()
        }
        _assert_hidden_resource(
            eve_client.get(
                f"/api/sessions/{session_id}/submissions", headers=_read_headers()
            )
        )
