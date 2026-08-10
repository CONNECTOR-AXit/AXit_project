"""Deterministic, fixture-backed provider for the approved no-Grok experiment.

This is a development-time substitute, not a runtime coding-agent bridge and
not evidence of any production-model compatibility.  Fixture-local aliases
are resolved to server-issued UUIDs in memory and are never returned in a
candidate, persistence payload, or error detail.
"""

from __future__ import annotations

import json
import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from app.summary_grounding import (
    ApprovedSummaryAssertion,
    ForeignAnchorError,
    GroundedSummary,
    RuntimeSourceAnchor,
    SourcePromptInjectionError,
    SummaryCandidate,
    SummaryItemCandidate,
    SummarySectionCandidate,
    SummarySupportCandidate,
    UnsupportedAssertionError,
    ground_summary,
    isolated_summary_excerpt,
    require_assertion_grounded,
)
from app.provider_errors import GenerationProviderFailure


_SCHEMA_VERSION: Final = "provider-fixture.v1"
_GROUNDED_FIXTURE: Final = "summary-grounded-001"
_RETRY_FIXTURE: Final = "summary-deterministic-retry-001"
_REJECTION_FIXTURES: Final[frozenset[str]] = frozenset(
    {
        "summary-foreign-anchor-rejection-001",
        "summary-source-prompt-injection-rejection-001",
        "summary-ungrounded-assertion-rejection-001",
        "summary-provider-timeout-001",
        "summary-malformed-schema-001",
    }
)
_REVIEWED_SUMMARY_ASSERTIONS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "The facilitator reported that the pilot scope and owner are confirmed and the next review date is Friday.",
        (
            "Facilitator: The pilot scope and owner are confirmed, and the next review date is Friday.",
        ),
    ),
    (
        "Alice reported that the Tuesday checklist assignment is recorded under her name.",
        ("Alice: The Tuesday checklist assignment is recorded under my name.",),
    ),
    (
        "Bob reported that the sample records passed Thursday's validation audit.",
        ("Bob: The sample records passed the validation audit on Thursday.",),
    ),
)


class MockProviderError(GenerationProviderFailure):
    """Typed provider outcome safe to persist as an error code only."""

    code: str
    retryable: bool

    def __init__(self, code: str, *, retryable: bool, detail: str) -> None:
        super().__init__(code, retryable=retryable, detail=detail)


class MockProviderUnavailableError(MockProviderError):
    """The local fixture corpus cannot safely serve an output."""

    def __init__(self, code: str = "fixture_source_mismatch") -> None:
        super().__init__(
            code,
            retryable=False,
            detail="deterministic fixture output is unavailable for this source set",
        )


class MockProviderTimeoutError(MockProviderError):
    """Deterministic retryable timeout fixture outcome."""

    def __init__(self) -> None:
        super().__init__("provider_timeout", retryable=True, detail="provider timed out")


class MockProviderRejectedError(MockProviderError):
    """A fixture deliberately rejects an invalid provider request/output."""

    def __init__(self, code: str) -> None:
        super().__init__(code, retryable=False, detail="provider fixture rejected request")


@dataclass(frozen=True, slots=True)
class EmptyResearchResult:
    """Phase 3's deliberate no-web/no-fact-check research completion."""

    snapshot_id: UUID

    def structured_content(self) -> dict[str, object]:
        """Return the frozen Phase 2 ``ResearchResult`` body sans envelope."""

        return {"topic_items": [], "fact_checks": []}


@dataclass(frozen=True, slots=True)
class ResearchWebEvidence:
    id: UUID
    url: str
    title: str
    domain: str
    accessed_at: datetime
    snippet_hash: str


