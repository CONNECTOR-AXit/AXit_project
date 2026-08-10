"""Browser-boundary security regressions for file originals."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.main import app
from app.migrations import upgrade_database


pytestmark = pytest.mark.security

_ORIGIN = "http://localhost:3000"
_HOST = "localhost:3000"
_PDF = b"%PDF-1.7\nroute security fixture"


@contextmanager
def _temporary_database() -> Iterator[str]:
    configured_url = os.environ.get("AXIT_TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("AXIT_TEST_DATABASE_URL is required for file route security")
    connection_info = conninfo_to_dict(configured_url)
    database_name = "axit_file_security_" + uuid4().hex
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
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            maintenance.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))


def _read_headers() -> dict[str, str]:
    return {"X-AXit-Original-Host": _HOST}


def _mutation_headers(csrf: str) -> dict[str, str]:
    return {**_read_headers(), "Origin": _ORIGIN, "X-CSRF-Token": csrf}


def _register_and_login(client: TestClient, *, label: str) -> tuple[dict[str, object], str]:
    email = f"{label}@example.test"
    password = f"{label}-local-password"
    registered = client.post(
        "/api/auth/register",
        headers={**_read_headers(), "Origin": _ORIGIN},
        json={"email": email, "password": password, "display_name": label.title()},
    )
    assert registered.status_code == 201, registered.text
    login = client.post(
        "/api/auth/login",
        headers={**_read_headers(), "Origin": _ORIGIN},
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    csrf = client.get("/api/csrf", headers=_read_headers())
    assert csrf.status_code == 200, csrf.text
    return registered.json(), str(csrf.json()["csrf_token"])


@dataclass(slots=True)
class FileRouteContext:
    member: TestClient
    outsider: TestClient
    anonymous: TestClient
    member_csrf: str
    outsider_csrf: str
    session_id: str


@pytest.fixture
def file_route_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[FileRouteContext]:
    repository_blob_root = Path(__file__).resolve().parents[2] / ".axit-blobs"
    repository_blobs_before = {
        path.relative_to(repository_blob_root)
        for path in repository_blob_root.rglob("*")
        if path.is_file()
    } if repository_blob_root.exists() else set()
    with _temporary_database() as database_url:
        upgrade_database(database_url)
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("PUBLIC_ORIGIN", _ORIGIN)
        monkeypatch.setenv("PUBLIC_HOST", _HOST)
        monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
        # contracts._file_submission_service resolves this canonical setting at
        # request time, so every test original is isolated under pytest tmp_path.
        monkeypatch.setenv("AXIT_BLOB_ROOT", str(tmp_path))
        with (
            TestClient(app, base_url=_ORIGIN) as member,
            TestClient(app, base_url=_ORIGIN) as outsider,
            TestClient(app, base_url=_ORIGIN) as anonymous,
        ):
            _, member_csrf = _register_and_login(member, label="filemember")
            _, outsider_csrf = _register_and_login(outsider, label="fileoutsider")
            room = member.post(
                "/api/rooms",
                headers=_mutation_headers(member_csrf),
                json={"name": "Protected originals"},
            )
            assert room.status_code == 201, room.text
            session = member.post(
                f"/api/rooms/{room.json()['id']}/sessions",
                headers=_mutation_headers(member_csrf),
                json={"topic": "Confidential agenda"},
            )
            assert session.status_code == 201, session.text
            yield FileRouteContext(
                member=member,
                outsider=outsider,
                anonymous=anonymous,
                member_csrf=member_csrf,
                outsider_csrf=outsider_csrf,
                session_id=str(session.json()["id"]),
            )
    repository_blobs_after = {
        path.relative_to(repository_blob_root)
        for path in repository_blob_root.rglob("*")
        if path.is_file()
    } if repository_blob_root.exists() else set()
    assert repository_blobs_after == repository_blobs_before


def _upload(client: TestClient, session_id: str, headers: dict[str, str]) -> object:
    return client.post(
        f"/api/sessions/{session_id}/submissions/files",
        headers=headers,
        files={"file": ("agenda.pdf", _PDF, "application/pdf")},
    )


def test_unauthenticated_browser_cannot_upload(file_route_context: FileRouteContext) -> None:
    response = _upload(
        file_route_context.anonymous,
        file_route_context.session_id,
        _mutation_headers("untrusted-token"),
    )

    assert response.status_code == 401


def test_authenticated_upload_requires_session_bound_csrf(
    file_route_context: FileRouteContext,
) -> None:
    response = _upload(
        file_route_context.member,
        file_route_context.session_id,
        {**_read_headers(), "Origin": _ORIGIN},
    )

    assert response.status_code == 403


def test_nonmember_cannot_upload_to_a_private_session(
    file_route_context: FileRouteContext,
) -> None:
    response = _upload(
        file_route_context.outsider,
        file_route_context.session_id,
        _mutation_headers(file_route_context.outsider_csrf),
    )

    assert response.status_code == 404


def test_original_download_is_attachment_with_nosniff(
    file_route_context: FileRouteContext,
) -> None:
    uploaded = _upload(
        file_route_context.member,
        file_route_context.session_id,
        _mutation_headers(file_route_context.member_csrf),
    )
    assert uploaded.status_code == 201, uploaded.text

    response = file_route_context.member.get(
        f"/api/source-revisions/{uploaded.json()['current_revision_id']}/original",
        headers=_read_headers(),
    )

    assert response.status_code == 200
    assert response.content == _PDF
    assert response.headers["content-disposition"].lower().startswith("attachment;")
    assert "agenda.pdf" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_nonmember_cannot_download_a_private_original(
    file_route_context: FileRouteContext,
) -> None:
    uploaded = _upload(
        file_route_context.member,
        file_route_context.session_id,
        _mutation_headers(file_route_context.member_csrf),
    )
    assert uploaded.status_code == 201, uploaded.text

    response = file_route_context.outsider.get(
        f"/api/source-revisions/{uploaded.json()['current_revision_id']}/original",
        headers=_read_headers(),
    )

    assert response.status_code == 404
