"""Evaluation gates for the Korean deterministic RAG meeting demo."""

from __future__ import annotations

from copy import deepcopy

import pytest

from tools.render_rag_meeting_demo import (
    DemoFixtureError,
    load_fixture,
    render_report,
    validate_fixture,
)


@pytest.mark.evaluation
def test_rag_meeting_demo_is_grounded_isolated_korean_and_offline() -> None:
    fixture = load_fixture()

    validate_fixture(fixture)
    report = render_report(fixture)

    assert fixture["provider"] == "mock"
    assert fixture["xai_called"] is False
    assert fixture["credential_persisted"] is False
    assert "## 참가자 원문 기반 요약" in report
    assert "## 외부 자료 조사" in report
    assert "https://arxiv.org/abs/2005.11401" in report
    assert "https://github.com/microsoft/graphrag" in report


@pytest.mark.evaluation
def test_rag_meeting_demo_rejects_ungrounded_summary_support() -> None:
    fixture = deepcopy(load_fixture())
    fixture["summary"]["items"][0]["supports"][0]["exact_quote"] = "근거를 바꾼 문장"

    with pytest.raises(DemoFixtureError, match="does not exactly match"):
        validate_fixture(fixture)


@pytest.mark.evaluation
def test_rag_meeting_demo_rejects_web_content_in_summary() -> None:
    fixture = deepcopy(load_fixture())
    fixture["summary"]["items"][0]["text"] += " https://example.invalid"

    with pytest.raises(DemoFixtureError, match="summary must not contain web URLs"):
        validate_fixture(fixture)


@pytest.mark.evaluation
def test_rag_meeting_demo_rejects_live_provider_or_credential_persistence() -> None:
    fixture = deepcopy(load_fixture())
    fixture["provider"] = "grok"

    with pytest.raises(DemoFixtureError, match="offline and mock-backed"):
        validate_fixture(fixture)

    fixture = deepcopy(load_fixture())
    fixture["credential_persisted"] = True
    with pytest.raises(DemoFixtureError, match="must never be persisted"):
        validate_fixture(fixture)
