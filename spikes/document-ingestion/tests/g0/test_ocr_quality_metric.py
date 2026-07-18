from __future__ import annotations

import pytest

from quality import (
    MAX_EVALUATION_CODEPOINTS,
    levenshtein_distance,
    normalize_ocr_quality_text,
    ocr_character_accuracy,
)


def test_scoring_profile_is_nfc_lf_and_whitespace_insensitive_only() -> None:
    assert normalize_ocr_quality_text(" 회의\r\n사전\t브리핑 ") == "회의사전브리핑"
    assert normalize_ocr_quality_text("예산: 1억 2,500만 원") == "예산:1억2,500만원"


def test_character_accuracy_preserves_punctuation_numbers_and_korean() -> None:
    assert ocr_character_accuracy("회의 사전 브리핑", "회의사전 브리핑") == 1.0
    assert ocr_character_accuracy("예산 1억", "예산 2억") == 0.75
    assert levenshtein_distance("가나다", "가마") == 2


def test_scoring_rejects_unbounded_inputs() -> None:
    with pytest.raises(ValueError, match="bound"):
        levenshtein_distance("가" * (MAX_EVALUATION_CODEPOINTS + 1), "가")
