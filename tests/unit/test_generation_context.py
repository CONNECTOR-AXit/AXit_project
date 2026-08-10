from uuid import uuid4

import pytest

import app.generation_context as generation_context
from app.generation_context import plan_generation_context
from app.provider_errors import GenerationProviderFailure
from app.summary_grounding import RuntimeSourceAnchor


def _anchor(revision_id, text):
    return RuntimeSourceAnchor(id=uuid4(), revision_id=revision_id, exact_quote=text)


def test_context_groups_documents_and_deduplicates_only_within_revision() -> None:
    first, second = uuid4(), uuid4()
    anchors = (
        _anchor(first, "예산 검토 결과를 공유합니다"),
        _anchor(first, "예산 검토 결과 공유"),
        _anchor(second, "예산 검토 결과를 공유합니다"),
    )
    plan = plan_generation_context(anchors)

    assert len(plan.documents) == 2
    assert [len(document.anchors) for document in plan.documents] == [1, 1]
    assert plan.duplicate_anchor_ids == (anchors[1].id,)
    assert {anchor.revision_id for anchor in plan.anchors} == {first, second}


def test_context_fails_closed_instead_of_silently_truncating_sources() -> None:
    anchor = _anchor(uuid4(), "가" * 4_001)
    with pytest.raises(ValueError, match="token budget"):
        plan_generation_context((anchor,), max_estimated_tokens=1_000)


def test_context_budget_is_global_across_document_stage_calls() -> None:
    anchors = tuple(_anchor(uuid4(), chr(0xAC00 + index) * 1_500) for index in range(3))
    with pytest.raises(ValueError, match="token budget"):
        plan_generation_context(anchors, max_estimated_tokens=1_000)


def test_context_rejects_anchor_count_before_quadratic_work(monkeypatch) -> None:
    monkeypatch.setattr(generation_context, "_MAX_ANCHORS_PER_REVISION", 2)
    revision_id = uuid4()
    with pytest.raises(GenerationProviderFailure, match="context_anchor_budget_exceeded"):
        plan_generation_context(tuple(_anchor(revision_id, str(index)) for index in range(3)))


def test_context_rejects_comparison_work_budget(monkeypatch) -> None:
    monkeypatch.setattr(generation_context, "_MAX_DEDUP_COMPARISONS", 1)
    revision_id = uuid4()
    with pytest.raises(GenerationProviderFailure, match="context_comparison_budget_exceeded"):
        plan_generation_context(tuple(_anchor(revision_id, str(index)) for index in range(3)))
