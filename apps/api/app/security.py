"""Small, explicit security primitives for the durable Phase 3 API.

The FastAPI route adapter is deliberately kept out of this module.  It reads
headers/cookies and maps these typed errors to the frozen API error shape,
while this module owns the security decisions themselves.  In particular, no
raw password, session token, CSRF token, or source text is ever logged here.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Final


SESSION_COOKIE_NAME: Final = "axit_session"
CSRF_HEADER_NAME: Final = "X-CSRF-Token"
ORIGINAL_HOST_HEADER_NAME: Final = "X-AXit-Original-Host"
DEFAULT_SESSION_TTL: Final = timedelta(days=7)
_CSRF_DERIVATION_LABEL: Final = b"axit-csrf-v1"


class SecurityPolicyError(PermissionError):
    """Base error for a rejected browser transport security property."""


class UntrustedOriginalHostError(SecurityPolicyError):
    """The trusted proxy did not attest to the configured public host."""


class UntrustedOriginError(SecurityPolicyError):
    """A browser mutation did not originate from the configured origin."""


class MissingCsrfTokenError(SecurityPolicyError):
    """An authenticated unsafe request omitted its synchronizer token."""


class InvalidCsrfTokenError(SecurityPolicyError):
    """An authenticated unsafe request supplied the wrong synchronizer token."""


@dataclass(frozen=True, slots=True)
class BrowserSecurityPolicy:
    """Configured same-origin policy shared by every Phase 3 route.

    ``public_host`` is deliberately checked from the proxy-injected header,
    not the ambient Host header.  The public frontend gateway removes user-controlled
    forwarded identity headers before the API sees the request; the only
    forwarding fact accepted here is its fixed original-host attestation.
    """

    public_origin: str
    public_host: str
    cookie_secure: bool = False
    cookie_name: str = SESSION_COOKIE_NAME
    session_ttl: timedelta = DEFAULT_SESSION_TTL

    def __post_init__(self) -> None:
        if not self.public_origin.strip():
            raise ValueError("public_origin must not be blank")
        if not self.public_host.strip():
            raise ValueError("public_host must not be blank")
        if not self.cookie_name.strip():
            raise ValueError("cookie_name must not be blank")
        if self.session_ttl <= timedelta(0):
            raise ValueError("session_ttl must be positive")


@dataclass(frozen=True, slots=True)
class SessionCookie:
    """A route-adapter-friendly host-only session-cookie instruction."""

    name: str
    value: str
    max_age: int
    secure: bool
    httponly: bool = True
    samesite: str = "lax"
    path: str = "/"


def issue_opaque_token() -> str:
    """Return a high-entropy opaque browser session token.

    The raw token exists only at issuance and while processing the request.
    Persistence always uses :func:`secret_hash` instead.
    """

    return secrets.token_urlsafe(32)


def secret_hash(value: str) -> str:
    """Hash a security secret without retaining a reversible database value."""

    if not value:
        raise ValueError("secret must not be empty")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def derive_csrf_token(session_token: str) -> str:
    """Derive a synchronizer token bound to one opaque session token.

    A CSRF token does not need a second persistent plaintext secret.  The
    browser receives it only through the authenticated same-origin endpoint;
    the database retains a SHA-256 verifier.  Deriving it from the already
    high-entropy HttpOnly session token avoids storing a recoverable CSRF
    secret while still making rotation of the session rotate the CSRF token.
    """

    if not session_token:
        raise ValueError("session token must not be empty")
    return hmac.new(
        session_token.encode("utf-8"),
        _CSRF_DERIVATION_LABEL,
        hashlib.sha256,
    ).hexdigest()


def verify_secret(value: str, expected_hash: str) -> bool:
    """Constant-time verification against a stored SHA-256 digest."""

    if not value or len(expected_hash) != 64:
        return False
    return hmac.compare_digest(secret_hash(value), expected_hash)


def _is_allowed_host(original_host: str | None, public_host: str) -> bool:
    return original_host == public_host


def _is_allowed_origin(origin: str | None, public_origin: str) -> bool:
    return origin == public_origin


def require_trusted_original_host(
    policy: BrowserSecurityPolicy,
    original_host: str | None,
) -> None:
    """Require the proxy-attested public host for every API request."""

    if not _is_allowed_host(original_host, policy.public_host):
        raise UntrustedOriginalHostError("untrusted original host")


def require_pre_auth_request(
    policy: BrowserSecurityPolicy,
    *,
    origin: str | None,
    original_host: str | None,
) -> None:
    """Validate register/login transport before any credential lookup."""

    require_trusted_original_host(policy, original_host)
    if not _is_allowed_origin(origin, policy.public_origin):
        raise UntrustedOriginError("untrusted origin")


def require_unsafe_authenticated_request(
    policy: BrowserSecurityPolicy,
    *,
    origin: str | None,
    original_host: str | None,
    csrf_token: str | None,
    csrf_secret_hash: str,
) -> None:
    """Require exact origin/host and a session-bound CSRF verifier."""

    require_pre_auth_request(policy, origin=origin, original_host=original_host)
    if csrf_token is None or not csrf_token:
        raise MissingCsrfTokenError("missing CSRF token")
    if not verify_secret(csrf_token, csrf_secret_hash):
        raise InvalidCsrfTokenError("invalid CSRF token")


def session_cookie(policy: BrowserSecurityPolicy, session_token: str) -> SessionCookie:
    """Create the fixed host-only cookie shape expected by the route adapter."""

    if not session_token:
        raise ValueError("session token must not be empty")
    return SessionCookie(
        name=policy.cookie_name,
        value=session_token,
        max_age=int(policy.session_ttl.total_seconds()),
        secure=policy.cookie_secure,
    )
