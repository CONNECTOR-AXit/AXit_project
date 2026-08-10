"""Offline checks for the opt-in, one-call online Grok smoke runner."""

from __future__ import annotations

import json
from collections.abc import Mapping

from app.grok_smoke import main, run_online_smoke, synthetic_rag_anchors


class _CountingTransport:
    def __init__(self) -> None:
        self.calls = 0

    def create_response(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        self.calls += 1
        anchors = synthetic_rag_anchors()
        document = {
            "sections": [
                {
                    "heading": "이미지 부유물 처리",
                    "items": [
                        {
                            "text": f"{anchor.participant}의 Marine Snow 처리 의견을 요약했다.",
                            "source_anchor_ids": [str(anchor.id)],
                            "supports": [
                                {
                                    "source_anchor_id": str(anchor.id),
                                    "exact_quote": anchor.exact_quote,
                                }
                            ],
                        }
                        for anchor in anchors[::2]
                    ],
                }
            ]
        }
        assert payload["store"] is False
        assert payload["tools"] == []
        assert payload["max_output_tokens"] == 4000
        return {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(document, ensure_ascii=False),
                        }
                    ],
                }
            ],
        }


def test_online_smoke_contract_performs_exactly_one_call_with_synthetic_data() -> None:
    transport = _CountingTransport()

    result = run_online_smoke(transport)

    assert transport.calls == 1
    assert result["online"] is True
    assert result["korean_output"] is True
    assert result["participants"] == 5
    assert result["covered_participants"] == 5
    assert result["unique_input_anchors"] == 10
    assert result["unique_output_items"] == 5
    assert result["canonical_persistence_attempted"] is False


def test_synthetic_meeting_input_is_realistic_and_non_repetitive() -> None:
    anchors = synthetic_rag_anchors()

    assert len({anchor.exact_quote for anchor in anchors}) == len(anchors)
    participants = {anchor.participant for anchor in anchors}
    assert len(participants) == 5
    assert all(sum(anchor.participant == participant for anchor in anchors) == 2 for participant in participants)
    topic_terms = ("Marine Snow", "Occlusion", "수중", "가림", "산란", "복원")
    assert all(any(term in anchor.exact_quote for term in topic_terms) for anchor in anchors)


def test_online_smoke_cli_refuses_to_start_without_acknowledgement() -> None:
    assert main({"XAI_API_KEY": "synthetic-test-key"}) == 2
