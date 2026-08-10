"""Security-focused unit tests for the Phase 3 same-origin boundary."""

from __future__ import annotations

import logging

import pytest

from app.security import (
    BrowserSecurityPolicy,
    InvalidCsrfTokenError,
    UntrustedOriginError,
    UntrustedOriginalHostError,
    derive_csrf_token,
    issue_opaque_token,
    require_pre_auth_request,
    require_unsafe_authenticated_request,
    secret_hash,
)


pytestmark = pytest.mark.security


def test_forged_origin_cannot_bypass_a_valid_session_bound_csrf_token() -> None:
    policy = BrowserSecurityPolicy(
        public_origin="https://meet.example.test",
        public_host="meet.example.test",
        cookie_secure=True,
    )
    session_token = issue_opaque_token()
    csrf_token = derive_csrf_token(session_token)

    with pytest.raises(UntrustedOriginError):
        require_unsafe_authenticated_request(
            policy,
            origin="https://attacker.example.test",
            original_host=policy.public_host,
            csrf_token=csrf_token,
            csrf_secret_hash=secret_hash(csrf_token),
        )


def test_forged_proxy_host_cannot_bypass_a_valid_origin_and_csrf_token() -> None:
    policy = BrowserSecurityPolicy(
        public_origin="https://meet.example.test",
        public_host="meet.example.test",
    )
    session_token = issue_opaque_token()
    csrf_token = derive_csrf_token(session_token)

    with pytest.raises(UntrustedOriginalHostError):
        require_unsafe_authenticated_request(
            policy,
            origin=policy.public_origin,
            original_host="attacker.example.test",
            csrf_token=csrf_token,
            csrf_secret_hash=secret_hash(csrf_token),
        )


def test_pre_auth_has_no_originless_or_wildcard_escape_hatch() -> None:
    policy = BrowserSecurityPolicy(
        public_origin="https://meet.example.test",
        public_host="meet.example.test",
    )

    for origin in (None, "*", "https://meet.example.test.evil"):
        with pytest.raises(UntrustedOriginError):
            require_pre_auth_request(
                policy,
                origin=origin,
                original_host=policy.public_host,
            )


@pytest.mark.parametrize(
    "origin",
    (
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "https://localhost:443",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "https://127.0.0.1:443",
    ),
)
def test_production_policy_rejects_every_local_origin_variant(origin: str) -> None:
    policy = BrowserSecurityPolicy(
        public_origin="https://meet.example.test",
        public_host="meet.example.test",
    )
    with pytest.raises(UntrustedOriginError):
        require_pre_auth_request(
            policy,
            origin=origin,
            original_host=policy.public_host,
        )


@pytest.mark.parametrize(
    "original_host",
    (
        "localhost",
        "localhost:3000",
        "localhost:5173",
        "localhost:443",
        "127.0.0.1",
        "127.0.0.1:3000",
        "127.0.0.1:5173",
        "127.0.0.1:443",
    ),
)
def test_production_policy_rejects_every_local_original_host_variant(
    original_host: str,
) -> None:
    policy = BrowserSecurityPolicy(
        public_origin="https://meet.example.test",
        public_host="meet.example.test",
    )
    with pytest.raises(UntrustedOriginalHostError):
        require_pre_auth_request(
            policy,
            origin=policy.public_origin,
            original_host=original_host,
        )


def test_csrf_verifier_rejects_tokens_from_another_rotated_session() -> None:
    policy = BrowserSecurityPolicy(
        public_origin="https://meet.example.test",
        public_host="meet.example.test",
    )
    old_token = derive_csrf_token(issue_opaque_token())
    new_token = derive_csrf_token(issue_opaque_token())

    with pytest.raises(InvalidCsrfTokenError):
        require_unsafe_authenticated_request(
            policy,
            origin=policy.public_origin,
            original_host=policy.public_host,
            csrf_token=old_token,
            csrf_secret_hash=secret_hash(new_token),
        )


def test_security_helpers_do_not_log_raw_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    session_token = issue_opaque_token()
    csrf_token = derive_csrf_token(session_token)
    _ = secret_hash(csrf_token)

    assert caplog.records == []
