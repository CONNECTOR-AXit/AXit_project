"""Deterministic local hybrid retrieval for snapshot-pinned generation context."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.local_embeddings import semantic_similarity
from app.source_anchor_quality import assess_source_anchor
from app.summary_grounding import RuntimeSourceAnchor


_STRATEGY: Final = "hybrid-local-v1"
_MAX_CANDIDATES: Final = 10_000


@dataclass(frozen=True, slots=True)
class GenerationRetrievalPlan:
    query_hash: str
    candidate_count: int
    eligible_count: int
    anchors: tuple[RuntimeSourceAnchor, ...]
    ranked_anchor_ids: tuple[UUID, ...]
    excluded_anchor_ids: tuple[UUID, ...]
    quality_reason_counts: tuple[tuple[str, int], ...]

    def metadata(self) -> dict[str, object]:
        return {
            "strategy": _STRATEGY,
            "query_hash": self.query_hash,
            "candidate_count": self.candidate_count,
            "eligible_count": self.eligible_count,
            "selected_count": len(self.anchors),
            "selected_anchor_ids": [str(anchor_id) for anchor_id in self.ranked_anchor_ids],
            "source_quality": {
                "status": "filtered" if self.excluded_anchor_ids else "clean",
                "total_anchor_count": self.candidate_count,
                "accepted_anchor_count": self.eligible_count,
                "excluded_anchor_count": len(self.excluded_anchor_ids),
                "reason_counts": dict(self.quality_reason_counts),
            },
        }


def retrieve_generation_anchors(
    *,
    topic: str,
    anchors: tuple[RuntimeSourceAnchor, ...],
    max_anchors: int = 64,
) -> GenerationRetrievalPlan:
    """Rank immutable anchors locally, retaining document coverage under a hard cap."""

    normalized_topic = _normalize(topic)
    if not normalized_topic:
        raise ValueError("generation retrieval topic must not be blank")
    if isinstance(max_anchors, bool) or not 1 <= max_anchors <= 256:
        raise ValueError("generation retrieval limit must be between 1 and 256")
    if not anchors:
        raise ValueError("generation retrieval requires source anchors")
    if len(anchors) > _MAX_CANDIDATES:
        raise ValueError("generation retrieval candidate limit exceeded")

    eligible: list[RuntimeSourceAnchor] = []
    excluded_ids: list[UUID] = []
    reason_counts: dict[str, int] = {}
    for anchor in anchors:
        assessment = assess_source_anchor(
            text=anchor.exact_quote,
            confidence=anchor.confidence,
            block_type=anchor.block_type,
        )
        if assessment.accepted:
            eligible.append(anchor)
            continue
        excluded_ids.append(anchor.id)
        reason = assessment.reason or "unknown"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    if not eligible:
        raise ValueError("generation retrieval has no quality-approved source anchors")
    eligible_anchors = tuple(eligible)

    query_tokens = frozenset(_tokens(normalized_topic))
    scored = tuple(
        sorted(
            (
                (
                    _hybrid_score(
                        query=normalized_topic,
                        query_tokens=query_tokens,
                        text=anchor.exact_quote,
                    ),
                    ordinal,
                    anchor,
                )
                for ordinal, anchor in enumerate(eligible_anchors)
            ),
            key=lambda item: (
                -item[0],
                str(item[2].revision_id),
                item[1],
                str(item[2].id),
            ),
        )
    )
    limit = min(max_anchors, len(eligible_anchors))
    selected_ids: set[UUID] = set()

    # First retain the strongest anchor from as many documents as the budget allows.
    revision_best: dict[UUID, tuple[float, int, RuntimeSourceAnchor]] = {}
    for candidate in scored:
        revision_best.setdefault(candidate[2].revision_id, candidate)
    for _, _, anchor in sorted(
        revision_best.values(),
        key=lambda item: (-item[0], str(item[2].revision_id), item[1], str(item[2].id)),
    )[:limit]:
        selected_ids.add(anchor.id)

    for _, _, anchor in scored:
        if len(selected_ids) >= limit:
            break
        selected_ids.add(anchor.id)

    ranked_anchor_ids = tuple(
        anchor.id for _, _, anchor in scored if anchor.id in selected_ids
    )
    selected_anchors = tuple(anchor for anchor in eligible_anchors if anchor.id in selected_ids)
    return GenerationRetrievalPlan(
        query_hash=hashlib.sha256(normalized_topic.encode("utf-8")).hexdigest(),
        candidate_count=len(anchors),
        eligible_count=len(eligible_anchors),
        anchors=selected_anchors,
        ranked_anchor_ids=ranked_anchor_ids,
        excluded_anchor_ids=tuple(excluded_ids),
        quality_reason_counts=tuple(sorted(reason_counts.items())),
    )


def _hybrid_score(
    *,
    query: str,
    query_tokens: frozenset[str],
    text: str,
) -> float:
    text_tokens = frozenset(_tokens(_normalize(text)))
    lexical = (
        len(query_tokens & text_tokens) / len(query_tokens)
        if query_tokens
        else 0.0
    )
    semantic = semantic_similarity(query, text)
    return round((semantic * 0.75) + (lexical * 0.25), 8)


def _normalize(value: str) -> str:
    return " ".join(
        re.findall(
            r"[^\W_]+",
            unicodedata.normalize("NFKC", value).casefold(),
            flags=re.UNICODE,
        )
    )


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[^\W_]+", value, flags=re.UNICODE))
