"""Hierarchical source planning, semantic deduplication, and token budgeting."""

from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from app.local_embeddings import is_conservative_duplicate
from app.summary_grounding import RuntimeSourceAnchor
from app.provider_errors import GenerationProviderFailure

_MAX_DOCUMENT_STAGE_CALLS = 32
_MAX_ANCHORS_PER_REVISION = 2_000
_MAX_DEDUP_COMPARISONS = 200_000


@dataclass(frozen=True, slots=True)
class ContextDocument:
    revision_id: UUID
    anchors: tuple[RuntimeSourceAnchor, ...]


@dataclass(frozen=True, slots=True)
class GenerationContextPlan:
    documents: tuple[ContextDocument, ...]
    duplicate_anchor_ids: tuple[UUID, ...]
    estimated_input_tokens: int

    @property
    def anchors(self) -> tuple[RuntimeSourceAnchor, ...]:
        return tuple(anchor for document in self.documents for anchor in document.anchors)


def plan_generation_context(
    anchors: tuple[RuntimeSourceAnchor, ...],
    *,
    max_estimated_tokens: int = 24_000,
    duplicate_threshold: float = 0.72,
) -> GenerationContextPlan:
    """Group by immutable revision and remove only within-document near duplicates."""

    if not anchors:
        raise ValueError("generation context requires source anchors")
    if max_estimated_tokens < 1_000:
        raise ValueError("generation context token budget is too small")
    grouped: dict[UUID, list[RuntimeSourceAnchor]] = {}
    for anchor in anchors:
        grouped.setdefault(anchor.revision_id, []).append(anchor)
    documents: list[ContextDocument] = []
    duplicates: list[UUID] = []
    character_budget = max_estimated_tokens * 4
    total_selected_characters = 0
    comparisons = 0
    for revision_id in sorted(grouped, key=str):
        if len(grouped[revision_id]) > _MAX_ANCHORS_PER_REVISION:
            raise GenerationProviderFailure("context_anchor_budget_exceeded", retryable=False)
        selected: list[RuntimeSourceAnchor] = []
        selected_characters = 0
        seen_for_revision: list[RuntimeSourceAnchor] = []
        for anchor in grouped[revision_id]:
            comparisons += len(seen_for_revision)
            if comparisons > _MAX_DEDUP_COMPARISONS:
                raise GenerationProviderFailure("context_comparison_budget_exceeded", retryable=False)
            if any(
                is_conservative_duplicate(
                    anchor.exact_quote, existing.exact_quote, threshold=duplicate_threshold
                )
                for existing in seen_for_revision
            ):
                duplicates.append(anchor.id)
                continue
            required = len(anchor.exact_quote)
            if required > character_budget:
                raise GenerationProviderFailure(
                    "context_anchor_too_large", retryable=False,
                    detail="one source anchor exceeds the configured token budget",
                )
            if total_selected_characters + required > character_budget:
                raise GenerationProviderFailure(
                    "context_budget_exceeded", retryable=False,
                    detail="generation context exceeds the configured token budget",
                )
            if selected and selected_characters + required > character_budget:
                documents.append(ContextDocument(revision_id, tuple(selected)))
                selected = []
                selected_characters = 0
            selected.append(anchor)
            seen_for_revision.append(anchor)
            selected_characters += required
            total_selected_characters += required
        if selected:
            documents.append(ContextDocument(revision_id, tuple(selected)))
    if len(documents) > _MAX_DOCUMENT_STAGE_CALLS:
        raise GenerationProviderFailure("context_call_budget_exceeded", retryable=False)
    return GenerationContextPlan(
        documents=tuple(documents),
        duplicate_anchor_ids=tuple(duplicates),
        estimated_input_tokens=max(
            1,
            math.ceil(total_selected_characters / 4),
        ),
    )
