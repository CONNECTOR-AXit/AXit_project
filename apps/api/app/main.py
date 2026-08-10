"""FastAPI entry point with a disposable Phase 0 harness and frozen contract.

The ``/api/__phase0`` routes deliberately remain in-memory transport proof
fixtures.  The separately defined ``/api`` durable surface now includes the
Phase 3 text flow and the promoted Phase 4 local file/original path. Neither
surface auto-runs migrations on import.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import APIRouter, FastAPI, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, RedirectResponse

from app.api_errors import install_api_problem_handler
from app.contracts import contract_router, install_contract_only_exception_handler
from app.db import database_is_ready


PHASE0_PREFIX: Final = "/api/__phase0"
SESSION_COOKIE_NAME: Final = "phase0_session"
CSRF_HEADER_NAME: Final = "X-CSRF-Token"
ORIGINAL_HOST_HEADER_NAME: Final = "X-AXit-Original-Host"
UPSTREAM_HEADER_NAME: Final = "X-Phase0-Upstream"
UPSTREAM_HEADER_VALUE: Final = "api"
CITATION_INVOCATION_HEADER_NAME: Final = "X-Phase0-Citation-Invocation"
MAX_UPLOAD_BYTES: Final = 200 * 1024 * 1024
UPLOAD_CHUNK_BYTES: Final = 64 * 1024

CITATION_ID: Final = "phase0-citation-001"
CITATION_TARGET_URL: Final = (
    "https://fixtures.invalid/viewer/revision-agenda-001"
    "?anchor=anchor-agenda-001&view=source"
    "#highlight=anchor-agenda-001"
)

PUBLIC_ORIGIN: Final = os.environ.get("PUBLIC_ORIGIN", "http://localhost:3000")
PUBLIC_HOST: Final = os.environ.get("PUBLIC_HOST", "localhost:3000")


def _read_boolean_environment(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise RuntimeError(f"{name} must be either 'true' or 'false'")


SESSION_COOKIE_SECURE: Final = _read_boolean_environment(
    "SESSION_COOKIE_SECURE",
    default=False,
)


class _Phase0UpstreamHeaderMiddleware(BaseHTTPMiddleware):
    """Mark every response as originating from the FastAPI process."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith(PHASE0_PREFIX):
            response.headers[UPSTREAM_HEADER_NAME] = UPSTREAM_HEADER_VALUE
        return response


class LoginRequest(BaseModel):
    """Test-only login input."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=128)


class MutationRequest(BaseModel):
    """Test-only mutation input."""

    model_config = ConfigDict(extra="forbid")

    operation: str = Field(min_length=1, max_length=128)


class CsrfResponse(BaseModel):
    csrf_token: str


class SessionResponse(BaseModel):
    authenticated: bool
    cookie_forwarded: bool
    session_cookie_sha256: str


class MutationResponse(BaseModel):
    mutated: bool


class UploadResponse(BaseModel):
    bytes_received: int
    sha256: str


class CitationResponse(BaseModel):
    citation_id: str
    target_url: str
    invocation_id: str


class HealthResponse(BaseModel):
    status: str
    database: str


@dataclass(frozen=True, slots=True)
class _Session:
    subject: str
    csrf_token: str


@dataclass(frozen=True, slots=True)
class _AuthenticatedSession:
    session_cookie_sha256: str
    session: _Session


class _Phase0State:
    """Concurrency-safe in-memory state used only by the transport proof."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions_by_hash: dict[str, _Session] = {}
        self._session_hash_by_subject: dict[str, str] = {}
        self._citation_invocations: dict[str, CitationResponse] = {}

    async def rotate_session(self, subject: str) -> tuple[str, _Session]:
        session_cookie = secrets.token_urlsafe(32)
        session_hash = _sha256_text(session_cookie)
        session = _Session(subject=subject, csrf_token=secrets.token_urlsafe(32))

        async with self._lock:
            previous_hash = self._session_hash_by_subject.get(subject)
            if previous_hash is not None:
                self._sessions_by_hash.pop(previous_hash, None)
            self._sessions_by_hash[session_hash] = session
            self._session_hash_by_subject[subject] = session_hash

        return session_cookie, session

    async def find_session(self, session_cookie: str) -> _AuthenticatedSession | None:
        session_hash = _sha256_text(session_cookie)
        async with self._lock:
            session = self._sessions_by_hash.get(session_hash)
        if session is None:
            return None
        return _AuthenticatedSession(
            session_cookie_sha256=session_hash,
            session=session,
        )

    async def record_citation_invocation(self) -> CitationResponse:
        invocation = CitationResponse(
            citation_id=CITATION_ID,
            target_url=CITATION_TARGET_URL,
            invocation_id=secrets.token_urlsafe(24),
        )
        async with self._lock:
            self._citation_invocations[invocation.invocation_id] = invocation
        return invocation

    async def find_citation_invocation(
        self,
        invocation_id: str,
    ) -> CitationResponse | None:
        async with self._lock:
            return self._citation_invocations.get(invocation_id)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_original_host(request: Request) -> None:
    if request.headers.get(ORIGINAL_HOST_HEADER_NAME) != PUBLIC_HOST:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="untrusted original host",
        )


