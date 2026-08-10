"""Runtime-neutral generation provider contract.

The runner depends on this structural boundary rather than on the fixture
implementation.  Providers remain responsible for producing already
grounded, alias-free domain results and typed failures.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from app.summary_grounding import GroundedSummary, RuntimeSourceAnchor


class ResearchTopic(Protocol):
    text: str
    web_evidence_ids: tuple[UUID, ...]


class ResearchFact(Protocol):
    source_anchor_id: UUID
    source_claim_quote: str
    verdict: Literal["supported", "refuted", "mixed", "unverifiable"]
    explanation: str
    web_evidence_ids: tuple[UUID, ...]


class ResearchEvidence(Protocol):
    id: UUID
    url: str
    title: str
    domain: str
    accessed_at: datetime
    snippet_hash: str


class GroundedResearch(Protocol):
    topic_items: tuple[ResearchTopic, ...]
    fact_checks: tuple[ResearchFact, ...]
    web_evidence: tuple[ResearchEvidence, ...]

    def structured_content(self) -> dict[str, object]: ...


class GenerationProvider(Protocol):
    provider: str
    model: str
    prompt_version: str

    def generate_summary(
        self,
        anchors: tuple[RuntimeSourceAnchor, ...] | list[RuntimeSourceAnchor],
        *,
        fixture_id: str,
        attempt: int,
    ) -> GroundedSummary: ...

    def generate_research(
        self,
        anchors: tuple[RuntimeSourceAnchor, ...] | list[RuntimeSourceAnchor],
        *,
        snapshot_id: UUID,
    ) -> GroundedResearch: ...


@dataclass(frozen=True, slots=True)
class CallbackGenerationProvider:
    """Composition adapter for any approved transport plus grounding policy."""

    provider: str
    model: str
    prompt_version: str
    summary_generator: Callable[..., GroundedSummary]
    research_generator: Callable[..., GroundedResearch]

    def generate_summary(self, anchors: tuple[RuntimeSourceAnchor, ...] | list[RuntimeSourceAnchor],
                         *, fixture_id: str, attempt: int) -> GroundedSummary:
        return self.summary_generator(anchors, fixture_id=fixture_id, attempt=attempt)

    def generate_research(self, anchors: tuple[RuntimeSourceAnchor, ...] | list[RuntimeSourceAnchor],
                          *, snapshot_id: UUID) -> GroundedResearch:
        return self.research_generator(anchors, snapshot_id=snapshot_id)
