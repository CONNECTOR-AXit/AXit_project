"""Typed, non-leaky error responses for the durable Phase 3 API.

Phase 0 deliberately uses FastAPI's ordinary ``HTTPException`` response
shape as a disposable transport harness.  Production-facing Phase 3 routes
raise this separate exception instead, so they can consistently return the
public ``ErrorResponse`` envelope without changing the historical harness.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@dataclass
class ApiProblem(Exception):
    """A bounded error code and safe public detail for one API response."""

    status_code: int
    code: str
    detail: str

    def __post_init__(self) -> None:
        if not 400 <= self.status_code <= 599:
            raise ValueError("API problem status must be an HTTP error")
        if not self.code or len(self.code) > 128:
            raise ValueError("API problem code must be non-empty and bounded")
        if not self.detail or len(self.detail) > 1_000:
            raise ValueError("API problem detail must be non-empty and bounded")
        # ``contextlib`` attaches traceback/context attributes while a route
        # leaves a database context manager.  Exceptions therefore cannot be
        # frozen or slotted, even though the public payload itself is
        # immutable by convention.
        Exception.__init__(self, self.detail)


async def _api_problem_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render only the reviewed problem envelope, never exception internals."""

    if not isinstance(exc, ApiProblem):  # pragma: no cover - FastAPI dispatch guard
        raise exc
    del request
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "detail": exc.detail},
    )


def _problem_response(*, status_code: int, code: str, detail: str) -> JSONResponse:
    """Build one validated public problem response without exposing a cause."""

    problem = ApiProblem(status_code, code, detail)
    return JSONResponse(
        status_code=problem.status_code,
        content={"code": problem.code, "detail": problem.detail},
    )


def install_api_problem_handler(
    app: FastAPI,
    *,
    preserve_validation_prefix: str | None = None,
) -> None:
    """Install Phase 3 problem envelopes and optionally preserve a legacy route.

    FastAPI's default validation body exposes framework-specific field
    internals, while the public Phase 3 contract advertises ``ErrorResponse``.
    The disposable Phase 0 harness predates that contract, so its validation
    response can be deliberately left unchanged by passing its exact prefix.
    """

    async def validation_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        if not isinstance(exc, RequestValidationError):  # pragma: no cover - registry guard
            raise exc
        if (
            preserve_validation_prefix is not None
            and request.url.path.startswith(preserve_validation_prefix)
        ):
            return await request_validation_exception_handler(request, exc)
        return _problem_response(
            status_code=422,
            code="invalid_request",
            detail="request is invalid",
        )

    app.add_exception_handler(ApiProblem, _api_problem_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