@dataclass(frozen=True, slots=True)
class ResearchTopicItem:
    text: str
    web_evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class ResearchFactCheck:
    source_anchor_id: UUID
    source_claim_quote: str
    verdict: Literal["supported", "refuted", "mixed", "unverifiable"]
    explanation: str
    web_evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class FixtureResearchResult:
    """Validated alias-free research output plus its persistence inputs."""

    snapshot_id: UUID
    topic_items: tuple[ResearchTopicItem, ...]
    fact_checks: tuple[ResearchFactCheck, ...]
    web_evidence: tuple[ResearchWebEvidence, ...]

    def structured_content(self) -> dict[str, object]:
        return {
            "topic_items": [
                {
                    "text": item.text,
                    "web_evidence_ids": [str(value) for value in item.web_evidence_ids],
                }
                for item in self.topic_items
            ],
            "fact_checks": [
                {
                    "source_anchor_id": str(item.source_anchor_id),
                    "source_claim_quote": item.source_claim_quote,
                    "verdict": item.verdict,
                    "explanation": item.explanation,
                    "web_evidence_ids": [str(value) for value in item.web_evidence_ids],
                }
                for item in self.fact_checks
            ],
        }


@dataclass(frozen=True, slots=True)
class _FixtureAnchor:
    """Internal fixture-only alias mapping.  Never crosses this module boundary."""

    alias: str
    classification: str
    atomic_quotes: tuple[str, ...]
    exact_quote: str
    participant: str


