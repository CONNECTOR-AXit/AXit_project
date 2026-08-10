"""Unit coverage for the Phase 3 browser security boundary."""

from __future__ import annotations

import pytest
from argon2 import PasswordHasher

from app.security import (
    BrowserSecurityPolicy,
    InvalidCsrfTokenError,
    MissingCsrfTokenError,
    UntrustedOriginError,
    UntrustedOriginalHostError,
    derive_csrf_token,
    issue_opaque_token,
    require_pre_auth_request,
    require_trusted_original_host,
    require_unsafe_authenticated_request,
    secret_hash,
    session_cookie,
)


def _policy() -> BrowserSecurityPolicy:
    return BrowserSecurityPolicy(
        public_origin="https://app.example.test",
        public_host="app.example.test",
        cookie_secure=True,
    )


def test_opaque_session_and_csrf_are_high_entropy_and_bound_to_one_session() -> None:
    first = issue_opaque_token()
    second = issue_opaque_token()

    assert first != second
    assert len(first) >= 40
    assert derive_csrf_token(first) == derive_csrf_token(first)
    assert derive_csrf_token(first) != derive_csrf_token(second)
    assert len(secret_hash(first)) == 64


def test_password_hasher_defaults_to_argon2id() -> None:
    password_hash = PasswordHasher().hash("phase3-unit-password")

    assert password_hash.startswith("$argon2id$")


def test_pre_auth_requires_exact_origin_and_proxy_attested_host() -> None:
    policy = _policy()
    require_pre_auth_request(
        policy,
        origin="https://app.example.test",
        original_host="app.example.test",
    )

    with pytest.raises(UntrustedOriginalHostError):
        require_pre_auth_request(
            policy,
            origin="https://app.example.test",
            original_host="evil.example.test",
        )
    with pytest.raises(UntrustedOriginError):
        require_pre_auth_request(
            policy,
            origin="https://evil.example.test",
            original_host="app.example.test",
        )
    with pytest.raises(UntrustedOriginalHostError):
        require_trusted_original_host(policy, None)


def test_unsafe_request_requires_current_csrf_verifier_after_transport_checks() -> None:
    policy = _policy()
    session_token = issue_opaque_token()
    csrf_token = derive_csrf_token(session_token)
    csrf_secret_hash = secret_hash(csrf_token)

    require_unsafe_authenticated_request(
        policy,
        origin=policy.public_origin,
        original_host=policy.public_host,
        csrf_token=csrf_token,
        csrf_secret_hash=csrf_secret_hash,
    )
    with pytest.raises(MissingCsrfTokenError):
        require_unsafe_authenticated_request(
            policy,
            origin=policy.public_origin,
            original_host=policy.public_host,
            csrf_token=None,
            csrf_secret_hash=csrf_secret_hash,
        )
    with pytest.raises(InvalidCsrfTokenError):
        require_unsafe_authenticated_request(
            policy,
            origin=policy.public_origin,
            original_host=policy.public_host,
            csrf_token="forged-token",
            csrf_secret_hash=csrf_secret_hash,
        )
    with pytest.raises(UntrustedOriginError):
        require_unsafe_authenticated_request(
            policy,
            origin="https://evil.example.test",
            original_host=policy.public_host,
            csrf_token=csrf_token,
            csrf_secret_hash=csrf_secret_hash,
        )


def test_cookie_instruction_is_host_only_http_only_lax_and_secure_by_policy() -> None:
    policy = _policy()
    cookie = session_cookie(policy, "opaque-token")

    assert cookie.name == "axit_session"
    assert cookie.value == "opaque-token"
    assert cookie.path == "/"
    assert cookie.httponly is True
    assert cookie.samesite == "lax"
    assert cookie.secure is True
    # Domain is intentionally absent from the dataclass/adapter instruction,
    # which leaves the browser cookie host-only.
    assert not hasattr(cookie, "domain")
