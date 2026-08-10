"""Regression checks for the Phase 3 public error envelope."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.api_errors import ApiProblem, install_api_problem_handler


def test_phase3_problem_handler_does_not_change_unrelated_http_errors() -> None:
    app = FastAPI()
    install_api_problem_handler(app)

    @app.get("/phase3")
    def phase3_error() -> None:
        raise ApiProblem(403, "forbidden", "request is not permitted")

    response = TestClient(app).get("/phase3")
    assert response.status_code == 403
    assert response.json() == {
        "code": "forbidden",
        "detail": "request is not permitted",
    }


def test_problem_fields_are_bounded_before_a_route_can_leak_them() -> None:
    for status_code, code, detail in (
        (200, "invalid", "not an error"),
        (400, "", "missing code"),
        (400, "x" * 129, "long code"),
        (400, "invalid", "x" * 1_001),
    ):
        try:
            ApiProblem(status_code, code, detail)
        except ValueError:
            continue
        raise AssertionError("invalid API problem was accepted")


def test_phase3_validation_errors_use_the_same_bounded_public_envelope() -> None:
    class _Payload(BaseModel):
        name: str = Field(min_length=1)

    app = FastAPI()
    install_api_problem_handler(app)

    @app.post("/phase3")
    def phase3_validation(payload: _Payload) -> dict[str, str]:
        return {"name": payload.name}

    response = TestClient(app).post("/phase3", json={"name": ""})
    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_request",
        "detail": "request is invalid",
    }
