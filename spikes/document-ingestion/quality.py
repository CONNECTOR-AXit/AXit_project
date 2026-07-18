from __future__ import annotations

import unicodedata


MAX_EVALUATION_CODEPOINTS = 20_000


def normalize_ocr_quality_text(value: str) -> str:
    """Apply the frozen G0 OCR scoring profile: NFC and no Unicode whitespace."""

    normalized = unicodedata.normalize(
        "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
    )
    return "".join(character for character in normalized if not character.isspace())


def levenshtein_distance(left: str, right: str) -> int:
    """Return code-point edit distance with bounded linear memory."""

    if len(left) > MAX_EVALUATION_CODEPOINTS or len(right) > MAX_EVALUATION_CODEPOINTS:
        raise ValueError("OCR evaluation input exceeds the G0 scoring bound")
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_character in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1]
                    + (left_character != right_character),
                )
            )
        previous = current
    return previous[-1]


def ocr_character_accuracy(expected: str, actual: str) -> float:
    expected_normalized = normalize_ocr_quality_text(expected)
    actual_normalized = normalize_ocr_quality_text(actual)
    denominator = max(len(expected_normalized), 1)
    distance = levenshtein_distance(expected_normalized, actual_normalized)
    return round(max(0.0, 1 - distance / denominator), 6)
