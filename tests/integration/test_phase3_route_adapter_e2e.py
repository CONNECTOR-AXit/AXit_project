"""Cross-lane browser-facing proof of the Phase 3 FastAPI route adapter.

This test deliberately drives the public contract router rather than calling
the services directly.  It uses the same temporary PostgreSQL lifecycle as
the durable-core integration suite and runs the real fenced worker between
the close and result reads.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.db import open_connection
from app.generation_worker import FencedGenerationWorker
from app.main import app
from app.migrations import upgrade_database


pytestmark = pytest.mark.integration

_ORIGIN = "http://localhost:3000"
_HOST = "localhost:3000"


@contextmanager
def _temporary_database() -> Iterator[str]:
    configured_url = os.environ.get("AXIT_TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("AXIT_TEST_DATABASE_URL is required for route-adapter E2E")
    connection_info = conninfo_to_dict(configured_url)
    database_name = "axit_phase3_routes_" + uuid4().hex
    maintenance_info = dict(connection_info)
    maintenance_info["dbname"] = "postgres"
    target_info = dict(connection_info)
    target_info["dbname"] = database_name
    target_url = make_conninfo(**target_info)
    with psycopg.connect(**maintenance_info, autocommit=True) as maintenance:
        maintenance.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        try:
            yield target_url
        finally:
            maintenance.execute(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            maintenance.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))


@pytest.fixture
def route_adapter_database_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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


def _register(client: TestClient, *, email: str, display_name: str) -> dict[str, object]:
    response = client.post(
        "/api/auth/register",
        headers=_pre_auth_headers(),
        json={
            "email": email,
            "password": f"{display_name.lower()}-local-password",
            "display_name": display_name,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _login_and_csrf(client: TestClient, *, email: str, display_name: str) -> str:
    response = client.post(
        "/api/auth/login",
        headers=_pre_auth_headers(),
        json={"email": email, "password": f"{display_name.lower()}-local-password"},
    )
    assert response.status_code == 200, response.text
    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/" in set_cookie
    assert "Domain=" not in set_cookie
    csrf_response = client.get("/api/csrf", headers=_read_headers())
    assert csrf_response.status_code == 200, csrf_response.text
    return str(csrf_response.json()["csrf_token"])


def _mutation_headers(csrf_token: str) -> dict[str, str]:
    return {**_pre_auth_headers(), "X-CSRF-Token": csrf_token}


def _assert_bounded_error(response: object, *, status_code: int) -> None:
    # Keep the assertion intentionally independent of FastAPI's validation
    # internals: production route failures must always use ErrorResponse.
    assert hasattr(response, "status_code")
    assert getattr(response, "status_code") == status_code
    body = getattr(response, "json")()
    assert set(body) == {"code", "detail"}
    assert isinstance(body["code"], str) and body["code"]
    assert isinstance(body["detail"], str) and body["detail"]
    assert len(body["detail"]) <= 1_000


def test_public_route_adapter_completes_private_text_summary_flow(
    route_adapter_database_url: str,
) -> None:
    # Separate browser clients prevent a cookie jar from masking an IDOR bug.
    with (
        TestClient(app, base_url=_ORIGIN) as alice_client,
        TestClient(app, base_url=_ORIGIN) as bob_client,
        TestClient(app, base_url=_ORIGIN) as eve_client,
    ):
        forbidden_register = alice_client.post(
            "/api/auth/register",
            headers=_read_headers(),
            json={
                "email": "originless@example.test",
                "password": "originless-local-password",
                "display_name": "Originless",
            },
        )
        _assert_bounded_error(forbidden_register, status_code=403)

        alice = _register(alice_client, email="alice@example.test", display_name="Alice")
        bob = _register(bob_client, email="bob@example.test", display_name="Bob")
        _register(eve_client, email="eve@example.test", display_name="Eve")
        assert alice["display_name"] == "Alice"
        alice_csrf = _login_and_csrf(
            alice_client,
            email="alice@example.test",
            display_name="Alice",
        )
        bob_csrf = _login_and_csrf(
            bob_client,
            email="bob@example.test",
            display_name="Bob",
        )
        eve_csrf = _login_and_csrf(
            eve_client,
            email="eve@example.test",
            display_name="Eve",
        )

        missing_csrf = alice_client.post(
            "/api/rooms",
            headers=_pre_auth_headers(),
            json={"name": "must not be created"},
        )
        _assert_bounded_error(missing_csrf, status_code=403)
        forged_origin = alice_client.post(
            "/api/rooms",
            headers={
                "Origin": "https://attacker.example.test",
                "X-AXit-Original-Host": _HOST,
                "X-CSRF-Token": alice_csrf,
            },
            json={"name": "also forbidden"},
        )
        _assert_bounded_error(forged_origin, status_code=403)

        friend_request = alice_client.post(
            "/api/friend-requests",
            headers=_mutation_headers(alice_csrf),
            json={"addressee_id": bob["id"]},
        )
        assert friend_request.status_code == 201, friend_request.text
        friend_request_id = friend_request.json()["id"]
        accepted = bob_client.post(
            f"/api/friend-requests/{friend_request_id}/accept",
            headers=_mutation_headers(bob_csrf),
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "accepted"

        room_response = alice_client.post(
            "/api/rooms",
            headers=_mutation_headers(alice_csrf),
            json={"name": "Private fixture room"},
        )
        assert room_response.status_code == 201, room_response.text
        room_id = room_response.json()["id"]
        invitation = alice_client.post(
            f"/api/rooms/{room_id}/invitations",
            headers=_mutation_headers(alice_csrf),
            json={"invitee_id": bob["id"]},
        )
        assert invitation.status_code == 201, invitation.text
        assert invitation.json()["status"] == "accepted"

        session_response = alice_client.post(
            f"/api/rooms/{room_id}/sessions",
            headers=_mutation_headers(alice_csrf),
            json={"topic": "Fixture-backed meeting", "description": "Phase 3 E2E"},
        )
        assert session_response.status_code == 201, session_response.text
        session_id = session_response.json()["id"]

        # These exact participant spans are the only normal fixture inputs.
        # They are source material, never provider aliases.
        for text in (
            "Facilitator: The pilot scope and owner are confirmed, and the next review date is Friday.",
            "Alice: The Tuesday checklist assignment is recorded under my name.",
        ):
            submitted = alice_client.post(
                f"/api/sessions/{session_id}/submissions/text",
                headers=_mutation_headers(alice_csrf),
                json={"text": text},
            )
            assert submitted.status_code == 201, submitted.text
        bob_submission = bob_client.post(
            f"/api/sessions/{session_id}/submissions/text",
            headers=_mutation_headers(bob_csrf),
            json={"text": "Bob: The sample records passed the validation audit on Thursday."},
        )
        assert bob_submission.status_code == 201, bob_submission.text

        closed = alice_client.post(
            f"/api/sessions/{session_id}/close",
            headers=_mutation_headers(alice_csrf),
            json={"exclusions": []},
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["state"] == "processing"

        worker = FencedGenerationWorker(
            connection_factory=lambda: open_connection(route_adapter_database_url)
        )
        first_outcome = worker.run_once(owner="route-e2e-worker-a")
        second_outcome = worker.run_once(owner="route-e2e-worker-b")
        assert first_outcome.claimed and first_outcome.completed
        assert second_outcome.claimed and second_outcome.completed
        assert first_outcome.error_code is None
        assert second_outcome.error_code is None

        ready = alice_client.get(f"/api/sessions/{session_id}", headers=_read_headers())
        assert ready.status_code == 200, ready.text
        assert ready.json()["state"] == "ready"
        summary = bob_client.get(f"/api/sessions/{session_id}/summary", headers=_read_headers())
        assert summary.status_code == 200, summary.text
        summary_body = summary.json()
        assert summary_body["snapshot_id"] == closed.json()["snapshot_id"]
        serialized_summary = json.dumps(summary_body, ensure_ascii=False)
        assert "anchor-agenda-001" not in serialized_summary
        assert "web_evidence" not in serialized_summary
        assert "verdict" not in serialized_summary.lower()
        support = summary_body["sections"][0]["items"][0]["supports"][0]
        citation_id = support["citation_id"]
        source_anchor_id = support["source_anchor_id"]

        research = bob_client.get(f"/api/sessions/{session_id}/research", headers=_read_headers())
        assert research.status_code == 200, research.text
        research_body = research.json()
        assert research_body["snapshot_id"] == closed.json()["snapshot_id"]
        assert len(research_body["topic_items"]) == 3
        assert len(research_body["fact_checks"]) == 3
        serialized_research = json.dumps(research_body, ensure_ascii=False)
        assert "web-evidence-" not in serialized_research
        assert "anchor-agenda-001" not in serialized_research

        report = bob_client.get(f"/api/sessions/{session_id}/report", headers=_read_headers())
        assert report.status_code == 200, report.text
        assert report.json()["source_quality"] == {
            "status": "clean",
            "total_anchor_count": 3,
            "accepted_anchor_count": 3,
            "excluded_anchor_count": 0,
            "reason_counts": {},
        }

        resolved = bob_client.get(f"/api/citations/{citation_id}/resolve", headers=_read_headers())
        assert resolved.status_code == 200, resolved.text
        target = resolved.json()
        assert target["target_type"] == "source_anchor"
        assert target["source_anchor_id"] == source_anchor_id
        viewer = bob_client.get(
            f"/api/source-revisions/{target['source_revision_id']}/viewer?anchor={source_anchor_id}",
            headers=_read_headers(),
        )
        assert viewer.status_code == 200, viewer.text
        viewer_body = viewer.json()
        assert viewer_body["highlighted_anchor"]["id"] == source_anchor_id
        assert viewer_body["highlighted_anchor"]["exact_quote"] in viewer_body["text"]

        # Eve has a valid account/session/CSRF but no membership.  Each read
        # must stay bounded and indistinguishable from a missing resource.
        comparison_left = uuid4()
        comparison_right = uuid4()
        for path in (
            f"/api/sessions/{session_id}",
            f"/api/sessions/{session_id}/summary",
            f"/api/sessions/{session_id}/suggestions",
            f"/api/sessions/{session_id}/search?q=agenda",
            f"/api/sessions/{session_id}/comparison"
            f"?left_revision_id={comparison_left}&right_revision_id={comparison_right}",
            f"/api/citations/{citation_id}/resolve",
            f"/api/source-revisions/{target['source_revision_id']}/viewer?anchor={source_anchor_id}",
        ):
            _assert_bounded_error(eve_client.get(path, headers=_read_headers()), status_code=404)

        # Service-level normalization and cross-field checks can reject values
        # that pass the wire model. They still need the bounded 422 envelope,
        # never an uncaught ValueError/500.
        _assert_bounded_error(
            bob_client.get(
                f"/api/sessions/{session_id}/search?q=%20",
                headers=_read_headers(),
            ),
            status_code=422,
        )
        same_revision = uuid4()
        _assert_bounded_error(
            bob_client.get(
                f"/api/sessions/{session_id}/comparison"
                f"?left_revision_id={same_revision}&right_revision_id={same_revision}",
                headers=_read_headers(),
            ),
            status_code=422,
        )
        _assert_bounded_error(
            bob_client.post(
                f"/api/sessions/{session_id}/suggestions",
                headers=_mutation_headers(bob_csrf),
                json={"suggested_text": " ", "rationale": ""},
            ),
            status_code=422,
        )
        eve_close = eve_client.post(
            f"/api/sessions/{session_id}/close",
            headers=_mutation_headers(eve_csrf),
            json={"exclusions": []},
        )
        _assert_bounded_error(eve_close, status_code=404)
