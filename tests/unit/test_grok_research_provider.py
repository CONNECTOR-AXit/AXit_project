"""Regression coverage for GrokResearchProvider's citation-trust and
response-shape handling.

Both cases here were observed against the real xAI Responses API (not
imagined): a genuinely search-grounded citation whose URL the model retyped
with a trailing slash was rejected as foreign, and a "completed" response
that didn't carry exactly one output_text message permanently failed an
entire research generation instead of being retried.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from uuid import uuid4

import pytest

from app.grok_research_provider import GrokResearchProvider, GrokResearchProviderError
from app.summary_grounding import RuntimeSourceAnchor


class _StubTransport:
    def __init__(self, response: Mapping[str, object]) -> None:
        self._response = response
        self.payload: Mapping[str, object] | None = None

    def create_response(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        self.payload = payload
        return self._response


def _anchor(quote: str) -> RuntimeSourceAnchor:
    return RuntimeSourceAnchor(id=uuid4(), revision_id=uuid4(), exact_quote=quote)


def _completed_response(
    *, searched_url: str, cited_url: str
) -> tuple[dict[str, object], RuntimeSourceAnchor]:
    anchor = _anchor("서울의 인구는 약 950만 명이다.")
    finding = {
        "source_anchor_id": str(anchor.id),
        "source_claim_quote": anchor.exact_quote,
        "verdict": "supported",
        "explanation": "실제 통계와 일치합니다.",
        "web_sources": [{"url": cited_url, "title": "인구 통계"}],
    }
    return {
        "status": "completed",
        "output": [
            {
                "type": "web_search_call",
                "action": {"sources": [{"url": searched_url, "title": "인구 통계"}]},
            },
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": json.dumps({"findings": [finding]})}
                ],
            },
        ],
    }, anchor


def test_cosmetic_url_difference_is_still_trusted() -> None:
    response, anchor = _completed_response(
        searched_url="https://example.com/population",
        cited_url="https://example.com/population/",
    )
    transport = _StubTransport(response)
    provider = GrokResearchProvider(transport=transport)

    result = provider.generate_research((anchor,), snapshot_id=uuid4())

    assert len(result.fact_checks) == 1
    assert len(result.web_evidence) == 1
    assert transport.payload is not None
    assert transport.payload["include"] == ["web_search_call.action.sources"]
    # Persisted evidence keeps the tool's exact URL, not the model's retyped one.
    assert result.web_evidence[0].url == "https://example.com/population"


def test_genuinely_foreign_url_is_discarded_and_marked_unverifiable() -> None:
    response, anchor = _completed_response(
        searched_url="https://example.com/population",
        cited_url="https://not-searched.example/fabricated",
    )
    provider = GrokResearchProvider(transport=_StubTransport(response))

    result = provider.generate_research((anchor,), snapshot_id=uuid4())

    assert result.fact_checks[0].verdict == "unverifiable"
    assert result.fact_checks[0].web_evidence_ids == ()
    assert "provenance" in result.fact_checks[0].explanation
    assert all(evidence.url != "https://not-searched.example/fabricated" for evidence in result.web_evidence)


@pytest.mark.parametrize("citation_shape", ["annotation", "top_level"])
def test_official_alternate_citation_shapes_are_trusted(citation_shape: str) -> None:
    url = "https://python-docx.readthedocs.io/"
    response, anchor = _completed_response(searched_url=url, cited_url=url)
    response["output"] = [response["output"][1]]
    if citation_shape == "annotation":
        response["output"][0]["content"][0]["annotations"] = [
            {"type": "url_citation", "url": url, "title": "python-docx"}
        ]
    else:
        response["citations"] = [url]

    result = GrokResearchProvider(
        transport=_StubTransport(response)
    ).generate_research((anchor,), snapshot_id=uuid4())

    assert result.web_evidence[0].url == url


def test_response_without_exactly_one_message_is_retryable() -> None:
    anchor = _anchor("서울의 인구는 약 950만 명이다.")
    response = {
        "status": "completed",
        "output": [{"type": "reasoning", "summary": []}],
    }
    provider = GrokResearchProvider(transport=_StubTransport(response))

    with pytest.raises(GrokResearchProviderError) as excinfo:
        provider.generate_research((anchor,), snapshot_id=uuid4())

    assert excinfo.value.code == "grok_research_malformed_response"
    assert excinfo.value.retryable is True
