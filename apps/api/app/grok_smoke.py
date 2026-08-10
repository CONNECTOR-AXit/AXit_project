"""One-call online Grok smoke runner for a future approved experiment.

The runner is not invoked by the API, orchestrator, Compose, or test suite.  It
requires an explicit billing/data-transfer acknowledgement and reads the key
only from the launching process environment.  Its request uses synthetic RAG
meeting text, disables tools, and sets ``store`` to false through GrokProvider.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from typing import Final
from uuid import UUID

from app.grok_provider import (
    GrokProvider,
    GrokProviderError,
    GrokTransport,
    XaiResponsesTransport,
)
from app.summary_grounding import RuntimeSourceAnchor


_ACKNOWLEDGEMENT: Final = "I_ACKNOWLEDGE_XAI_BILLING_AND_DATA_TRANSFER"
_KOREAN: Final = re.compile(r"[가-힣]")


def synthetic_rag_anchors() -> tuple[RuntimeSourceAnchor, ...]:
    """Return distinct, realistic synthetic meeting notes for the one-call smoke."""

    revision_ids = tuple(
        UUID(f"10000000-0000-4000-8000-{index:012d}") for index in range(1, 6)
    )
    return (
        RuntimeSourceAnchor(
            id=UUID("20000000-0000-4000-8000-000000000001"),
            revision_id=revision_ids[0],
            exact_quote=(
                "지민: 수중드론 영상의 Marine Snow는 전경 입자와 후방 산란이 섞여 "
                "주 목표물의 윤곽을 가리므로 시간축 배경 모델을 기준선으로 삼자고 제안했다."
            ),
            participant="지민",
        ),
        RuntimeSourceAnchor(
            id=UUID("20000000-0000-4000-8000-000000000002"),
            revision_id=revision_ids[0],
            exact_quote=(
                "지민의 파일: 연속 프레임에서 순간적으로 나타나는 Marine Snow 입자를 검출한 뒤 "
                "안정적인 배경 추정과 인페인팅을 결합하는 처리 순서를 비교했다."
            ),
            participant="지민",
        ),
        RuntimeSourceAnchor(
            id=UUID("20000000-0000-4000-8000-000000000003"),
            revision_id=revision_ids[1],
            exact_quote=(
                "현우: Occlusion 정도를 입자 면적 비율과 목표물 경계 손실률로 나누어 "
                "라벨링하면 제거 성능과 목표물 보존 성능을 따로 평가할 수 있다고 말했다."
            ),
            participant="현우",
        ),
        RuntimeSourceAnchor(
            id=UUID("20000000-0000-4000-8000-000000000004"),
            revision_id=revision_ids[1],
            exact_quote=(
                "현우의 파일: 실제 수중 영상에서 관찰한 두 종류의 Marine Snow를 합성해 "
                "원본과 오염 영상의 짝을 만드는 벤치마크 구성을 정리했다."
            ),
            participant="현우",
        ),
        RuntimeSourceAnchor(
            id=UUID("20000000-0000-4000-8000-000000000005"),
            revision_id=revision_ids[2],
            exact_quote=(
                "소라: 작은 Marine Snow 마스크는 적응형 중간값 필터로 처리하고 큰 가림 영역은 "
                "주변 구조를 참조하는 인페인팅으로 복원하는 혼합 경로를 제안했다."
            ),
            participant="소라",
        ),
        RuntimeSourceAnchor(
            id=UUID("20000000-0000-4000-8000-000000000006"),
            revision_id=revision_ids[2],
            exact_quote=(
                "소라의 파일: 공간 특징과 푸리에 정보를 함께 쓰는 복원 방식이 입자 흔적과 "
                "저주파 안개를 분리하는 데 유용하다는 설계안을 담았다."
            ),
            participant="소라",
        ),
        RuntimeSourceAnchor(
            id=UUID("20000000-0000-4000-8000-000000000007"),
            revision_id=revision_ids[3],
            exact_quote=(
                "태윤: 드론 조명과 카메라 사이의 각도를 벌리고 노출을 고정해 후방 산란을 줄인 "
                "입력을 확보해야 후처리 모델의 오탐도 감소한다고 설명했다."
            ),
            participant="태윤",
        ),
        RuntimeSourceAnchor(
            id=UUID("20000000-0000-4000-8000-000000000008"),
            revision_id=revision_ids[3],
            exact_quote=(
                "태윤의 파일: 탁도, 조도, 이동 속도를 운항 로그와 동기화하고 조건별로 원본 프레임을 "
                "보존하는 수중드론 촬영 프로토콜을 제시했다."
            ),
            participant="태윤",
        ),
        RuntimeSourceAnchor(
            id=UUID("20000000-0000-4000-8000-000000000009"),
            revision_id=revision_ids[4],
            exact_quote=(
                "예린: 최종 영상은 Marine Snow 제거율뿐 아니라 목표물 탐지 정확도, 경계 선명도, "
                "프레임 간 깜빡임을 함께 통과해야 한다고 검수 조건을 정했다."
            ),
            participant="예린",
        ),
        RuntimeSourceAnchor(
            id=UUID("20000000-0000-4000-8000-000000000010"),
            revision_id=revision_ids[4],
            exact_quote=(
                "예린의 파일: 원본, 오염본, 복원본을 나란히 비교하고 가려졌던 주 목표물의 세부가 "
                "새로 생성되거나 삭제되지 않았는지 사람이 확인하는 승인표를 정의했다."
            ),
            participant="예린",
        ),
    )


def run_online_smoke(
    transport: GrokTransport,
    *,
    model: str = "grok-4.5",
) -> dict[str, object]:
    """Perform exactly one provider call and return non-secret validation facts."""

    anchors = synthetic_rag_anchors()
    if len({anchor.exact_quote for anchor in anchors}) != len(anchors):
        raise GrokProviderError("grok_duplicate_input_anchor", retryable=False)
    candidate = GrokProvider(transport=transport, model=model).generate_summary_candidate(
        anchors
    )
    items = [item for section in candidate.sections for item in section.items]
    if not items or any(_KOREAN.search(item.text) is None for item in items):
        raise GrokProviderError("grok_korean_output_required", retryable=False)
    if any(not item.supports for item in items):
        raise GrokProviderError("grok_support_required", retryable=False)
    anchors_by_id = {anchor.id: anchor for anchor in anchors}
    covered_participants = {
        anchors_by_id[support.source_anchor_id].participant
        for item in items
        for support in item.supports
    }
    expected_participants = {anchor.participant for anchor in anchors}
    if covered_participants != expected_participants:
        raise GrokProviderError("grok_participant_coverage_required", retryable=False)
    normalized_items = [" ".join(item.text.split()) for item in items]
    if len(normalized_items) != len(set(normalized_items)):
        raise GrokProviderError("grok_duplicate_output_item", retryable=False)
    return {
        "online": True,
        "provider": "grok",
        "model": model,
        "sections": len(candidate.sections),
        "items": len(items),
        "korean_output": True,
        "participants": len({anchor.participant for anchor in anchors}),
        "covered_participants": len(covered_participants),
        "unique_input_anchors": len(anchors),
        "unique_output_items": len(normalized_items),
        "grounding_candidate_validated": True,
        "canonical_persistence_attempted": False,
    }


def main(environment: Mapping[str, str] | None = None) -> int:
    """Run only after explicit acknowledgement; never print or persist the key."""

    values = environment if environment is not None else os.environ
    if values.get("GROK_LIVE_SMOKE_ACK") != _ACKNOWLEDGEMENT:
        print("Grok live smoke is disabled: explicit acknowledgement is missing.")
        return 2
    model = values.get("GROK_MODEL", "grok-4.5").strip()
    if not model:
        print("Grok live smoke is disabled: GROK_MODEL is blank.")
        return 2

    def key_supplier() -> str:
        return values.get("XAI_API_KEY", "")

    transport = XaiResponsesTransport(
        api_key_supplier=key_supplier,
        enabled=True,
        timeout_seconds=30.0,
    )
    try:
        result = run_online_smoke(transport, model=model)
    except GrokProviderError as error:
        print(
            json.dumps(
                {"ok": False, "error_code": error.code, "retryable": error.retryable}
            )
        )
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
