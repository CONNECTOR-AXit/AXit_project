"""Durable local authentication backed by ``users`` and ``auth_sessions``.

This service intentionally returns small value objects rather than FastAPI
responses.  The API adapter owns cookies and HTTP error mapping; this module
owns Argon2id verification, opaque-token rotation, and database lifetime
rules.  It never logs credentials or bearer material.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from psycopg.rows import dict_row

from app.activity_policy import build_event_key
from app.activity_service import ActivityService
from app.security import (
    BrowserSecurityPolicy,
    derive_csrf_token,
    issue_opaque_token,
    secret_hash,
    verify_secret,
)


class AuthenticationError(PermissionError):
    """Base class for authentication failures safe to expose generically."""


class InvalidCredentialsError(AuthenticationError):
    """Credentials did not identify a valid current account."""


class SessionAuthenticationError(AuthenticationError):
    """A session token is missing, expired, revoked, or no longer valid."""


class EmailAlreadyRegisteredError(ValueError):
    """Registration conflicts with an existing normalized email address."""


class RegistrationValidationError(ValueError):
    """Registration fields are outside the durable data contract."""


@dataclass(frozen=True, slots=True)
class UserRecord:
    """Public user data that is safe for API response serialization."""

    id: UUID
    email: str
    display_name: str


@dataclass(frozen=True, slots=True)
class LoginResult:
    """One freshly rotated browser session and its public user record."""

    user: UserRecord
    session_id: UUID
    session_token: str = field(repr=False)
    csrf_token: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """Verified DB session context for one request.

    The raw cookie token is intentionally excluded from ``repr`` so ordinary
    debugging cannot accidentally expose it in logs.
    """

    id: UUID
    user: UserRecord
    session_token: str = field(repr=False)
    csrf_secret_hash: str = field(repr=False)
    expires_at: datetime


_DEFAULT_PASSWORD_HASHER = PasswordHasher()
# The same slow verification path for unknown users avoids a simple account
# enumeration timing oracle.  It is not a real credential and is never used
# as a database value.
_DUMMY_PASSWORD_HASH = _DEFAULT_PASSWORD_HASHER.hash("axit-not-a-user-password")


class AuthService:
    """Persist local credentials and DB-backed opaque browser sessions."""

    def __init__(
        self,
        *,
        session_ttl: timedelta = timedelta(days=7),
        password_hasher: PasswordHasher | None = None,
        activity_service: ActivityService | None = None,
    ) -> None:
        if session_ttl <= timedelta(0):
            raise ValueError("session_ttl must be positive")
        self._session_ttl = session_ttl
        self._password_hasher = password_hasher or _DEFAULT_PASSWORD_HASHER
        self._activities = activity_service or ActivityService()

    def register(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        email: str,
        password: str,
        display_name: str,
    ) -> UserRecord:
        """Create a local account with an Argon2id password verifier."""

        normalized_email = _normalize_email(email)
        normalized_display_name = _normalize_display_name(display_name)
        _validate_password(password)
        password_hash = self._password_hasher.hash(password)
        user_id = uuid4()
        try:
            with connection.transaction():
                with connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute(
                        """
                        INSERT INTO users (id, email, password_hash, display_name)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id, email, display_name
                        """,
                        (user_id, normalized_email, password_hash, normalized_display_name),
                    )
                    row = _require_row(cursor.fetchone(), "registered user")
                    cursor.execute(
                        "INSERT INTO user_profiles (user_id) VALUES (%s)",
                        (user_id,),
                    )
                    cursor.execute(
                        """INSERT INTO notification_preferences(user_id,kind,channel,enabled)
                           SELECT %s, kind, channel, channel = 'in_app'
                           FROM (VALUES ('analysis_completed'),('mention'),('comment')) kinds(kind)
                           CROSS JOIN (VALUES ('in_app'),('email_intent')) channels(channel)""",
                        (user_id,),
                    )
                    self._activities.record(
                        cursor,
                        event_key=build_event_key("account.registered", user_id=user_id),
                        event_type="account.registered",
                        actor_id=user_id,
                        scope_type="personal",
                        audience_user_id=user_id,
                        entity_type="account",
                        entity_id=user_id,
                    )
        except psycopg.errors.UniqueViolation as error:
            raise EmailAlreadyRegisteredError("email is already registered") from error
        return _user_from_row(row)

    def login(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        email: str,
        password: str,
    ) -> LoginResult:
        """Verify a password then revoke old sessions and issue one new pair.

        All active sessions for the user are revoked in the same transaction.
        Concurrent logins therefore serialize into a deliberate last-login-wins
        policy instead of leaving a session fixation window.
        """

        normalized_email = _normalize_email_for_login(email)
        _validate_login_password(password)
        raw_session_token = issue_opaque_token()
        csrf_token = derive_csrf_token(raw_session_token)
        session_id = uuid4()

        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, email, password_hash, display_name
                    FROM users
                    WHERE email = %s
                    FOR UPDATE
                    """,
                    (normalized_email,),
                )
                row = cursor.fetchone()
                password_hash = (
                    str(row["password_hash"])
                    if row is not None
                    else _DUMMY_PASSWORD_HASH
                )
                if not _verify_password(self._password_hasher, password_hash, password):
                    raise InvalidCredentialsError("invalid credentials")
                if row is None:
                    # ``_verify_password`` still ran for a non-existent user.
                    raise InvalidCredentialsError("invalid credentials")

                user = _user_from_row(row)
                if self._password_hasher.check_needs_rehash(password_hash):
                    cursor.execute(
                        "UPDATE users SET password_hash = %s WHERE id = %s",
                        (self._password_hasher.hash(password), user.id),
                    )
                cursor.execute(
                    """
                    UPDATE auth_sessions
                    SET revoked_at = clock_timestamp()
                    WHERE user_id = %s AND revoked_at IS NULL
                    """,
                    (user.id,),
                )
                cursor.execute(
                    """
                    INSERT INTO auth_sessions (
                        id, token_hash, csrf_secret_hash, user_id, expires_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        clock_timestamp() + %s
                    )
                    RETURNING expires_at
                    """,
                    (
                        session_id,
                        secret_hash(raw_session_token),
                        secret_hash(csrf_token),
                        user.id,
                        self._session_ttl,
                    ),
                )
                expires_row = _require_row(cursor.fetchone(), "new auth session")

        return LoginResult(
            user=user,
            session_id=session_id,
            session_token=raw_session_token,
            csrf_token=csrf_token,
            expires_at=_require_datetime(expires_row["expires_at"], "session expiry"),
        )

    def authenticate(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_token: str | None,
    ) -> AuthenticatedSession:
        """Resolve only a currently active, unexpired opaque session token."""

        if not session_token:
            raise SessionAuthenticationError("authentication required")
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT session_row.id AS session_id,
                       session_row.csrf_secret_hash,
                       session_row.expires_at,
                       user_row.id AS user_id,
                       user_row.email,
                       user_row.display_name
                FROM auth_sessions AS session_row
                JOIN users AS user_row ON user_row.id = session_row.user_id
                WHERE session_row.token_hash = %s
                  AND session_row.revoked_at IS NULL
                  AND session_row.expires_at > clock_timestamp()
                """,
                (secret_hash(session_token),),
            )
            row = cursor.fetchone()
        if row is None:
            raise SessionAuthenticationError("authentication required")
        return AuthenticatedSession(
            id=_require_uuid(row["session_id"], "session id"),
            user=UserRecord(
                id=_require_uuid(row["user_id"], "user id"),
                email=_require_text(row["email"], "email"),
                display_name=_require_text(row["display_name"], "display name"),
            ),
            session_token=session_token,
            csrf_secret_hash=_require_hash(row["csrf_secret_hash"], "CSRF verifier"),
            expires_at=_require_datetime(row["expires_at"], "session expiry"),
        )

    def csrf_token_for(self, authenticated: AuthenticatedSession) -> str:
        """Return a derived token only when the stored verifier still matches."""

        csrf_token = derive_csrf_token(authenticated.session_token)
        if not verify_secret(csrf_token, authenticated.csrf_secret_hash):
            raise SessionAuthenticationError("authentication required")
        return csrf_token

    def require_unsafe_request(
        self,
        policy: BrowserSecurityPolicy,
        authenticated: AuthenticatedSession,
        *,
        origin: str | None,
        original_host: str | None,
        csrf_token: str | None,
    ) -> None:
        """Check a request token against this exact authenticated session."""

        from app.security import require_unsafe_authenticated_request

        require_unsafe_authenticated_request(
            policy,
            origin=origin,
            original_host=original_host,
            csrf_token=csrf_token,
            csrf_secret_hash=authenticated.csrf_secret_hash,
        )

    def logout(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        authenticated: AuthenticatedSession,
    ) -> None:
        """Revoke the exact verified session without exposing token material."""

        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE auth_sessions
                    SET revoked_at = clock_timestamp()
                    WHERE id = %s AND revoked_at IS NULL
                    """,
                    (authenticated.id,),
                )
                if cursor.rowcount != 1:
                    raise SessionAuthenticationError("authentication required")


