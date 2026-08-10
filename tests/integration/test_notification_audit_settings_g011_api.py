"""Disposable PostgreSQL route and IDOR proof for deferred G011."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.main import app
from app.migrations import upgrade_database


pytestmark = pytest.mark.integration

_ORIGIN = "http://localhost:3000"
_HOST = "localhost:3000"
_PASSWORD = "Disposable-test-password-42!"
_TRUSTED_HEADERS = {"Origin": _ORIGIN, "X-AXit-Original-Host": _HOST}


@contextmanager
def _database() -> Iterator[str]:
    configured = os.environ.get("AXIT_TEST_DATABASE_URL")
    if not configured:
        pytest.skip(
            "AXIT_TEST_DATABASE_URL is required for isolated PostgreSQL integration"
        )
    info = conninfo_to_dict(configured)
    name = "axit_g011_" + uuid4().hex
    maintenance_info = dict(info)
    maintenance_info["dbname"] = "postgres"
    target_info = dict(info)
    target_info["dbname"] = name
    target = make_conninfo(**target_info)
    with psycopg.connect(**maintenance_info, autocommit=True) as maintenance:
        maintenance.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            yield target
        finally:
            maintenance.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid<>pg_backend_pid()",
                (name,),
            )
            maintenance.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name))
            )


@pytest.fixture(scope="module")
def g011_database_url() -> Iterator[str]:
    previous = {
        name: os.environ.get(name)
        for name in (
            "DATABASE_URL",
            "PUBLIC_ORIGIN",
            "PUBLIC_HOST",
            "SESSION_COOKIE_SECURE",
        )
    }
    with _database() as database_url:
        upgrade_database(database_url)
        os.environ.update(
            {
                "DATABASE_URL": database_url,
                "PUBLIC_ORIGIN": _ORIGIN,
                "PUBLIC_HOST": _HOST,
                "SESSION_COOKIE_SECURE": "false",
            }
        )
        try:
            yield database_url
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def _identity(label: str) -> tuple[TestClient, UUID, dict[str, str]]:
    client = TestClient(app, base_url="http://testserver")
    email = f"{label}-{uuid4().hex}@example.invalid"
    registered = client.post(
        "/api/auth/register",
        headers=_TRUSTED_HEADERS,
        json={"email": email, "password": _PASSWORD, "display_name": label},
    )
    assert registered.status_code == 201, registered.text
    logged_in = client.post(
        "/api/auth/login",
        headers=_TRUSTED_HEADERS,
        json={"email": email, "password": _PASSWORD},
    )
    assert logged_in.status_code == 200, logged_in.text
    csrf = client.get("/api/csrf", headers=_TRUSTED_HEADERS)
    assert csrf.status_code == 200, csrf.text
    mutation_headers = {**_TRUSTED_HEADERS, "X-CSRF-Token": csrf.json()["csrf_token"]}
    return client, UUID(registered.json()["id"]), mutation_headers


def _session_graph(
    database_url: str, *, owner_id: UUID, member_id: UUID
) -> tuple[UUID, UUID]:
    room_id, session_id = uuid4(), uuid4()
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "INSERT INTO rooms(id,owner_id,name) VALUES(%s,%s,'G011 room')",
            (room_id, owner_id),
        )
        connection.execute(
            "INSERT INTO room_memberships(room_id,user_id,role) VALUES"
            "(%s,%s,'host'),(%s,%s,'member')",
            (room_id, owner_id, room_id, member_id),
        )
        connection.execute(
            "INSERT INTO talk_sessions(id,room_id,host_id,mode,topic,state) "
            "VALUES(%s,%s,%s,'relay','G011 topic','open')",
            (session_id, room_id, owner_id),
        )
    return room_id, session_id


def _preference_matrix(*, mention_email: bool = False) -> dict[str, dict[str, bool]]:
    return {
        "analysis_completed": {"in_app": True, "email_intent": False},
        "mention": {"in_app": True, "email_intent": mention_email},
        "comment": {"in_app": True, "email_intent": False},
    }


def test_private_routes_require_authentication_and_valid_csrf(
    g011_database_url: str,
) -> None:
    del g011_database_url
    anonymous = TestClient(app)
    assert (
        anonymous.get(
            "/api/notifications", headers={"X-AXit-Original-Host": _HOST}
        ).status_code
        == 401
    )

    client, _, headers = _identity("Auth")
    profile = client.get("/api/me/profile", headers=_TRUSTED_HEADERS).json()
    payload = {
        "expected_version": profile["profile_version"],
        "display_name": profile["display_name"],
        "job_title": "Engineer",
        "language": profile["language"],
    }
    assert (
        client.put(
            "/api/me/profile", headers={"X-AXit-Original-Host": _HOST}, json=payload
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/me/profile",
            headers={**_TRUSTED_HEADERS, "X-CSRF-Token": "wrong"},
            json=payload,
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/me/profile",
            headers={**headers, "Origin": "https://forged.invalid"},
            json=payload,
        ).status_code
        == 403
    )
    assert (
        client.put("/api/me/profile", headers=headers, json=payload).status_code == 200
    )


def test_profile_cas_preserves_noop_version_and_rejects_stale_write(
    g011_database_url: str,
) -> None:
    client, user_id, headers = _identity("Profile")
    initial = client.get("/api/me/profile", headers=_TRUSTED_HEADERS).json()
    changed_payload = {
        "expected_version": initial["profile_version"],
        "display_name": "Profile Changed",
        "job_title": "Facilitator",
        "language": "en",
    }
    changed = client.put("/api/me/profile", headers=headers, json=changed_payload)
    assert changed.status_code == 200 and changed.json()["updated"] is True
    assert changed.json()["profile_version"] == initial["profile_version"] + 1

    same_payload = {
        **changed_payload,
        "expected_version": changed.json()["profile_version"],
    }
    unchanged = client.put("/api/me/profile", headers=headers, json=same_payload)
    assert unchanged.status_code == 200 and unchanged.json()["updated"] is False
    assert unchanged.json()["profile_version"] == changed.json()["profile_version"]
    assert (
        unchanged.json()["profile_updated_at"] == changed.json()["profile_updated_at"]
    )
    assert (
        client.put("/api/me/profile", headers=headers, json=changed_payload).status_code
        == 409
    )

    latest_payload = {
        **same_payload,
        "expected_version": unchanged.json()["profile_version"],
        "display_name": "Latest Profile Name",
    }
    latest = client.put("/api/me/profile", headers=headers, json=latest_payload)
    assert latest.status_code == 200 and latest.json()["updated"] is True
    history = client.get(
        "/api/audit-events", headers=_TRUSTED_HEADERS, params={"scope": "personal"}
    )
    assert history.status_code == 200
    profile_events = [
        item
        for item in history.json()["items"]
        if item["event_type"] == "profile.updated"
    ]
    assert len(profile_events) == 2
    assert {item["actor_id"] for item in profile_events} == {str(user_id)}
    assert {item["actor_display_name"] for item in profile_events} == {
        "Latest Profile Name"
    }


def test_profile_update_rejects_email_mutation_payload(
    g011_database_url: str,
) -> None:
    del g011_database_url
    client, _, headers = _identity("ImmutableEmail")
    initial = client.get("/api/me/profile", headers=_TRUSTED_HEADERS)
    assert initial.status_code == 200
    profile = initial.json()

    response = client.put(
        "/api/me/profile",
        headers=headers,
        json={
            "expected_version": profile["profile_version"],
            "display_name": profile["display_name"],
            "job_title": profile["job_title"],
            "language": profile["language"],
            "email": "attacker@example.invalid",
        },
    )

    assert response.status_code == 422
    unchanged = client.get("/api/me/profile", headers=_TRUSTED_HEADERS)
    assert unchanged.status_code == 200
    assert unchanged.json()["email"] == profile["email"]
    assert unchanged.json()["profile_version"] == profile["profile_version"]


def test_profile_reads_fail_closed_without_repairing_missing_defaults(
    g011_database_url: str,
) -> None:
    client, user_id, _ = _identity("MissingAggregate")
    with psycopg.connect(g011_database_url) as connection:
        connection.execute(
            "DELETE FROM notification_preferences WHERE user_id=%s AND kind='comment' AND channel='email_intent'",
            (user_id,),
        )
    response = client.get("/api/me/preferences", headers=_TRUSTED_HEADERS)
    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "detail": "service is temporarily unavailable",
    }
    with psycopg.connect(g011_database_url) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM notification_preferences WHERE user_id=%s",
                (user_id,),
            ).fetchone()[0]
            == len(_preference_matrix()) * 2 - 1
        )
        connection.execute("DELETE FROM user_profiles WHERE user_id=%s", (user_id,))
    profile_response = client.get("/api/me/profile", headers=_TRUSTED_HEADERS)
    assert profile_response.status_code == 500
    assert profile_response.json() == response.json()
    with psycopg.connect(g011_database_url) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM user_profiles WHERE user_id=%s", (user_id,)
            ).fetchone()[0]
            == 0
        )


def test_preferences_cas_preserves_noop_version_and_profile_aggregate(
    g011_database_url: str,
) -> None:
    del g011_database_url
    client, _, headers = _identity("Preferences")
    profile_before = client.get("/api/me/profile", headers=_TRUSTED_HEADERS).json()
    initial = client.get("/api/me/preferences", headers=_TRUSTED_HEADERS).json()
    changed = client.put(
        "/api/me/preferences",
        headers=headers,
        json={
            "expected_version": initial["preferences_version"],
            "values": _preference_matrix(mention_email=True),
        },
    )
    assert changed.status_code == 200 and changed.json()["updated"] is True

    unchanged = client.put(
        "/api/me/preferences",
        headers=headers,
        json={
            "expected_version": changed.json()["preferences_version"],
            "values": _preference_matrix(mention_email=True),
        },
    )
    assert unchanged.status_code == 200 and unchanged.json()["updated"] is False
    assert (
        unchanged.json()["preferences_updated_at"]
        == changed.json()["preferences_updated_at"]
    )
    assert (
        client.get("/api/me/profile", headers=_TRUSTED_HEADERS).json() == profile_before
    )
    assert (
        client.put(
            "/api/me/preferences",
            headers=headers,
            json={
                "expected_version": initial["preferences_version"],
                "values": _preference_matrix(),
            },
        ).status_code
        == 409
    )


def test_comment_mention_materializes_only_recipient_notification_and_local_outbox(
    g011_database_url: str,
) -> None:
    alice, alice_id, alice_headers = _identity("Alice")
    bob, bob_id, bob_headers = _identity("Bob")
    eve, eve_id, _ = _identity("Eve")
    _, session_id = _session_graph(
        g011_database_url, owner_id=alice_id, member_id=bob_id
    )
    preferences = alice.get("/api/me/preferences", headers=_TRUSTED_HEADERS).json()
    enabled = alice.put(
        "/api/me/preferences",
        headers=alice_headers,
        json={
            "expected_version": preferences["preferences_version"],
            "values": _preference_matrix(mention_email=True),
        },
    )
    assert enabled.status_code == 200

    client_request_id = uuid4()
    comment_payload = {
        "client_request_id": str(client_request_id),
        "body": "Alice mention",
        "mentioned_user_ids": [str(alice_id)],
    }
    created = bob.post(
        f"/api/sessions/{session_id}/comments",
        headers=bob_headers,
        json=comment_payload,
    )
    assert created.status_code == 201, created.text
    comment_id = UUID(created.json()["id"])
    replay = bob.post(
        f"/api/sessions/{session_id}/comments",
        headers=bob_headers,
        json=comment_payload,
    )
    assert replay.status_code == 200
    assert replay.json() == {"id": str(comment_id), "version": 1, "idempotent": True}
    _, other_session_id = _session_graph(
        g011_database_url, owner_id=alice_id, member_id=bob_id
    )
    cross_session_reuse = bob.post(
        f"/api/sessions/{other_session_id}/comments",
        headers=bob_headers,
        json=comment_payload,
    )
    assert cross_session_reuse.status_code == 409
    assert cross_session_reuse.json()["code"] == "conflict"

    alice_notifications = alice.get(
        "/api/notifications", headers=_TRUSTED_HEADERS
    ).json()
    assert [
        (item["kind"], item["resource_id"]) for item in alice_notifications["items"]
    ] == [("mention", str(comment_id))]
    assert bob.get("/api/notifications", headers=_TRUSTED_HEADERS).json()["items"] == []
    assert eve.get("/api/notifications", headers=_TRUSTED_HEADERS).json()["items"] == []
    outbox = alice.get("/api/me/email-outbox", headers=_TRUSTED_HEADERS).json()["items"]
    assert len(outbox) == 1 and outbox[0]["notification_kind"] == "mention"
    assert outbox[0]["status"] == "queued_local"
    assert "recipient_id" not in alice_notifications["items"][0]
    assert "recipient_id" not in outbox[0] and "email" not in outbox[0]

    with psycopg.connect(g011_database_url) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM comment_mentions WHERE comment_id=%s AND user_id=%s",
                (comment_id, alice_id),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM notifications WHERE resource_id=%s AND recipient_id NOT IN (%s)",
                (comment_id, alice_id),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM email_outbox WHERE recipient_id IN (%s,%s)",
                (bob_id, eve_id),
            ).fetchone()[0]
            == 0
        )


def test_comment_routes_conceal_existing_and_unknown_foreign_ids(
    g011_database_url: str,
) -> None:
    alice, alice_id, _ = _identity("CommentOwner")
    bob, bob_id, bob_headers = _identity("CommentAuthor")
    eve, _, eve_headers = _identity("CommentEve")
    _, session_id = _session_graph(
        g011_database_url, owner_id=alice_id, member_id=bob_id
    )
    created = bob.post(
        f"/api/sessions/{session_id}/comments",
        headers=bob_headers,
        json={
            "client_request_id": str(uuid4()),
            "body": "private",
            "mentioned_user_ids": [],
        },
    )
    assert created.status_code == 201
    existing_id, unknown_id = created.json()["id"], str(uuid4())
    payload = {"expected_version": 1, "body": "probe", "mentioned_user_ids": []}

    existing = eve.put(
        f"/api/comments/{existing_id}", headers=eve_headers, json=payload
    )
    unknown = eve.put(f"/api/comments/{unknown_id}", headers=eve_headers, json=payload)
    assert (existing.status_code, existing.json()) == (
        unknown.status_code,
        unknown.json(),
    )
    assert existing.status_code == 404
    assert (
        eve.get(
            f"/api/sessions/{session_id}/comments", headers=_TRUSTED_HEADERS
        ).status_code
        == 404
    )
    del alice


def test_comment_mentions_reject_nonmembers_without_creating_rows(
    g011_database_url: str,
) -> None:
    alice, alice_id, _ = _identity("MentionOwner")
    bob, bob_id, bob_headers = _identity("MentionAuthor")
    _, eve_id, _ = _identity("MentionEve")
    _, session_id = _session_graph(
        g011_database_url, owner_id=alice_id, member_id=bob_id
    )
    client_request_id = uuid4()

    response = bob.post(
        f"/api/sessions/{session_id}/comments",
        headers=bob_headers,
        json={
            "client_request_id": str(client_request_id),
            "body": "forbidden mention",
            "mentioned_user_ids": [str(eve_id)],
        },
    )
    assert response.status_code == 404
    with psycopg.connect(g011_database_url) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM comments WHERE author_id=%s AND client_request_id=%s",
                (bob_id, client_request_id),
            ).fetchone()[0]
            == 0
        )
    del alice


def test_notification_read_conceals_foreign_ids_and_preserves_owner_row(
    g011_database_url: str,
) -> None:
    alice, alice_id, _ = _identity("NoticeOwner")
    bob, _, bob_headers = _identity("NoticeProbe")
    notification_id = uuid4()
    with psycopg.connect(g011_database_url) as connection:
        connection.execute(
            "INSERT INTO notifications(id,recipient_id,kind,resource_type,resource_id,action_kind,title,body,dedupe_key) "
            "VALUES(%s,%s,'analysis_completed','session',%s,'open_session','ready','ready',%s)",
            (notification_id, alice_id, uuid4(), f"g011:{notification_id}"),
        )

    foreign = bob.post(
        f"/api/notifications/{notification_id}/read", headers=bob_headers
    )
    unknown = bob.post(f"/api/notifications/{uuid4()}/read", headers=bob_headers)
    assert (foreign.status_code, foreign.json()) == (
        unknown.status_code,
        unknown.json(),
    )
    assert foreign.status_code == 404
    with psycopg.connect(g011_database_url) as connection:
        assert (
            connection.execute(
                "SELECT read_at IS NULL FROM notifications WHERE id=%s",
                (notification_id,),
            ).fetchone()[0]
            is True
        )
    del alice


def test_audit_cursor_is_reauthorized_after_membership_revocation(
    g011_database_url: str,
) -> None:
    alice, alice_id, _ = _identity("AuditOwner")
    bob, bob_id, bob_headers = _identity("AuditMember")
    eve, eve_id, _ = _identity("AuditEve")
    room_id, session_id = _session_graph(
        g011_database_url, owner_id=alice_id, member_id=bob_id
    )
    for body in ("first", "second"):
        response = bob.post(
            f"/api/sessions/{session_id}/comments",
            headers=bob_headers,
            json={
                "client_request_id": str(uuid4()),
                "body": body,
                "mentioned_user_ids": [],
            },
        )
        assert response.status_code == 201

    page = bob.get(
        "/api/audit-events",
        headers=_TRUSTED_HEADERS,
        params={"scope": "session", "scope_id": str(session_id), "limit": 1},
    )
    assert page.status_code == 200 and page.json()["next_cursor"] is not None
    cursor = page.json()["next_cursor"]
    foreign = eve.get(
        "/api/audit-events",
        headers=_TRUSTED_HEADERS,
        params={"scope": "session", "scope_id": str(session_id), "cursor": cursor},
    )
    assert foreign.status_code == 404
    with psycopg.connect(g011_database_url) as connection:
        connection.execute(
            "UPDATE room_memberships SET left_at=clock_timestamp() WHERE room_id=%s AND user_id=%s",
            (room_id, bob_id),
        )

    revoked = bob.get(
        "/api/audit-events",
        headers=_TRUSTED_HEADERS,
        params={"scope": "session", "scope_id": str(session_id), "cursor": cursor},
    )
    assert revoked.status_code == 404
    with psycopg.connect(g011_database_url) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM audit_events WHERE session_id=%s AND actor_id=%s",
                (session_id, bob_id),
            ).fetchone()[0]
            == 2
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM room_memberships WHERE room_id=%s AND user_id=%s AND left_at IS NULL",
                (room_id, eve_id),
            ).fetchone()[0]
            == 0
        )
    del alice


def test_generated_g005_contract_matches_runtime_openapi_paths() -> None:
    generated = json.loads(
        Path("packages/schemas/openapi.v1.json").read_text(encoding="utf-8")
    )
    runtime = app.openapi()
    paths = (
        "/api/notifications",
        "/api/notifications/{notification_id}/read",
        "/api/notifications/read-all",
        "/api/me/email-outbox",
        "/api/me/profile",
        "/api/me/preferences",
        "/api/sessions/{session_id}/comments",
        "/api/comments/{comment_id}",
        "/api/audit-events",
    )
    assert {path: runtime["paths"][path] for path in paths} == {
        path: generated["paths"][path] for path in paths
    }
    g005_schemas = (
        "NotificationPageResponse",
        "EmailOutboxPageResponse",
        "ProfileUpdateResponse",
        "NotificationPreferencesUpdateResponse",
        "CommentMutationResponse",
        "AuditEventPageResponse",
    )
    assert {name: runtime["components"]["schemas"][name] for name in g005_schemas} == {
        name: generated["components"]["schemas"][name] for name in g005_schemas
    }
