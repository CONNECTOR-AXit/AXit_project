"""Deterministic quality gate for extracted source anchors.

The gate runs locally before retrieval or provider calls.  It never rewrites source
text: questionable anchors remain available for the source viewer, but they cannot
be used to establish facts in generated reports.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final


_OCR_BLOCK_TYPES: Final = frozenset({"image_ocr", "pdf_ocr"})
_MIN_OCR_CONFIDENCE: Final = 0.72
_CORRUPT_CHARACTERS: Final = frozenset({"\ufffd", "\ufffe", "\uffff"})
_INCOMPLETE_KOREAN_OCR_ENDING: Final = re.compile(
    r"(?:^|\s)(?:해|하|되|된|할|될)\s*[.!?]?\s*$"
)


@dataclass(frozen=True, slots=True)
class AnchorQualityAssessment:
    accepted: bool
    reason: str | None = None


def assess_source_anchor(
    *,
    text: str,
    confidence: float | None,
    block_type: str,
) -> AnchorQualityAssessment:
    """Return a conservative, explainable generation-eligibility decision."""

    normalized = unicodedata.normalize("NFC", text).strip()
    if not normalized:
        return AnchorQualityAssessment(False, "blank_text")
    if any(character in _CORRUPT_CHARACTERS for character in normalized):
        return AnchorQualityAssessment(False, "corrupt_characters")
    if any(
        unicodedata.category(character) == "Cc" and character not in "\t\n\r"
        for character in normalized
    ):
        return AnchorQualityAssessment(False, "control_characters")
    if block_type in _OCR_BLOCK_TYPES:
        if confidence is None or confidence < _MIN_OCR_CONFIDENCE:
            return AnchorQualityAssessment(False, "low_ocr_confidence")
        if len(normalized) < 3:
            return AnchorQualityAssessment(False, "short_ocr_fragment")
        if (
            len(normalized.split()) <= 6
            and _INCOMPLETE_KOREAN_OCR_ENDING.search(normalized) is not None
        ):
            return AnchorQualityAssessment(False, "incomplete_ocr_fragment")
    return AnchorQualityAssessment(True)