def _normalize_email(email: str) -> str:
    normalized = _normalize_email_for_login(email)
    if len(normalized) < 3 or len(normalized) > 320 or "@" not in normalized:
        raise RegistrationValidationError("email must be a valid address")
    return normalized


def _normalize_email_for_login(email: str) -> str:
    if not isinstance(email, str):
        raise InvalidCredentialsError("invalid credentials")
    normalized = email.strip().lower()
    if not normalized or len(normalized) > 320 or any(ord(char) < 32 for char in normalized):
        raise InvalidCredentialsError("invalid credentials")
    return normalized


def _normalize_display_name(display_name: str) -> str:
    if not isinstance(display_name, str):
        raise RegistrationValidationError("display name is required")
    normalized = display_name.strip()
    if not normalized or len(normalized) > 200 or "\x00" in normalized:
        raise RegistrationValidationError("display name is invalid")
    return normalized


def _validate_password(password: str) -> None:
    if not isinstance(password, str) or not 8 <= len(password) <= 1_024:
        raise RegistrationValidationError("password must be between 8 and 1024 characters")


def _validate_login_password(password: str) -> None:
    if not isinstance(password, str) or not 1 <= len(password) <= 1_024:
        raise InvalidCredentialsError("invalid credentials")


def _verify_password(hasher: PasswordHasher, password_hash: str, password: str) -> bool:
    try:
        return bool(hasher.verify(password_hash, password))
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def _require_row(row: dict[str, Any] | None, label: str) -> dict[str, Any]:
    if row is None:
        raise RuntimeError(f"{label} was not returned")
    return row


def _user_from_row(row: dict[str, Any]) -> UserRecord:
    return UserRecord(
        id=_require_uuid(row["id"], "user id"),
        email=_require_text(row["email"], "email"),
        display_name=_require_text(row["display_name"], "display name"),
    )


def _require_uuid(value: object, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise RuntimeError(f"persisted {label} must be UUID")


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"persisted {label} must be non-empty text")
    return value


def _require_hash(value: object, label: str) -> str:
    text = _require_text(value, label)
    if len(text) != 64:
        raise RuntimeError(f"persisted {label} must be a SHA-256 hex digest")
    return text


def _require_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError(f"persisted {label} must be datetime")
    return value