def _require_unsafe_transport_headers(request: Request) -> None:
    _require_original_host(request)
    if request.headers.get("Origin") != PUBLIC_ORIGIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="untrusted origin",
        )


async def _require_session(request: Request) -> _AuthenticatedSession:
    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    authenticated = await _state.find_session(session_cookie)
    if authenticated is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid session",
        )
    return authenticated


async def _require_csrf(
    request: Request,
    authenticated: _AuthenticatedSession,
) -> None:
    submitted_token = request.headers.get(CSRF_HEADER_NAME)
    if submitted_token is None or not hmac.compare_digest(
        submitted_token,
        authenticated.session.csrf_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid CSRF token",
        )


_state = _Phase0State()
_phase0_router = APIRouter(prefix=PHASE0_PREFIX, include_in_schema=False)


@_phase0_router.post(
    "/session/login",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def phase0_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
) -> None:
    _require_unsafe_transport_headers(request)
    session_cookie, _ = await _state.rotate_session(payload.subject)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_cookie,
        path="/",
        secure=SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


@_phase0_router.get("/session", response_model=SessionResponse)
async def phase0_session(request: Request) -> SessionResponse:
    _require_original_host(request)
    authenticated = await _require_session(request)
    return SessionResponse(
        authenticated=True,
        cookie_forwarded=True,
        session_cookie_sha256=authenticated.session_cookie_sha256,
    )


@_phase0_router.get("/csrf", response_model=CsrfResponse)
async def phase0_csrf(request: Request) -> CsrfResponse:
    _require_original_host(request)
    authenticated = await _require_session(request)
    return CsrfResponse(csrf_token=authenticated.session.csrf_token)


@_phase0_router.post("/mutation", response_model=MutationResponse)
async def phase0_mutation(
    payload: MutationRequest,
    request: Request,
) -> MutationResponse:
    _require_unsafe_transport_headers(request)
    authenticated = await _require_session(request)
    await _require_csrf(request, authenticated)
    return MutationResponse(mutated=bool(payload.operation))


@_phase0_router.post("/upload", response_model=UploadResponse)
async def phase0_upload(
    request: Request,
    file: Annotated[UploadFile, File()],
) -> UploadResponse:
    _require_unsafe_transport_headers(request)
    authenticated = await _require_session(request)
    await _require_csrf(request, authenticated)

    received = 0
    digest = hashlib.sha256()
    try:
        while chunk := await file.read(UPLOAD_CHUNK_BYTES):
            received += len(chunk)
            if received > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="file exceeds the Phase 0 transport limit",
                )
            digest.update(chunk)
    finally:
        await file.close()

    return UploadResponse(bytes_received=received, sha256=digest.hexdigest())


@_phase0_router.get(
    "/citations/{citation_id}/resolve",
    response_model=None,
)
async def phase0_resolve_citation(
    citation_id: str,
    request: Request,
) -> RedirectResponse:
    _require_original_host(request)
    await _require_session(request)
    if citation_id != CITATION_ID:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="citation not found",
        )
    invocation = await _state.record_citation_invocation()
    return RedirectResponse(
        url=invocation.target_url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={
            CITATION_INVOCATION_HEADER_NAME: invocation.invocation_id,
        },
    )


@_phase0_router.get(
    "/citation-invocations/{invocation_id}",
    response_model=CitationResponse,
)
async def phase0_citation_invocation(
    invocation_id: str,
    request: Request,
) -> CitationResponse:
    _require_original_host(request)
    await _require_session(request)
    invocation = await _state.find_citation_invocation(invocation_id)
    if invocation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="citation invocation not found",
        )
    return invocation


app = FastAPI(
    title="AXit Meeting RAG API",
    version="0.1.0-phase2",
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json",
)
app.add_middleware(_Phase0UpstreamHeaderMiddleware)
app.include_router(_phase0_router)
app.include_router(contract_router)
install_contract_only_exception_handler(app)
install_api_problem_handler(app, preserve_validation_prefix=PHASE0_PREFIX)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse | JSONResponse:
    if not database_is_ready():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "database": "unavailable"},
        )
    return HealthResponse(status="ok", database="ready")
