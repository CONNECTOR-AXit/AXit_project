from uuid import uuid4

from app.generation_retrieval import retrieve_generation_anchors
from app.summary_grounding import RuntimeSourceAnchor


def test_hybrid_retrieval_selects_relevant_anchors_with_deterministic_order() -> None:
    revision_id = uuid4()
    distractor = RuntimeSourceAnchor(uuid4(), revision_id, "사내 동호회 점심 메뉴")
    budget = RuntimeSourceAnchor(uuid4(), revision_id, "프로젝트 예산은 1억 원입니다")
    schedule = RuntimeSourceAnchor(uuid4(), revision_id, "다음 회의 일정은 금요일입니다")
    anchors = (distractor, budget, schedule)

    first = retrieve_generation_anchors(
        topic="프로젝트 예산 및 회의 일정",
        anchors=anchors,
        max_anchors=2,
    )
    second = retrieve_generation_anchors(
        topic="프로젝트 예산 및 회의 일정",
        anchors=anchors,
        max_anchors=2,
    )

    assert first == second
    assert first.candidate_count == 3
    assert first.anchors == (budget, schedule)
    assert set(first.ranked_anchor_ids) == {budget.id, schedule.id}
    assert first.query_hash == second.query_hash


def test_retrieval_keeps_document_coverage_before_global_fill() -> None:
    first_revision = uuid4()
    second_revision = uuid4()
    first_best = RuntimeSourceAnchor(uuid4(), first_revision, "예산 검토와 승인")
    first_extra = RuntimeSourceAnchor(uuid4(), first_revision, "예산 세부 항목")
    second_best = RuntimeSourceAnchor(uuid4(), second_revision, "일정 검토와 승인")

    plan = retrieve_generation_anchors(
        topic="예산 일정 검토",
        anchors=(first_best, first_extra, second_best),
        max_anchors=2,
    )

    assert {anchor.revision_id for anchor in plan.anchors} == {
        first_revision,
        second_revision,
    }


def test_retrieval_filters_noisy_ocr_before_ranking_and_reports_quality() -> None:
    revision_id = uuid4()
    noisy = RuntimeSourceAnchor(
        id=uuid4(),
        revision_id=revision_id,
        exact_quote="사내 686 시스템 도입 해",
        block_type="image_ocr",
        confidence=0.58,
    )
    clean = RuntimeSourceAnchor(
        id=uuid4(),
        revision_id=revision_id,
        exact_quote="사내 검색 시스템은 2026년 9월에 시범 도입한다.",
        block_type="image_ocr",
        confidence=0.93,
    )

    result = retrieve_generation_anchors(
        topic="사내 검색 시스템 도입",
        anchors=(noisy, clean),
    )

    assert result.anchors == (clean,)
    assert result.excluded_anchor_ids == (noisy.id,)
    assert result.metadata()["source_quality"] == {
        "status": "filtered",
        "total_anchor_count": 2,
        "accepted_anchor_count": 1,
        "excluded_anchor_count": 1,
        "reason_counts": {"low_ocr_confidence": 1},
    }
