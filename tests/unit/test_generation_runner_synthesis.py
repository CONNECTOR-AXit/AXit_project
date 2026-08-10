from uuid import uuid4

from app.generation_runner import _synthesize_document_summaries
from app.summary_grounding import (
    GroundedSummary,
    GroundedSummaryItem,
    GroundedSummarySection,
)


def test_hierarchical_summary_round_robins_documents_within_contract_limit() -> None:
    summaries = tuple(
        GroundedSummary(
            sections=(
                GroundedSummarySection(
                    heading="Source highlights",
                    items=tuple(
                        GroundedSummaryItem(
                            text=f"document-{document}-item-{item}",
                            source_anchor_ids=(uuid4(),),
                            supports=(),
                        )
                        for item in range(30)
                    ),
                ),
            )
        )
        for document in range(7)
    )

    result = _synthesize_document_summaries(summaries)
    texts = [item.text for section in result.sections for item in section.items]

    assert len(texts) == 100
    assert texts[:7] == [f"document-{document}-item-0" for document in range(7)]
    assert texts[7] == "document-0-item-1"