class MockProvider:
    """Resolve reviewed fixture content into runtime UUID-grounded output."""

    provider: Final[str] = "mock"
    model: Final[str] = "fixture-v1"
    prompt_version: Final[str] = "mock-provider.prompt.v1"

    def __init__(self, fixtures_root: Path | None = None) -> None:
        self._fixtures_root = (fixtures_root or _default_fixtures_root()).resolve()
        self._source_anchors: tuple[_FixtureAnchor, ...] | None = None

    def generate_summary(
        self,
        anchors: tuple[RuntimeSourceAnchor, ...] | list[RuntimeSourceAnchor],
        *,
        assertion: str | None = None,
        requested_anchor_ids: tuple[UUID, ...] | list[UUID] | None = None,
        fixture_id: str = _GROUNDED_FIXTURE,
        attempt: int = 1,
    ) -> GroundedSummary:
        """Produce a source-only summary or a typed deterministic failure.

        ``fixture_id`` and ``attempt`` are test harness inputs only.  They are
        intentionally absent from returned values and persistence payloads.
        """

        if attempt < 1:
            raise ValueError("fixture attempt must be positive")
        runtime_anchors = tuple(anchors)
        self._assert_requested_anchors_are_safe(runtime_anchors, requested_anchor_ids)

        if fixture_id == _RETRY_FIXTURE:
            retry = self._read_fixture("summary", fixture_id)
            if attempt == 1:
                self._assert_retry_fixture(retry)
                raise MockProviderTimeoutError()
            return self._ground_retry_success(retry, runtime_anchors, assertion)

        if fixture_id in _REJECTION_FIXTURES:
            rejection = self._read_fixture("summary", fixture_id)
            self._raise_fixture_rejection(rejection)

        if fixture_id != _GROUNDED_FIXTURE:
            raise MockProviderUnavailableError("unknown_fixture")
        fixture = self._read_fixture("summary", fixture_id)
        try:
            candidate = self._candidate_from_grounded_fixture(fixture, runtime_anchors)
            summary = _ground_reviewed_candidate(runtime_anchors, candidate)
        except MockProviderUnavailableError:
            summary = _ground_extractive_fallback(runtime_anchors)
        if assertion is not None:
            require_assertion_grounded(assertion, summary)
        return summary

    def generate_empty_research(self, *, snapshot_id: UUID) -> EmptyResearchResult:
        """Complete the required Phase 3 aggregate without Phase 5 web work."""

        return EmptyResearchResult(snapshot_id=snapshot_id)

    def generate_research(
        self,
        anchors: tuple[RuntimeSourceAnchor, ...] | list[RuntimeSourceAnchor],
        *,
        snapshot_id: UUID,
    ) -> FixtureResearchResult:
        """Map reviewed research fixtures to runtime anchors by exact quote.

        Unknown source material receives an explicit source-only evidence-gap
        result rather than fabricated corroboration or an empty artifact.
        """

        runtime_anchors = tuple(anchors)
        topic_items: list[ResearchTopicItem] = []
        fact_checks: list[ResearchFactCheck] = []
        evidence_by_alias: dict[str, ResearchWebEvidence] = {}
        matched_anchor_ids: set[UUID] = set()
        for fixture_id in (
            "research-supported-001",
            "research-refuted-001",
            "research-mixed-001",
            "research-unverifiable-001",
        ):
            research = self._read_fixture("research", fixture_id)
            quote = _required_string(research.get("source_claim_quote"), "research quote")
            fixture_alias = _required_string(research.get("source_anchor_id"), "research anchor")
            fixture_anchor = self._fixture_anchor(fixture_alias)
            if quote not in fixture_anchor.atomic_quotes:
                raise MockProviderRejectedError("malformed_schema")
            try:
                runtime_anchor = self._resolve_runtime_anchor(fixture_anchor, quote, runtime_anchors)
            except MockProviderUnavailableError:
                continue
            matched_anchor_ids.add(runtime_anchor.id)
            evidence_ids = self._research_evidence_ids(
                research, snapshot_id=snapshot_id, evidence_by_alias=evidence_by_alias
            )
            factcheck_id = fixture_id.replace("research-", "factcheck-")
            factcheck = self._read_fixture("factcheck", factcheck_id)
            if (
                factcheck.get("source_anchor_id") != fixture_alias
                or factcheck.get("source_claim_quote") != quote
                or factcheck.get("web_evidence_ids") != research.get("web_evidence_ids")
            ):
                raise MockProviderRejectedError("malformed_schema")
            verdict = _required_string(factcheck.get("verdict"), "fact-check verdict")
            outcome = _required_string(research.get("outcome"), "research outcome")
            if verdict != outcome or verdict not in {"supported", "refuted", "mixed", "unverifiable"}:
                raise MockProviderRejectedError("malformed_schema")
            topic_items.append(
                ResearchTopicItem(
                    text=_required_string(research.get("finding"), "research finding"),
                    web_evidence_ids=evidence_ids,
                )
            )
            fact_checks.append(
                ResearchFactCheck(
                    source_anchor_id=runtime_anchor.id,
                    source_claim_quote=quote,
                    verdict=verdict,  # type: ignore[arg-type]
                    explanation=_required_string(factcheck.get("rationale"), "fact-check rationale"),
                    web_evidence_ids=evidence_ids,
                )
            )

        fallback_candidates = tuple(
            anchor
            for anchor in runtime_anchors
            if anchor.id not in matched_anchor_ids
            and not _looks_instruction_like(anchor.exact_quote)
        )
        for anchor in _round_robin_anchors(
            fallback_candidates,
            limit=max(0, 100 - len(fact_checks)),
        ):
            bounded_anchor = RuntimeSourceAnchor(
                id=anchor.id,
                revision_id=anchor.revision_id,
                exact_quote=anchor.exact_quote[:20_000],
                classification=anchor.classification,
                participant=anchor.participant,
            )
            evidence = _fallback_evidence(snapshot_id, bounded_anchor)
            evidence_by_alias[str(evidence.id)] = evidence
            topic_items.append(
                ResearchTopicItem(
                    text="No independent web evidence is available for this source claim.",
                    web_evidence_ids=(evidence.id,),
                )
            )
            fact_checks.append(
                ResearchFactCheck(
                    source_anchor_id=anchor.id,
                    source_claim_quote=bounded_anchor.exact_quote,
                    verdict="unverifiable",
                    explanation="The deterministic offline provider has no independent evidence for this source claim.",
                    web_evidence_ids=(evidence.id,),
                )
            )
        if not fact_checks:
            raise MockProviderUnavailableError()
        return FixtureResearchResult(
            snapshot_id=snapshot_id,
            topic_items=tuple(topic_items),
            fact_checks=tuple(fact_checks),
            web_evidence=tuple(evidence_by_alias.values()),
        )

    def _research_evidence_ids(
        self,
        fixture: dict[str, Any],
        *,
        snapshot_id: UUID,
        evidence_by_alias: dict[str, ResearchWebEvidence],
    ) -> tuple[UUID, ...]:
        aliases = _required_string_list(fixture.get("web_evidence_ids"), "web evidence aliases")
        ids: list[UUID] = []
        for alias in aliases:
            evidence = evidence_by_alias.get(alias)
            if evidence is None:
                raw = self._read_fixture("web_evidence", alias)
                if raw.get("web_evidence_id") != alias or raw.get("synthetic") is not True:
                    raise MockProviderRejectedError("malformed_schema")
                url = _required_string(raw.get("url"), "evidence URL")
                domain = _required_string(raw.get("domain"), "evidence domain")
                if urlsplit(url).hostname != domain:
                    raise MockProviderRejectedError("malformed_schema")
                snippet_hash = _required_string(raw.get("snippet_hash"), "snippet hash")
                if not snippet_hash.startswith("sha256:") or len(snippet_hash) != 71:
                    raise MockProviderRejectedError("malformed_schema")
                try:
                    accessed_at = datetime.fromisoformat(
                        _required_string(raw.get("accessed_at"), "accessed at").replace("Z", "+00:00")
                    )
                except ValueError as error:
                    raise MockProviderRejectedError("malformed_schema") from error
                evidence = ResearchWebEvidence(
                    id=uuid5(snapshot_id, alias),
                    url=url,
                    title=_required_string(raw.get("title"), "evidence title"),
                    domain=domain,
                    accessed_at=accessed_at,
                    snippet_hash=snippet_hash.removeprefix("sha256:"),
                )
                evidence_by_alias[alias] = evidence
            ids.append(evidence.id)
        return tuple(ids)

    def _ground_retry_success(
        self,
        fixture: dict[str, Any],
        anchors: tuple[RuntimeSourceAnchor, ...],
        assertion: str | None,
    ) -> GroundedSummary:
        response = _required_mapping(fixture.get("response"), "retry response")
        attempts = _required_list(response.get("attempts"), "retry attempts")
        if len(attempts) != 2:
            raise MockProviderRejectedError("malformed_schema")
        second = _required_mapping(attempts[1], "retry success")
        if set(second) != {
            "attempt",
            "status",
            "text",
            "source_anchor_ids",
            "supporting_quotes",
        } or second.get("attempt") != 2 or second.get("status") != "succeeded":
            raise MockProviderRejectedError("malformed_schema")
        item = self._item_from_fixture(
            {
                "text": second["text"],
                "source_anchor_ids": second["source_anchor_ids"],
                "supporting_quotes": second["supporting_quotes"],
            },
            anchors,
        )
        summary = _ground_reviewed_candidate(
            anchors,
            SummaryCandidate(
                sections=(SummarySectionCandidate(heading="Participant updates", items=(item,)),)
            ),
        )
        if assertion is not None:
            require_assertion_grounded(assertion, summary)
        return summary

    def _candidate_from_grounded_fixture(
        self,
        fixture: dict[str, Any],
        anchors: tuple[RuntimeSourceAnchor, ...],
    ) -> SummaryCandidate:
        response = _required_mapping(fixture.get("response"), "summary response")
        if set(response) != {"sections"}:
            raise MockProviderRejectedError("malformed_schema")
        sections = _required_list(response.get("sections"), "summary sections")
        candidate_sections: list[SummarySectionCandidate] = []
        for index, raw_section in enumerate(sections):
            section = _required_mapping(raw_section, f"summary section {index}")
            if set(section) != {"items"}:
                raise MockProviderRejectedError("malformed_schema")
            raw_items = _required_list(section.get("items"), f"summary section {index} items")
            mapped_items: list[SummaryItemCandidate] = []
            for raw_item in raw_items:
                try:
                    mapped_items.append(self._item_from_fixture(_required_mapping(raw_item, "summary item"), anchors))
                except MockProviderUnavailableError:
                    # Fixture maps/reduces only source material present in the
                    # snapshot.  A partial source set therefore remains safe.
                    continue
            if mapped_items:
                candidate_sections.append(
                    SummarySectionCandidate(
                        heading="Participant updates", items=tuple(mapped_items)
                    )
                )
        if not candidate_sections:
            raise MockProviderUnavailableError()
        return SummaryCandidate(sections=tuple(candidate_sections))

    def _item_from_fixture(
        self,
        item: dict[str, Any],
        anchors: tuple[RuntimeSourceAnchor, ...],
    ) -> SummaryItemCandidate:
        if set(item) != {"text", "source_anchor_ids", "supporting_quotes"}:
            raise MockProviderRejectedError("malformed_schema")
        text = _required_string(item.get("text"), "summary item text")
        alias_ids = _required_string_list(item.get("source_anchor_ids"), "summary source anchors")
        supporting_quotes = _required_list(item.get("supporting_quotes"), "summary support")
        candidates: list[SummarySupportCandidate] = []
        mapped_ids: list[UUID] = []
        aliases_from_support: set[str] = set()
        for raw_support in supporting_quotes:
            support = _required_mapping(raw_support, "summary support")
            if set(support) != {"source_anchor_id", "exact_quote"}:
                raise MockProviderRejectedError("malformed_schema")
            alias = _required_string(support.get("source_anchor_id"), "fixture support alias")
            quote = _required_string(support.get("exact_quote"), "fixture support quote")
            fixture_anchor = self._fixture_anchor(alias)
            if quote not in fixture_anchor.atomic_quotes:
                raise MockProviderRejectedError("malformed_schema")
            runtime_anchor = self._resolve_runtime_anchor(
                fixture_anchor, quote, anchors
            )
            candidates.append(
                SummarySupportCandidate(
                    source_anchor_id=runtime_anchor.id,
                    exact_quote=quote,
                )
            )
            mapped_ids.append(runtime_anchor.id)
            aliases_from_support.add(alias)
        if set(alias_ids) != aliases_from_support or len(alias_ids) != len(set(alias_ids)):
            raise MockProviderRejectedError("malformed_schema")
        if len(mapped_ids) != len(set(mapped_ids)):
            raise MockProviderRejectedError("malformed_schema")
        return SummaryItemCandidate(
            text=text,
            source_anchor_ids=tuple(mapped_ids),
            supports=tuple(candidates),
        )

    def _assert_requested_anchors_are_safe(
        self,
        anchors: tuple[RuntimeSourceAnchor, ...],
        requested_anchor_ids: tuple[UUID, ...] | list[UUID] | None,
    ) -> None:
        if requested_anchor_ids is None:
            return
        by_id = {anchor.id: anchor for anchor in anchors}
        if len(by_id) != len(anchors):
            raise MockProviderRejectedError("duplicate_anchor")
        for requested_id in requested_anchor_ids:
            anchor = by_id.get(requested_id)
            if anchor is None:
                raise ForeignAnchorError()
            fixture_anchor = self._matching_fixture_anchor(anchor)
            if fixture_anchor is None:
                raise UnsupportedAssertionError()
            if fixture_anchor.classification == "instruction_like_content":
                raise SourcePromptInjectionError()
            if fixture_anchor.classification != "factual_claim":
                raise MockProviderRejectedError("unsupported_anchor")

    def _resolve_runtime_anchor(
        self,
        fixture_anchor: _FixtureAnchor,
        quote: str,
        anchors: tuple[RuntimeSourceAnchor, ...],
    ) -> RuntimeSourceAnchor:
        matches = [
            anchor
            for anchor in anchors
            if _quote_matches(anchor.exact_quote, quote)
        ]
        if len(matches) != 1:
            raise MockProviderUnavailableError()
        selected = matches[0]
        # Preserve the fixture's reviewed source classification only at the
        # in-memory grounding boundary.  The provider alias never leaves here.
        return RuntimeSourceAnchor(
            id=selected.id,
            revision_id=selected.revision_id,
            exact_quote=selected.exact_quote,
            classification=fixture_anchor.classification,
            participant=fixture_anchor.participant,
        )

    def _matching_fixture_anchor(
        self, runtime_anchor: RuntimeSourceAnchor
    ) -> _FixtureAnchor | None:
        matches = [
            fixture_anchor
            for fixture_anchor in self._load_source_anchors()
            if any(
                _quote_matches(runtime_anchor.exact_quote, atomic_quote)
                for atomic_quote in fixture_anchor.atomic_quotes
            )
        ]
        return matches[0] if len(matches) == 1 else None

    def _fixture_anchor(self, alias: str) -> _FixtureAnchor:
        for anchor in self._load_source_anchors():
            if anchor.alias == alias:
                return anchor
        raise MockProviderRejectedError("foreign_anchor")

    def _load_source_anchors(self) -> tuple[_FixtureAnchor, ...]:
        if self._source_anchors is not None:
            return self._source_anchors
        document = self._read_fixture("source", "meeting-pack-001")
        raw_anchors = _required_list(document.get("anchors"), "source anchors")
        anchors: list[_FixtureAnchor] = []
        for raw_anchor in raw_anchors:
            anchor = _required_mapping(raw_anchor, "source anchor")
            if set(anchor) != {
                "anchor_id",
                "anchor_type",
                "atomic_quotes",
                "exact_quote",
                "participant",
                "revision_id",
            }:
                raise MockProviderRejectedError("malformed_schema")
            anchors.append(
                _FixtureAnchor(
                    alias=_required_string(anchor.get("anchor_id"), "source anchor alias"),
                    classification=_required_string(anchor.get("anchor_type"), "source anchor type"),
                    atomic_quotes=tuple(
                        _required_string_list(
                            anchor.get("atomic_quotes"), "source atomic quotes"
                        )
                    ),
                    exact_quote=_required_string(anchor.get("exact_quote"), "source quote"),
                    participant=_required_string(anchor.get("participant"), "source participant"),
                )
            )
        if len({anchor.alias for anchor in anchors}) != len(anchors):
            raise MockProviderRejectedError("malformed_schema")
        self._source_anchors = tuple(anchors)
        return self._source_anchors

    def _assert_retry_fixture(self, fixture: dict[str, Any]) -> None:
        response = _required_mapping(fixture.get("response"), "retry response")
        attempts = _required_list(response.get("attempts"), "retry attempts")
        if len(attempts) != 2:
            raise MockProviderRejectedError("malformed_schema")
        first = _required_mapping(attempts[0], "retry first attempt")
        if first.get("status") != "failed" or first.get("error_code") != "provider_timeout":
            raise MockProviderRejectedError("malformed_schema")

    def _raise_fixture_rejection(self, fixture: dict[str, Any]) -> None:
        if fixture.get("expected_rejection") is not True:
            raise MockProviderRejectedError("malformed_schema")
        response = _required_mapping(fixture.get("response"), "rejection response")
        code = _required_string(response.get("error_code"), "rejection error code")
        if code == "provider_timeout":
            raise MockProviderTimeoutError()
        raise MockProviderRejectedError(code)

    def _read_fixture(self, category: str, fixture_id: str) -> dict[str, Any]:
        path = self._fixtures_root / category / f"{fixture_id}.json"
        try:
            raw = path.read_bytes()
            document = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MockProviderUnavailableError("malformed_schema") from error
        if not isinstance(document, dict):
            raise MockProviderUnavailableError("malformed_schema")
        if document.get("schema_version") != _SCHEMA_VERSION:
            raise MockProviderUnavailableError("malformed_schema")
        if document.get("fixture_id") != fixture_id:
            raise MockProviderUnavailableError("malformed_schema")
        return document


