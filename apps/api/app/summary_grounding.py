"""Fail-closed normalization for source-grounded summary output.

The temporary provider experiment deliberately keeps its fixture aliases out
of the application boundary.  This module only accepts server-issued source
anchor UUIDs and exact source spans, then produces the JSON shape that may be
persisted for a summary document.  It has no web/research concepts by design.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID


_URL_PATTERN: Final = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
_VERDICT_PATTERN: Final = re.compile(
    r"\b(?:fact[ -]?check|web[ -]?evidence|verdict|supported|refuted|mixed|unverifiable)\b",
    re.IGNORECASE,
)
_INSTRUCTION_PATTERN: Final = re.compile(
    r"\b(?:ignore|disregard|override|forget)\b.{0,96}\b(?:instruction|prompt|previous)\b",
    re.IGNORECASE | re.DOTALL,
)


class SummaryGroundingError(ValueError):
    """A provider candidate cannot become a persisted grounded summary."""

    code: str

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(detail)


class ForeignAnchorError(SummaryGroundingError):
    """A candidate names an anchor outside the closed snapshot."""

    def __init__(self) -> None:
        super().__init__("foreign_anchor", "summary support references a foreign anchor")


class SourcePromptInjectionError(SummaryGroundingError):
    """Untrusted instruction-like source content was selected as support."""

    def __init__(self) -> None:
        super().__init__(
            "source_prompt_injection",
            "instruction-like source content cannot support a summary",
        )


class UnsupportedAssertionError(SummaryGroundingError):
    """An assertion has no exact accepted summary/source support."""

    def __init__(self) -> None:
        super().__init__("assertion_not_grounded", "assertion is not exactly grounded")


class SummaryIsolationError(SummaryGroundingError):
    """A summary candidate attempts to cross the summary/research boundary."""

    def __init__(self, detail: str) -> None:
        super().__init__("summary_isolation_violation", detail)


@dataclass(frozen=True, slots=True)
class RuntimeSourceAnchor:
    """The minimum immutable source context allowed into summary grounding."""

    id: UUID
    revision_id: UUID
    exact_quote: str
    classification: str = "factual_claim"
    participant: str | None = None
    block_type: str = "unknown"
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.exact_quote.strip():
            raise ValueError("runtime source anchor exact_quote must not be blank")
        if not self.classification.strip():
            raise ValueError("runtime source anchor classification must not be blank")
        if not self.block_type.strip():
            raise ValueError("runtime source anchor block_type must not be blank")
        if self.confidence is not None and (
            isinstance(self.confidence, bool) or not 0 <= self.confidence <= 1
        ):
            raise ValueError("runtime source anchor confidence must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class SummarySupportCandidate:
    """A provider-selected source span before offset normalization."""

    source_anchor_id: UUID
    exact_quote: str

    def __post_init__(self) -> None:
        if not self.exact_quote.strip():
            raise ValueError("summary support exact_quote must not be blank")


@dataclass(frozen=True, slots=True)
class SummaryItemCandidate:
    """One provider item with only source-anchor support information."""

    text: str
    source_anchor_ids: tuple[UUID, ...]
    supports: tuple[SummarySupportCandidate, ...]

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("summary item text must not be blank")
        if not self.source_anchor_ids:
            raise ValueError("summary item must declare source anchors")
        if not self.supports:
            raise ValueError("summary item must include exact support")


@dataclass(frozen=True, slots=True)
class SummarySectionCandidate:
    """A grouping-only section; its heading adds no factual content."""

    heading: str
    items: tuple[SummaryItemCandidate, ...]

    def __post_init__(self) -> None:
        if not self.heading.strip():
            raise ValueError("summary section heading must not be blank")
        if not self.items:
            raise ValueError("summary section must have at least one item")


@dataclass(frozen=True, slots=True)
class SummaryCandidate:
    """Provider response accepted at the provider/grounding boundary."""

    sections: tuple[SummarySectionCandidate, ...]

    def __post_init__(self) -> None:
        if not self.sections:
            raise ValueError("summary must have at least one section")


@dataclass(frozen=True, slots=True)
class ApprovedSummaryAssertion:
    """A reviewed, deterministic assertion/support pairing from a fixture.

    This is deliberately supplied by the trusted fixture adapter, rather than
    by a provider candidate.  Exact quote checks alone cannot prove semantic
    entailment, so Phase 3 accepts only these reviewed fixture paraphrases.
    """

    text: str
    supports: tuple[SummarySupportCandidate, ...]

    def __post_init__(self) -> None:
        if not self.text.strip() or not self.supports:
            raise ValueError("approved assertion requires text and exact support")


@dataclass(frozen=True, slots=True)
class GroundedSummarySupport:
    """A persisted exact source span, including code-point offsets."""

    source_anchor_id: UUID
    exact_quote: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class GroundedSummaryItem:
    """A summary item proven against one or more snapshot anchors."""

    text: str
    source_anchor_ids: tuple[UUID, ...]
    supports: tuple[GroundedSummarySupport, ...]


@dataclass(frozen=True, slots=True)
class GroundedSummarySection:
    heading: str
    items: tuple[GroundedSummaryItem, ...]


@dataclass(frozen=True, slots=True)
class GroundedSummary:
    """The source-only portion of a canonical persisted summary document."""

    sections: tuple[GroundedSummarySection, ...]

    def structured_content(self) -> dict[str, object]:
        """Return JSON-safe content without provider aliases or research fields."""

        return {
            "sections": [
                {
                    "heading": section.heading,
                    "items": [
                        {
                            "text": item.text,
                            "source_anchor_ids": [
                                str(anchor_id) for anchor_id in item.source_anchor_ids
                            ],
                            "supports": [
                                {
                                    "source_anchor_id": str(support.source_anchor_id),
                                    "exact_quote": support.exact_quote,
                                    "start": support.start,
                                    "end": support.end,
                                }
                                for support in item.supports
                            ],
                        }
                        for item in section.items
                    ],
                }
                for section in self.sections
            ]
        }

    def accepted_texts(self) -> tuple[str, ...]:
        """Return exact normalized statements that may satisfy an assertion check."""

        return tuple(
            item.text
            for section in self.sections
            for item in section.items
        )


def ground_summary(
    anchors: Iterable[RuntimeSourceAnchor],
    candidate: SummaryCandidate,
    *,
    approved_assertions: Iterable[ApprovedSummaryAssertion],
) -> GroundedSummary:
    """Validate exact support and return a source-only persisted summary.

    This is intentionally conservative: unknown anchors, non-factual anchors,
    instruction-like content, quotes that are not literal source substrings,
    and summary/research contamination all fail closed.
    """

    approved_by_signature: dict[tuple[str, frozenset[tuple[UUID, str]]], ApprovedSummaryAssertion] = {}
    for approved in approved_assertions:
        signature = _assertion_signature(approved.text, approved.supports)
        if signature in approved_by_signature:
            raise SummaryGroundingError(
                "duplicate_approved_assertion",
                "approved fixture assertions must be unique",
            )
        approved_by_signature[signature] = approved
    if not approved_by_signature:
        raise SummaryGroundingError(
            "missing_approved_assertion",
            "summary grounding requires reviewed fixture assertions",
        )

    anchor_by_id: dict[UUID, RuntimeSourceAnchor] = {}
    for anchor in anchors:
        if anchor.id in anchor_by_id:
            raise SummaryGroundingError("duplicate_anchor", "snapshot contains duplicate anchors")
        anchor_by_id[anchor.id] = anchor

    grounded_sections: list[GroundedSummarySection] = []
    for section in candidate.sections:
        _assert_summary_text_is_isolated(section.heading)
        grounded_items: list[GroundedSummaryItem] = []
        for item in section.items:
            _assert_summary_text_is_isolated(item.text)
            declared_ids = set(item.source_anchor_ids)
            if len(declared_ids) != len(item.source_anchor_ids):
                raise SummaryGroundingError(
                    "duplicate_anchor", "summary item source anchor IDs must be unique"
                )

            grounded_supports: list[GroundedSummarySupport] = []
            support_ids: set[UUID] = set()
            support_pairs: set[tuple[UUID, str]] = set()
            for support in item.supports:
                selected_anchor = anchor_by_id.get(support.source_anchor_id)
                if selected_anchor is None:
                    raise ForeignAnchorError()
                _assert_anchor_is_summary_safe(selected_anchor)
                pair = (support.source_anchor_id, support.exact_quote)
                if pair in support_pairs:
                    raise SummaryGroundingError(
                        "duplicate_support", "summary item support spans must be unique"
                    )
                support_pairs.add(pair)
                start = selected_anchor.exact_quote.find(support.exact_quote)
                if start < 0:
                    raise SummaryGroundingError(
                        "support_quote_mismatch",
                        "summary support quote is not an exact source substring",
                    )
                support_ids.add(support.source_anchor_id)
                grounded_supports.append(
                    GroundedSummarySupport(
                        source_anchor_id=support.source_anchor_id,
                        exact_quote=support.exact_quote,
                        start=start,
                        end=start + len(support.exact_quote),
                    )
                )

            if declared_ids != support_ids:
                raise SummaryGroundingError(
                    "support_anchor_mismatch",
                    "summary source anchors must exactly match support anchors",
                )
            candidate_signature = _assertion_signature(item.text, item.supports)
            if candidate_signature not in approved_by_signature:
                raise UnsupportedAssertionError()
            grounded_items.append(
                GroundedSummaryItem(
                    text=item.text,
                    source_anchor_ids=tuple(item.source_anchor_ids),
                    supports=tuple(grounded_supports),
                )
            )
        grounded_sections.append(
            GroundedSummarySection(heading=section.heading, items=tuple(grounded_items))
        )
    return GroundedSummary(sections=tuple(grounded_sections))


def ground_live_summary(
    candidate: SummaryCandidate,
    anchors: Sequence[RuntimeSourceAnchor],
) -> GroundedSummary:
    """Normalize an approved live-provider summary against immutable anchors.

    Unlike the fixture-only ``ground_summary`` gate, this path does not require
    a pre-reviewed assertion catalog. It still fails closed on foreign anchors,
    unsafe source instructions, duplicate/mismatched support, and non-exact
    quotes. This boundary is limited to the owner-approved full Grok report
    pipeline; callers must not use it as a generic provider fallback.
    """

    anchor_by_id: dict[UUID, RuntimeSourceAnchor] = {}
    for anchor in anchors:
        if anchor.id in anchor_by_id:
            raise SummaryGroundingError("duplicate_anchor", "snapshot contains duplicate anchors")
        anchor_by_id[anchor.id] = anchor
    if not anchor_by_id:
        raise SummaryGroundingError("missing_anchor", "summary grounding requires source anchors")

    grounded_sections: list[GroundedSummarySection] = []
    for section in candidate.sections:
        _assert_summary_text_is_isolated(section.heading)
        grounded_items: list[GroundedSummaryItem] = []
        for item in section.items:
            _assert_summary_text_is_isolated(item.text)
            declared_ids = set(item.source_anchor_ids)
            if len(declared_ids) != len(item.source_anchor_ids):
                raise SummaryGroundingError("duplicate_anchor", "summary item source anchor IDs must be unique")
            supports: list[GroundedSummarySupport] = []
            support_ids: set[UUID] = set()
            seen_supports: set[tuple[UUID, str]] = set()
            for support in item.supports:
                selected_anchor = anchor_by_id.get(support.source_anchor_id)
                if selected_anchor is None:
                    raise ForeignAnchorError()
                _assert_anchor_is_summary_safe(selected_anchor)
                signature = (support.source_anchor_id, support.exact_quote)
                if signature in seen_supports:
                    raise SummaryGroundingError("duplicate_support", "summary item support spans must be unique")
                seen_supports.add(signature)
                start = selected_anchor.exact_quote.find(support.exact_quote)
                if start < 0:
                    raise SummaryGroundingError("support_quote_mismatch", "summary support quote is not an exact source substring")
                support_ids.add(support.source_anchor_id)
                supports.append(GroundedSummarySupport(
                    source_anchor_id=support.source_anchor_id,
                    exact_quote=support.exact_quote,
                    start=start,
                    end=start + len(support.exact_quote),
                ))
            if declared_ids != support_ids:
                raise SummaryGroundingError("support_anchor_mismatch", "summary source anchors must exactly match support anchors")
            grounded_items.append(GroundedSummaryItem(
                text=item.text,
                source_anchor_ids=tuple(item.source_anchor_ids),
                supports=tuple(supports),
            ))
        grounded_sections.append(GroundedSummarySection(heading=section.heading, items=tuple(grounded_items)))
    return GroundedSummary(sections=tuple(grounded_sections))


def require_assertion_grounded(assertion: str, summary: GroundedSummary) -> None:
    """Accept only a literal accepted summary statement or exact support quote.

    Semantic entailment is deliberately not inferred by an implementation that
    has no production model.  The conservative exact rule turns the approved
    ``valid anchor + unsupported assertion`` fixture into a deterministic
    blocking check.
    """

    normalized_assertion = _normalize_for_exact_match(assertion)
    if not normalized_assertion:
        raise UnsupportedAssertionError()
    accepted = {
        _normalize_for_exact_match(text)
        for text in summary.accepted_texts()
    }
    accepted.update(
        _normalize_for_exact_match(support.exact_quote)
        for section in summary.sections
        for item in section.items
        for support in item.supports
    )
    if normalized_assertion not in accepted:
        raise UnsupportedAssertionError()


def is_instruction_like_content(value: str) -> bool:
    """Classify the deliberately narrow prompt-injection fixture pattern."""

    return bool(_INSTRUCTION_PATTERN.search(value))


def _assert_anchor_is_summary_safe(anchor: RuntimeSourceAnchor) -> None:
    if anchor.classification == "instruction_like_content" or is_instruction_like_content(
        anchor.exact_quote
    ):
        raise SourcePromptInjectionError()
    if anchor.classification != "factual_claim":
        raise SummaryGroundingError(
            "unsupported_anchor",
            "only factual source anchors may support a summary",
        )


def _assert_summary_text_is_isolated(value: str) -> None:
    if not is_summary_text_isolated(value):
        raise SummaryIsolationError(
            "summary text must not contain URL, web-evidence, or verdict language"
        )


def is_summary_text_isolated(value: str) -> bool:
    """Return whether source text is safe to copy into the summary-only lane."""

    return _URL_PATTERN.search(value) is None and _VERDICT_PATTERN.search(value) is None


def isolated_summary_excerpt(value: str) -> str | None:
    """Return a literal source prefix that stays inside the summary-only lane."""

    if is_summary_text_isolated(value):
        candidate = value
    else:
        url_match = _URL_PATTERN.search(value)
        if url_match is None:
            return None
        candidate = value[: url_match.start()].rstrip(" |:-\t\r\n")
    if candidate.casefold() in {"source", "url", "reference", "references", "출처", "근거"}:
        return None
    candidate = candidate[:10_000].rstrip()
    return candidate if candidate and is_summary_text_isolated(candidate) else None


def _normalize_for_exact_match(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _assertion_signature(
    text: str,
    supports: Iterable[SummarySupportCandidate],
) -> tuple[str, frozenset[tuple[UUID, str]]]:
    pairs = frozenset(
        (support.source_anchor_id, support.exact_quote) for support in supports
    )
    if not pairs:
        raise ValueError("assertion signature requires at least one support")
    return (text, pairs)
