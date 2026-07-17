"""Black-box contract for the disposable Phase 0 Option A transport proof.

Every request in this module targets the public web origin, never the API port.
The web process must proxy these exact test-only endpoints to FastAPI:

* ``POST /api/__phase0/session/login``
* ``GET /api/__phase0/session``
* ``GET /api/__phase0/csrf``
* ``POST /api/__phase0/mutation``
* ``POST /api/__phase0/upload``
* ``GET /api/__phase0/citations/{citation_id}/resolve``
* ``GET /api/__phase0/citation-invocations/{invocation_id}``

Successful upstream responses carry ``X-Phase0-Upstream: api`` so a response
implemented only in the thin web shell cannot accidentally satisfy the proof.
This harness proves transport behavior only. It is not evidence that the
future database-backed production authentication implementation is correct.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO
from urllib.parse import parse_qs, quote, urlsplit

import httpx
import pytest


PHASE0_BASE_URL = os.environ.get(
    "PHASE0_BASE_URL",
    "http://127.0.0.1:3000",
).rstrip("/")
_BASE_URL_PARTS = urlsplit(PHASE0_BASE_URL)
if (
    _BASE_URL_PARTS.scheme not in {"http", "https"}
    or not _BASE_URL_PARTS.netloc
    or _BASE_URL_PARTS.path not in {"", "/"}
    or _BASE_URL_PARTS.query
    or _BASE_URL_PARTS.fragment
):
    raise ValueError(
        "PHASE0_BASE_URL must be an http(s) origin without a path, query, or fragment"
    )

PHASE0_PUBLIC_ORIGIN = os.environ.get(
    "PHASE0_PUBLIC_ORIGIN",
    "http://localhost:3000",
)
PHASE0_TRUSTED_HOST = os.environ.get(
    "PHASE0_TRUSTED_HOST",
    "localhost:3000",
)

SESSION_COOKIE_NAME = "phase0_session"
CSRF_HEADER_NAME = "X-CSRF-Token"
UPSTREAM_HEADER_NAME = "X-Phase0-Upstream"
UPSTREAM_HEADER_VALUE = "api"
CITATION_INVOCATION_HEADER_NAME = "X-Phase0-Citation-Invocation"

LOGIN_PATH = "/api/__phase0/session/login"
SESSION_PATH = "/api/__phase0/session"
CSRF_PATH = "/api/__phase0/csrf"
MUTATION_PATH = "/api/__phase0/mutation"
UPLOAD_PATH = "/api/__phase0/upload"

CITATION_ID = "phase0-citation-001"
CITATION_RESOLVE_PATH = f"/api/__phase0/citations/{CITATION_ID}/resolve"
CITATION_INVOCATION_PATH_PREFIX = "/api/__phase0/citation-invocations"
RESERVED_CITATION_TARGET = (
    "https://fixtures.invalid/viewer/revision-agenda-001"
    "?anchor=anchor-agenda-001&view=source"
    "#highlight=anchor-agenda-001"
)

EXACT_UPLOAD_BYTES = 20 * 1024 * 1024
OVERSIZED_UPLOAD_BYTES = EXACT_UPLOAD_BYTES + 1
_PAYLOAD_CHUNK = bytes(range(256)) * 256

pytestmark = [pytest.mark.phase0, pytest.mark.integration]
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def web_client() -> Iterator[httpx.Client]:
    with httpx.Client(
        base_url=PHASE0_BASE_URL,
        follow_redirects=False,
        timeout=httpx.Timeout(20.0, connect=2.0),
    ) as client:
        yield client


def _trusted_headers(*, csrf_token: str | None = None) -> dict[str, str]:
    headers = {
        "Host": PHASE0_TRUSTED_HOST,
        "Origin": PHASE0_PUBLIC_ORIGIN,
    }
    if csrf_token is not None:
        headers[CSRF_HEADER_NAME] = csrf_token
    return headers


def _assert_api_upstream(response: httpx.Response) -> None:
    assert response.headers.get(UPSTREAM_HEADER_NAME) == UPSTREAM_HEADER_VALUE


def _session_cookie_value(client: httpx.Client) -> str:
    cookie = client.cookies.get(SESSION_COOKIE_NAME)
    assert isinstance(cookie, str)
    assert cookie
    return cookie


def _login(client: httpx.Client, *, subject: str) -> tuple[httpx.Response, str]:
    response = client.post(
        LOGIN_PATH,
        json={"subject": subject},
        headers=_trusted_headers(),
    )
    assert response.status_code == 204
    _assert_api_upstream(response)
    return response, _session_cookie_value(client)


def _csrf_token(client: httpx.Client) -> str:
    response = client.get(CSRF_PATH, headers={"Host": PHASE0_TRUSTED_HOST})
    assert response.status_code == 200
    _assert_api_upstream(response)
    payload = response.json()
    token = payload.get("csrf_token")
    assert isinstance(token, str)
    assert token
    return token


def _assert_session_cookie_contract(response: httpx.Response) -> None:
    session_cookie_headers = [
        value
        for value in response.headers.get_list("set-cookie")
        if value.lower().startswith(f"{SESSION_COOKIE_NAME.lower()}=")
    ]
    assert len(session_cookie_headers) == 1

    attributes = [
        component.strip().lower()
        for component in session_cookie_headers[0].split(";")[1:]
    ]
    assert "httponly" in attributes
    assert "path=/" in attributes
    assert "samesite=lax" in attributes
    assert not any(attribute.startswith("domain=") for attribute in attributes)


def _assert_authenticated_cookie_reached_api(
    client: httpx.Client, session_cookie: str
) -> None:
    response = client.get(SESSION_PATH, headers={"Host": PHASE0_TRUSTED_HOST})
    assert response.status_code == 200
    _assert_api_upstream(response)
    payload = response.json()
    assert payload.get("authenticated") is True
    assert payload.get("cookie_forwarded") is True
    assert (
        payload.get("session_cookie_sha256")
        == hashlib.sha256(session_cookie.encode("utf-8")).hexdigest()
    )


@contextmanager
def _deterministic_payload(
    size: int,
) -> Iterator[tuple[BinaryIO, str]]:
    """Create a deterministic upload without retaining the payload in memory."""

    digest = hashlib.sha256()
    with tempfile.TemporaryFile(mode="w+b") as payload:
        remaining = size
        while remaining:
            chunk = _PAYLOAD_CHUNK[: min(remaining, len(_PAYLOAD_CHUNK))]
            payload.write(chunk)
            digest.update(chunk)
            remaining -= len(chunk)
        payload.seek(0)
        yield payload, digest.hexdigest()


def test_phase0_api_is_not_published_outside_the_compose_network() -> None:
    completed = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="strict",
        text=True,
    )
    compose = json.loads(completed.stdout)

    assert compose["services"]["api"].get("ports") in (None, [])
    assert compose["services"]["orchestrator"].get("ports") in (None, [])
    web_ports = compose["services"]["web"].get("ports") or []
    assert len(web_ports) == 1
    assert web_ports[0]["host_ip"] == "127.0.0.1"
    assert int(web_ports[0]["published"]) == 3000
    assert int(web_ports[0]["target"]) == 3000

    runtime = subprocess.run(
        ["docker", "compose", "ps", "--format", "json", "api"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="strict",
        text=True,
    )
    api_processes = [
        json.loads(line) for line in runtime.stdout.splitlines() if line.strip()
    ]
    assert len(api_processes) == 1
    assert api_processes[0]["State"] == "running"
    assert api_processes[0]["Health"] == "healthy"
    publishers = api_processes[0].get("Publishers") or []
    assert all(
        publisher.get("URL", "") == ""
        and int(publisher.get("PublishedPort") or 0) == 0
        for publisher in publishers
    )

    web_runtime = subprocess.run(
        ["docker", "compose", "ps", "--format", "json", "web"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="strict",
        text=True,
    )
    web_processes = [
        json.loads(line) for line in web_runtime.stdout.splitlines() if line.strip()
    ]
    assert len(web_processes) == 1
    web_publishers = [
        publisher
        for publisher in (web_processes[0].get("Publishers") or [])
        if int(publisher.get("PublishedPort") or 0) > 0
    ]
    assert web_publishers == [
        {
            "URL": "127.0.0.1",
            "TargetPort": 3000,
            "PublishedPort": 3000,
            "Protocol": "tcp",
        }
    ]

    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", 8000), timeout=0.5)


def test_phase0_base_url_is_the_public_next_origin(
    web_client: httpx.Client,
) -> None:
    response = web_client.get("/health", headers={"Host": PHASE0_TRUSTED_HOST})

    assert response.status_code == 200
    assert response.json() == {"service": "web", "status": "ok"}
    assert response.headers.get(UPSTREAM_HEADER_NAME) is None


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": PHASE0_TRUSTED_HOST},
        {
            "Host": PHASE0_TRUSTED_HOST,
            "Origin": "https://attacker.invalid",
        },
        {
            "Host": "attacker.invalid",
            "Origin": PHASE0_PUBLIC_ORIGIN,
        },
    ],
    ids=["missing-origin", "forged-origin", "forged-host"],
)
def test_phase0_login_rejects_untrusted_transport_without_setting_cookie(
    web_client: httpx.Client,
    headers: dict[str, str],
) -> None:
    response = web_client.post(
        LOGIN_PATH,
        json={"subject": "phase0-untrusted-login"},
        headers=headers,
    )

    assert response.status_code == 403
    _assert_api_upstream(response)
    assert not response.headers.get_list("set-cookie")
    assert SESSION_COOKIE_NAME not in web_client.cookies


def test_phase0_session_cookie_is_host_only_forwarded_and_rotated(
    web_client: httpx.Client,
) -> None:
    first_login, first_session_cookie = _login(
        web_client, subject="phase0-cookie-rotation"
    )
    _assert_session_cookie_contract(first_login)
    first_csrf_token = _csrf_token(web_client)
    _assert_authenticated_cookie_reached_api(web_client, first_session_cookie)

    second_login, second_session_cookie = _login(
        web_client, subject="phase0-cookie-rotation"
    )
    _assert_session_cookie_contract(second_login)
    second_csrf_token = _csrf_token(web_client)

    assert second_session_cookie != first_session_cookie
    assert second_csrf_token != first_csrf_token
    _assert_authenticated_cookie_reached_api(web_client, second_session_cookie)

    with httpx.Client(
        base_url=PHASE0_BASE_URL,
        follow_redirects=False,
        timeout=httpx.Timeout(20.0, connect=2.0),
    ) as stale_client:
        stale_response = stale_client.get(
            SESSION_PATH,
            headers={
                "Host": PHASE0_TRUSTED_HOST,
                "Cookie": f"{SESSION_COOKIE_NAME}={first_session_cookie}",
            },
        )
    assert stale_response.status_code == 401
    _assert_api_upstream(stale_response)

    old_csrf_response = web_client.post(
        MUTATION_PATH,
        json={"operation": "phase0-proof"},
        headers=_trusted_headers(csrf_token=first_csrf_token),
    )
    assert old_csrf_response.status_code == 403
    _assert_api_upstream(old_csrf_response)


def test_phase0_valid_csrf_mutation_succeeds_through_web_proxy(
    web_client: httpx.Client,
) -> None:
    _login(web_client, subject="phase0-valid-csrf")
    csrf_token = _csrf_token(web_client)

    response = web_client.post(
        MUTATION_PATH,
        json={"operation": "phase0-proof"},
        headers=_trusted_headers(csrf_token=csrf_token),
    )

    assert response.status_code == 200
    _assert_api_upstream(response)
    assert response.json().get("mutated") is True


def test_phase0_missing_csrf_token_is_rejected_through_web_proxy(
    web_client: httpx.Client,
) -> None:
    _login(web_client, subject="phase0-missing-csrf")

    response = web_client.post(
        MUTATION_PATH,
        json={"operation": "phase0-proof"},
        headers=_trusted_headers(),
    )

    assert response.status_code == 403
    _assert_api_upstream(response)


def test_phase0_forged_origin_is_rejected_through_web_proxy(
    web_client: httpx.Client,
) -> None:
    _login(web_client, subject="phase0-forged-origin")
    csrf_token = _csrf_token(web_client)
    headers = _trusted_headers(csrf_token=csrf_token)
    headers["Origin"] = "https://attacker.invalid"

    response = web_client.post(
        MUTATION_PATH,
        json={"operation": "phase0-proof"},
        headers=headers,
    )

    assert response.status_code == 403
    _assert_api_upstream(response)


def test_phase0_forged_host_is_rejected_through_web_proxy(
    web_client: httpx.Client,
) -> None:
    _login(web_client, subject="phase0-forged-host")
    csrf_token = _csrf_token(web_client)
    headers = _trusted_headers(csrf_token=csrf_token)
    headers["Host"] = "attacker.invalid"

    response = web_client.post(
        MUTATION_PATH,
        json={"operation": "phase0-proof"},
        headers=headers,
    )

    assert response.status_code == 403
    _assert_api_upstream(response)


def test_phase0_exactly_20_mib_multipart_reaches_api_byte_exact(
    web_client: httpx.Client,
) -> None:
    _login(web_client, subject="phase0-upload-limit")
    csrf_token = _csrf_token(web_client)

    with _deterministic_payload(EXACT_UPLOAD_BYTES) as (payload, expected_sha256):
        response = web_client.post(
            UPLOAD_PATH,
            files={
                "file": (
                    "phase0-exactly-20mib.bin",
                    payload,
                    "application/octet-stream",
                )
            },
            headers=_trusted_headers(csrf_token=csrf_token),
            timeout=120.0,
        )

    assert response.status_code == 200
    _assert_api_upstream(response)
    result = response.json()
    assert result.get("bytes_received") == EXACT_UPLOAD_BYTES
    assert result.get("sha256") == expected_sha256


def test_phase0_20_mib_plus_one_multipart_is_rejected(
    web_client: httpx.Client,
) -> None:
    _login(web_client, subject="phase0-upload-oversized")
    csrf_token = _csrf_token(web_client)

    with _deterministic_payload(OVERSIZED_UPLOAD_BYTES) as (payload, _):
        response = web_client.post(
            UPLOAD_PATH,
            files={
                "file": (
                    "phase0-20mib-plus-one.bin",
                    payload,
                    "application/octet-stream",
                )
            },
            headers=_trusted_headers(csrf_token=csrf_token),
            timeout=120.0,
        )

    assert response.status_code == 413
    _assert_api_upstream(response)


def test_phase0_unbounded_chunked_multipart_is_rejected_at_web_boundary(
    web_client: httpx.Client,
) -> None:
    _login(web_client, subject="phase0-chunked-upload")
    csrf_token = _csrf_token(web_client)
    boundary = "phase0-chunked-boundary"
    body_chunks = iter(
        [
            f"--{boundary}\r\n".encode(),
            (
                'Content-Disposition: form-data; name="file"; '
                'filename="chunked.bin"\r\n'
            ).encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            b"bounded-test-payload",
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    headers = _trusted_headers(csrf_token=csrf_token)
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

    response = web_client.post(
        UPLOAD_PATH,
        content=body_chunks,
        headers=headers,
    )

    assert "content-length" not in response.request.headers
    assert response.request.headers.get("transfer-encoding") == "chunked"
    assert response.status_code == 411
    assert response.headers.get(UPSTREAM_HEADER_NAME) is None


def test_phase0_citation_link_redirect_preserves_target_and_records_invocation(
    web_client: httpx.Client,
) -> None:
    _login(web_client, subject="phase0-citation-resolver")

    resolve_response = web_client.get(
        CITATION_RESOLVE_PATH,
        headers={"Host": PHASE0_TRUSTED_HOST},
    )

    assert resolve_response.status_code == 307
    _assert_api_upstream(resolve_response)
    assert resolve_response.headers.get("location") == RESERVED_CITATION_TARGET

    target_parts = urlsplit(resolve_response.headers["location"])
    assert target_parts.scheme == "https"
    assert target_parts.hostname == "fixtures.invalid"
    assert parse_qs(target_parts.query) == {
        "anchor": ["anchor-agenda-001"],
        "view": ["source"],
    }
    assert target_parts.fragment == "highlight=anchor-agenda-001"

    invocation_id = resolve_response.headers.get(CITATION_INVOCATION_HEADER_NAME)
    assert isinstance(invocation_id, str)
    assert invocation_id

    invocation_response = web_client.get(
        f"{CITATION_INVOCATION_PATH_PREFIX}/{quote(invocation_id, safe='')}",
        headers={"Host": PHASE0_TRUSTED_HOST},
    )
    assert invocation_response.status_code == 200
    _assert_api_upstream(invocation_response)
    invocation = invocation_response.json()
    assert invocation.get("invocation_id") == invocation_id
    assert invocation.get("citation_id") == CITATION_ID
    assert invocation.get("target_url") == RESERVED_CITATION_TARGET
