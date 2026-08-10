"""Small deterministic local embeddings for bounded similarity work.

No source text leaves the process.  Signed feature hashing projects normalized
word and character n-grams into a fixed vector; cosine similarity then gives a
stable embedding-space score without a model or network dependency.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from typing import Final

_DIMENSIONS: Final = 256
_CONCEPTS: Final[dict[str, tuple[str, ...]]] = {
    "meeting": ("회의", "미팅"),
    "schedule": ("일정", "날짜"),
    "next_week": ("다음 주", "다음주", "일주일 뒤", "일주일뒤"),
    "postpone": ("연기", "미룸", "미루"),
    "owner": ("담당자", "업무를 맡", "업무 담당", "책임자"),
    "budget": ("예산", "비용"),
    "share": ("공유", "전달"),
}


def embed_text(value: str) -> tuple[float, ...]:
    normalized = " ".join(
        re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value).casefold(), re.UNICODE)
    )
    words = normalized.split()
    compact = "".join(words)
    features = words.copy()
    features.extend(compact[i : i + 2] for i in range(max(0, len(compact) - 1)))
    features.extend(compact[i : i + 3] for i in range(max(0, len(compact) - 2)))
    for concept, expressions in _CONCEPTS.items():
        if any(expression in normalized for expression in expressions):
            # Repetition gives domain concepts enough weight to survive wording changes.
            features.extend((f"concept:{concept}",) * 8)
    counts = Counter(features)
    vector = [0.0] * _DIMENSIONS
    for feature, count in counts.items():
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % _DIMENSIONS
        sign = 1.0 if digest[4] & 1 else -1.0
        weight = float(count) if feature.startswith("concept:") else 1.0 + math.log(count)
        vector[bucket] += sign * weight
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0:
        return tuple(vector)
    return tuple(component / norm for component in vector)


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions must match")
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right, strict=True))))


def semantic_similarity(left: str, right: str) -> float:
    if unicodedata.normalize("NFKC", left).casefold().strip() == unicodedata.normalize(
        "NFKC", right
    ).casefold().strip():
        return 1.0
    return cosine_similarity(embed_text(left), embed_text(right))


_NEGATION_MARKERS: Final = ("않", "아님", "아니", "취소", "철회", "거부")
_OPPOSING_PREDICATES: Final = (
    (("취소", "철회"), ("확정", "승인")),
    (("증액", "인상"), ("감액", "삭감")),
    (("연기", "미룸"), ("앞당", "조기")),
)


def _content_slots(value: str) -> dict[str, frozenset[str]]:
    """Extract high-risk fact slots whose disagreement forbids deduplication."""
    compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", value).casefold())
    names = set(re.findall(r"담당자(?:는|가|로)?([가-힣]{2,4})", compact))
    names.update(re.findall(r"([가-힣]{2,4})(?:가|이가|는|은)업무를?맡", compact))
    relative_dates = set(re.findall(r"(?:이번|다음|차주|익월)(?:주|달|월|분기|해|년)", compact))
    if "다음주" in compact or "차주" in compact or "일주일뒤" in compact:
        relative_dates.difference_update({"다음주", "차주"})
        relative_dates.add("next_week")
    return {
        "number": frozenset(re.findall(r"\d+(?:[.,]\d+)?(?:억|만|천|원|%|명|건|회)?", compact)),
        "weekday": frozenset(re.findall(r"(?:월|화|수|목|금|토|일)요일", compact)),
        "relative_date": frozenset(relative_dates),
        "date": frozenset(re.findall(r"\d{4}[-./년]\d{1,2}(?:[-./월]\d{1,2}일?)?", compact)),
        "owner": frozenset(names),
    }


def is_conservative_duplicate(left: str, right: str, *, threshold: float = 0.72) -> bool:
    """Require matching polarity and state before treating related text as duplicate."""
    normalized_left = unicodedata.normalize("NFKC", left).casefold()
    normalized_right = unicodedata.normalize("NFKC", right).casefold()
    left_slots = _content_slots(normalized_left)
    right_slots = _content_slots(normalized_right)
    if any(left_slots[k] != right_slots[k] for k in left_slots):
        return False
    if any(marker in normalized_left for marker in _NEGATION_MARKERS) != any(
        marker in normalized_right for marker in _NEGATION_MARKERS
    ):
        return False
    for first, second in _OPPOSING_PREDICATES:
        left_first = any(value in normalized_left for value in first)
        left_second = any(value in normalized_left for value in second)
        right_first = any(value in normalized_right for value in first)
        right_second = any(value in normalized_right for value in second)
        if (left_first and right_second) or (left_second and right_first):
            return False
    return semantic_similarity(left, right) >= threshold
