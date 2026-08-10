from uuid import uuid4

from app.automatic_report_suggestions import (
    _SnapshotDocument,
    _build_source_coverage_blocks,
    _select_report_anchors,
    build_automatic_proposals,
)
from app.document_comparison import ComparisonAnchor, compare_anchor_sets
from app.document_comparison import ComparisonMatch, DocumentComparison


def test_report_anchor_selection_keeps_every_anchor_when_within_budget() -> None:
    documents = tuple(
        _SnapshotDocument(
            revision_id,
            f"문서 {index}",
            tuple(
                ComparisonAnchor(uuid4(), revision_id, f"문서 {index} 근거 {ordinal}")
                for ordinal in range(3)
            ),
        )
        for index, revision_id in enumerate((uuid4(), uuid4(), uuid4()))
    )

    selected = _select_report_anchors(
        documents,
        max_anchors=9,
    )

    assert [anchor.text for anchor in selected] == [
        "문서 0 근거 0",
        "문서 1 근거 0",
        "문서 2 근거 0",
        "문서 0 근거 1",
        "문서 1 근거 1",
        "문서 2 근거 1",
        "문서 0 근거 2",
        "문서 1 근거 2",
        "문서 2 근거 2",
    ]


def test_report_anchor_selection_uses_full_budget_without_per_document_truncation() -> None:
    first_revision_id = uuid4()
    second_revision_id = uuid4()
    documents = (
        _SnapshotDocument(
            first_revision_id,
            "긴 문서",
            tuple(
                ComparisonAnchor(
                    uuid4(), first_revision_id, f"반드시 분석할 근거 {ordinal}"
                )
                for ordinal in range(25)
            ),
        ),
        _SnapshotDocument(
            second_revision_id,
            "짧은 문서",
            (ComparisonAnchor(uuid4(), second_revision_id, "짧은 문서 근거"),),
        ),
    )

    selected = _select_report_anchors(documents, max_anchors=26)

    assert len(selected) == 26
    assert selected[1].text == "짧은 문서 근거"
    assert selected[-1].text == "반드시 분석할 근거 24"


def test_source_coverage_blocks_preserve_every_anchor_verbatim() -> None:
    first_revision_id = uuid4()
    second_revision_id = uuid4()
    first_anchor = ComparisonAnchor(uuid4(), first_revision_id, "첫 문서의 전체 원문")
    second_anchor = ComparisonAnchor(uuid4(), second_revision_id, "둘째 문서의 전체 원문")
    documents = (
        _SnapshotDocument(first_revision_id, "기획안", (first_anchor,)),
        _SnapshotDocument(second_revision_id, "보안안", (second_anchor,)),
    )

    blocks = _build_source_coverage_blocks(documents)

    assert blocks[0] == {
        "id": "source-coverage-heading",
        "type": "heading",
        "level": 1,
        "text": "업로드 문서 전체 내용",
        "tag": "원문 전체",
    }
    assert [block["text"] for block in blocks[1:]] == [
        first_anchor.text,
        second_anchor.text,
    ]
    assert blocks[1]["tag"] == f"기획안 · RAG:{first_anchor.anchor_id}"
    assert blocks[2]["tag"] == f"보안안 · RAG:{second_anchor.anchor_id}"


def test_source_coverage_blocks_pack_many_anchors_without_dropping_any() -> None:
    revision_id = uuid4()
    anchors = tuple(
        ComparisonAnchor(uuid4(), revision_id, f"원문 {ordinal}")
        for ordinal in range(23)
    )

    blocks = _build_source_coverage_blocks(
        (_SnapshotDocument(revision_id, "대용량 문서", anchors),)
    )

    assert len(blocks) == 4  # heading + 10/10/3 anchor chunks
    combined_text = "\n\n".join(str(block["text"]) for block in blocks[1:])
    assert all(anchor.text in combined_text for anchor in anchors)
    combined_tags = " ".join(str(block["tag"]) for block in blocks[1:])
    assert all(f"RAG:{anchor.anchor_id}" in combined_tags for anchor in anchors)


def test_comparison_proposals_distinguish_duplicate_edit_and_missing_content() -> None:
    left_revision_id = uuid4()
    right_revision_id = uuid4()
    left = (
        ComparisonAnchor(uuid4(), left_revision_id, "공통 예산 검토 결과"),
        ComparisonAnchor(uuid4(), left_revision_id, "왼쪽 전용 일정"),
    )
    right = (
        ComparisonAnchor(uuid4(), right_revision_id, "공통 예산 검토 결과"),
        ComparisonAnchor(uuid4(), right_revision_id, "오른쪽 전용 담당자"),
    )
    comparison = compare_anchor_sets(
        left_revision_id=left_revision_id,
        right_revision_id=right_revision_id,
        left=left,
        right=right,
    )

    proposals = build_automatic_proposals(
        comparisons=(("기준 문서", "비교 문서", comparison),),
    )

    assert [proposal.kind for proposal in proposals] == ["remove", "add", "add"]
    assert proposals[0].source_anchor_id == right[0].anchor_id
    assert {proposal.source_anchor_id for proposal in proposals[1:]} == {
        left[1].anchor_id,
        right[1].anchor_id,
    }
    assert len({proposal.comparison_key for proposal in proposals}) == len(proposals)


def test_similar_comparison_becomes_an_edit_proposal() -> None:
    left_revision_id = uuid4()
    right_revision_id = uuid4()
    left = ComparisonAnchor(uuid4(), left_revision_id, "예산은 1억 원입니다.")
    right = ComparisonAnchor(uuid4(), right_revision_id, "예산은 약 1억 원으로 예상됩니다.")
    comparison = DocumentComparison(
        left_revision_id=left_revision_id,
        right_revision_id=right_revision_id,
        matches=(ComparisonMatch(left, right, 0.81, "similar"),),
        left_only=(),
        right_only=(),
    )

    proposals = build_automatic_proposals(
        comparisons=(("예산안", "회의록", comparison),),
    )

    assert len(proposals) == 1
    assert proposals[0].kind == "edit"
    assert proposals[0].source_anchor_id == right.anchor_id
    assert "사실 관계" in proposals[0].rationale