def _default_fixtures_root() -> Path:
    return Path(__file__).resolve().parents[3] / "provider_fixtures"


def _quote_matches(anchor_quote: str, support_quote: str) -> bool:
    normalized_anchor = _normalize(anchor_quote)
    normalized_support = _normalize(support_quote)
    return normalized_anchor == normalized_support or normalized_support in normalized_anchor


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _looks_instruction_like(value: str) -> bool:
    normalized = _normalize(value).casefold()
    return "ignore" in normalized and ("instruction" in normalized or "prompt" in normalized)


def _fallback_evidence(snapshot_id: UUID, anchor: RuntimeSourceAnchor) -> ResearchWebEvidence:
    digest = hashlib.sha256(_normalize(anchor.exact_quote).encode("utf-8")).hexdigest()
    evidence_id = uuid5(snapshot_id, f"offline-gap:{anchor.id}:{digest}")
    return ResearchWebEvidence(
        id=evidence_id,
        url=f"https://fixtures.invalid/evidence/offline-gap/{digest}",
        title="Offline evidence gap",
        domain="fixtures.invalid",
        accessed_at=datetime.fromtimestamp(0, tz=timezone.utc),
        snippet_hash=digest,
    )


def _required_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MockProviderRejectedError("malformed_schema")
    return value


