from app.source_anchor_quality import assess_source_anchor


def test_low_confidence_ocr_fragment_is_excluded_from_generation() -> None:
    assessment = assess_source_anchor(
        text="사내 686 시스템 도입 해",
        confidence=0.58,
        block_type="image_ocr",
    )

    assert assessment.accepted is False
    assert assessment.reason == "low_ocr_confidence"


def test_incomplete_ocr_fragment_is_excluded_even_with_high_confidence() -> None:
    assessment = assess_source_anchor(
        text="사내 686 시스템 도입 해",
        confidence=0.93,
        block_type="image_ocr",
    )

    assert assessment.accepted is False
    assert assessment.reason == "incomplete_ocr_fragment"


def test_corrupt_replacement_characters_are_excluded_even_without_ocr_confidence() -> None:
    assessment = assess_source_anchor(
        text="회의 결론 \ufffd\ufffd\ufffd 예산 승인",
        confidence=None,
        block_type="pdf_text",
    )

    assert assessment.accepted is False
    assert assessment.reason == "corrupt_characters"


def test_clean_korean_ocr_anchor_remains_eligible() -> None:
    assessment = assess_source_anchor(
        text="사내 검색 시스템은 2026년 9월에 시범 도입한다.",
        confidence=0.91,
        block_type="pdf_ocr",
    )

    assert assessment.accepted is True
    assert assessment.reason is None