def _required_list(value: object, label: str) -> list[object]:
    del label
    if not isinstance(value, list) or not value:
        raise MockProviderRejectedError("malformed_schema")
    return value


def _required_string(value: object, label: str) -> str:
    del label
    if not isinstance(value, str) or not value.strip():
        raise MockProviderRejectedError("malformed_schema")
    return value


def _required_string_list(value: object, label: str) -> list[str]:
    values = _required_list(value, label)
    strings = [_required_string(item, label) for item in values]
    if len(strings) != len(set(strings)):
        raise MockProviderRejectedError("malformed_schema")
    return strings


def _ground_reviewed_candidate(
    anchors: tuple[RuntimeSourceAnchor, ...], candidate: SummaryCandidate
) -> GroundedSummary:
    """Ground only the fixed assertion/support pairings curated in fixtures."""

    approved = tuple(
        ApprovedSummaryAssertion(text=text, supports=item.supports)
        for section in candidate.sections
        for item in section.items
        for text, expected_quotes in _REVIEWED_SUMMARY_ASSERTIONS
        if tuple(support.exact_quote for support in item.supports) == expected_quotes
    )
    return ground_summary(anchors, candidate, approved_assertions=approved)


def _ground_extractive_fallback(
    anchors: tuple[RuntimeSourceAnchor, ...],
) -> GroundedSummary:
    """Return exact source text only; never infer an unreviewed paraphrase."""

    items: list[SummaryItemCandidate] = []
    approved: list[ApprovedSummaryAssertion] = []
    safe_anchors: list[RuntimeSourceAnchor] = []
    for anchor in anchors:
        if _looks_instruction_like(anchor.exact_quote):
            continue
        excerpt = isolated_summary_excerpt(anchor.exact_quote)
        if excerpt is None:
            continue
        support = SummarySupportCandidate(
            source_anchor_id=anchor.id, exact_quote=excerpt
        )
        items.append(
            SummaryItemCandidate(
                text=excerpt,
                source_anchor_ids=(anchor.id,),
                supports=(support,),
            )
        )
        approved.append(ApprovedSummaryAssertion(text=excerpt, supports=(support,)))
        safe_anchors.append(anchor)
    if not items:
        raise MockProviderUnavailableError()
    return ground_summary(
        safe_anchors,
        SummaryCandidate(
            sections=(
                SummarySectionCandidate(heading="Source highlights", items=tuple(items)),
            )
        ),
        approved_assertions=approved,
    )


def _round_robin_anchors(
    anchors: tuple[RuntimeSourceAnchor, ...], *, limit: int
) -> tuple[RuntimeSourceAnchor, ...]:
    """Select a bounded, deterministic set while retaining every document."""

    if limit <= 0:
        return ()
    grouped: dict[UUID, list[RuntimeSourceAnchor]] = {}
    for anchor in anchors:
        grouped.setdefault(anchor.revision_id, []).append(anchor)
    groups = tuple(grouped.values())
    selected: list[RuntimeSourceAnchor] = []
    for index in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if index < len(group):
                selected.append(group[index])
                if len(selected) == limit:
                    return tuple(selected)
    return tuple(selected)
