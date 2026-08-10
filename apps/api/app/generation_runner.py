"""Execution-only adapter between a claimed generation job and MockProvider.

Provider/grounding work happens outside a database transaction.  The returned
``GenerationExecution`` is deliberately inert until the orchestrator passes
it to a queue-fenced ``complete_with_effects`` callback together with
``GenerationRepository``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Final, Literal, cast
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from app.domain import JobState
from app.generation_repository import (
    CitationWrite,
    GeneratedSegmentWrite,
    GenerationAggregateProjection,
    GenerationCompletion,
    GenerationRepository,
    ResearchClaimWrite,
    WebCitationWrite,
    WebEvidenceWrite,
)
from app.generation_context import plan_generation_context
from app.generation_provider import GenerationProvider, GroundedResearch
from app.generation_retrieval import retrieve_generation_anchors
from app.mock_provider import MockProvider
from app.provider_errors import GenerationProviderFailure
from app.queue_repository import ClaimedJob
from app.summary_grounding import (
    GroundedSummary,
    GroundedSummaryItem,
    GroundedSummarySection,
    RuntimeSourceAnchor,
    SummaryGroundingError,
)


_GENERATION_KINDS: Final[frozenset[str]] = frozenset({"summary", "research"})


class GenerationRunnerError(RuntimeError):
    """The claimed queue payload does not identify a valid canonical run."""


@dataclass(frozen=True, slots=True)
class GenerationExecution:
    """Alias-free provider result or typed failure awaiting a fenced effect."""

    snapshot_id: UUID
    kind: Literal["summary", "research"]
    pipeline_version: str
    target_state: JobState
    result: Mapping[str, object]
    error_code: str | None
    retryable: bool
    completion: GenerationCompletion | None = None

    def __post_init__(self) -> None:
        if self.kind not in _GENERATION_KINDS:
            raise ValueError("generation execution kind must be summary or research")
        if not self.pipeline_version.strip():
            raise ValueError("generation execution pipeline_version must not be blank")
        if self.target_state is JobState.SUCCEEDED:
            if self.error_code is not None or self.completion is None or self.retryable:
                raise ValueError("successful execution requires exactly one completion")
        elif self.target_state in {JobState.FAILED_RETRYABLE, JobState.FAILED_TERMINAL}:
            if self.completion is not None or not self.error_code or self.error_code != self.error_code.strip():
                raise ValueError("failed execution requires a typed error and no completion")
        else:
            raise ValueError("generation execution must be terminal")

    def persist(
        self,
        cursor: psycopg.Cursor[Any],
        repository: GenerationRepository,
    ) -> GenerationAggregateProjection:
        """Apply the effect only after the queue callback has fenced the job."""

        if self.completion is not None:
            return repository.persist_success(cursor, self.completion)
        assert self.error_code is not None
        return repository.persist_failure(
            cursor,
            snapshot_id=self.snapshot_id,
            kind=self.kind,
            pipeline_version=self.pipeline_version,
            error_code=self.error_code,
            retryable=self.retryable,
        )

    def fenced_effect(
        self, repository: GenerationRepository
    ) -> Callable[[psycopg.Cursor[Any]], None]:
        """Return the exact callback for ``complete_with_effects``.

        The callback itself returns no payload so the queue owns transaction
        ordering and only invokes it after its lease CAS has succeeded.
        """

        def effect(cursor: psycopg.Cursor[Any]) -> None:
            self.persist(cursor, repository)

        return effect


class GenerationRunner:
    """Read a pinned snapshot, call the local fixture adapter, normalize once."""

    def __init__(
        self,
        provider: GenerationProvider | None = None,
        *,
        summary_fixture_id: str = "summary-grounded-001",
        retrieval_max_anchors: int = 64,
    ) -> None:
        self._provider: GenerationProvider = provider or cast(GenerationProvider, MockProvider())
        self._summary_fixture_id = summary_fixture_id
        self._retrieval_max_anchors = retrieval_max_anchors

    def execute(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        claimed: ClaimedJob,
    ) -> GenerationExecution:
        """Execute a claimed summary/research job without writing any result."""

        snapshot_id, kind, pipeline_version = _claimed_generation_identity(claimed)
        topic, candidates = self._snapshot_context(connection, snapshot_id=snapshot_id)
        try:
            retrieval = retrieve_generation_anchors(
                topic=_retrieval_query(topic, kind),
                anchors=candidates,
                max_anchors=self._retrieval_max_anchors,
            )
        except ValueError:
            return _failed_execution(
                snapshot_id=snapshot_id,
                kind=kind,
                pipeline_version=pipeline_version,
                error_code="retrieval_context_invalid",
                retryable=False,
            )
        anchors = retrieval.anchors
        try:
            if kind == "summary":
                plan = plan_generation_context(anchors)
                # Each document is independent and the approved live pipeline
                # explicitly requires document summaries to run in parallel.
                # ``executor.map`` preserves the stable document order used by
                # the deterministic synthesis step while executing the remote
                # calls concurrently.
                with ThreadPoolExecutor(
                    max_workers=min(4, len(plan.documents)),
                    thread_name_prefix="document-summary",
                ) as executor:
                    document_summaries = tuple(
                        executor.map(
                            lambda document: self._provider.generate_summary(
                                document.anchors,
                                fixture_id=self._summary_fixture_id,
                                attempt=claimed.lease_generation,
                            ),
                            plan.documents,
                        )
                    )
                summary = _synthesize_document_summaries(document_summaries)
                completion = _summary_completion(
                    snapshot_id=snapshot_id,
                    pipeline_version=pipeline_version,
                    summary=summary,
                    provider=self._provider,
                )
            else:
                research = self._provider.generate_research(
                    anchors, snapshot_id=snapshot_id
                )
                completion = _research_completion(
                    snapshot_id=snapshot_id,
                    pipeline_version=pipeline_version,
                    research=research,
                    provider=self._provider,
                )
        except GenerationProviderFailure as error:
            return _failed_execution(
                snapshot_id=snapshot_id,
                kind=kind,
                pipeline_version=pipeline_version,
                error_code=error.code,
                retryable=error.retryable,
            )
        except SummaryGroundingError as error:
            return _failed_execution(
                snapshot_id=snapshot_id,
                kind=kind,
                pipeline_version=pipeline_version,
                error_code=error.code,
                retryable=False,
            )
        return GenerationExecution(
            snapshot_id=snapshot_id,
            kind=kind,
            pipeline_version=pipeline_version,
            target_state=JobState.SUCCEEDED,
            result={
                **completion.job_result(),
                "retrieval": retrieval.metadata(),
            },
            error_code=None,
            retryable=False,
            completion=completion,
        )

    def _snapshot_context(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        snapshot_id: UUID,
    ) -> tuple[str, tuple[RuntimeSourceAnchor, ...]]:
        """Read the copied topic and only snapshot-pinned immutable anchors."""

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT snapshot.topic_copy, anchor.id, anchor.source_revision_id,
                       anchor.text, anchor.block_type, anchor.confidence
                FROM generation_snapshots AS snapshot
                JOIN snapshot_revisions AS snapshot_revision
                  ON snapshot_revision.snapshot_id = snapshot.id
                JOIN source_anchors AS anchor
                  ON anchor.source_revision_id = snapshot_revision.source_revision_id
                 AND anchor.extraction_run_id = snapshot_revision.extraction_run_id
                WHERE snapshot.id = %s
                ORDER BY anchor.source_revision_id, anchor.ordinal, anchor.id
                """,
                (snapshot_id,),
            )
            rows = cursor.fetchall()
        if not rows:
            raise GenerationRunnerError("generation snapshot has no source anchors")
        topic = _nonempty_text(rows[0]["topic_copy"], "generation snapshot topic")
        anchors = tuple(
            RuntimeSourceAnchor(
                id=_uuid_value(row["id"], "source anchor id"),
                revision_id=_uuid_value(row["source_revision_id"], "source revision id"),
                exact_quote=_nonempty_text(row["text"], "source anchor text"),
                block_type=_nonempty_text(row["block_type"], "source anchor block type"),
                confidence=(
                    None if row["confidence"] is None else float(row["confidence"])
                ),
            )
            for row in rows
        )
        return topic, anchors


def _retrieval_query(
    topic: str,
    kind: Literal["summary", "research"],
) -> str:
    if kind == "summary":
        intent = "핵심 결정 일정 담당자 합의 쟁점"
    else:
        intent = "외부 조사 사실 검증 배경 위험"
    return f"{topic} {intent}"


def _summary_completion(
    *,
    snapshot_id: UUID,
    pipeline_version: str,
    summary: GroundedSummary,
    provider: GenerationProvider,
) -> GenerationCompletion:
    """Turn grounded summary items into document segments and citations."""

    segments: list[GeneratedSegmentWrite] = []
    citations: list[CitationWrite] = []
    ordinal = 0
    for section in summary.sections:
        for item in section.items:
            segment = GeneratedSegmentWrite(id=uuid4(), ordinal=ordinal, text=item.text)
            segments.append(segment)
            for support in item.supports:
                citations.append(
                    CitationWrite(
                        id=uuid4(),
                        segment_id=segment.id,
                        source_anchor_id=support.source_anchor_id,
                    )
                )
            ordinal += 1
    return GenerationCompletion(
        snapshot_id=snapshot_id,
        kind="summary",
        pipeline_version=pipeline_version,
        document_id=uuid4(),
        structured_content=summary.structured_content(),
        segments=tuple(segments),
        citations=tuple(citations),
        provider=provider.provider,
        model=provider.model,
        prompt_version=provider.prompt_version,
    )


def _research_completion(
    *,
    snapshot_id: UUID,
    pipeline_version: str,
    research: GroundedResearch,
    provider: GenerationProvider,
) -> GenerationCompletion:
    """Normalize research rows and both citation types before fencing."""

    segments: list[GeneratedSegmentWrite] = []
    citations: list[CitationWrite | WebCitationWrite] = []
    claims: list[ResearchClaimWrite] = []
    ordinal = 0
    for topic_item in research.topic_items:
        segment = GeneratedSegmentWrite(id=uuid4(), ordinal=ordinal, text=topic_item.text)
        segments.append(segment)
        citations.extend(
            WebCitationWrite(id=uuid4(), segment_id=segment.id, web_evidence_id=evidence_id)
            for evidence_id in topic_item.web_evidence_ids
        )
        ordinal += 1
    for fact_check in research.fact_checks:
        segment = GeneratedSegmentWrite(id=uuid4(), ordinal=ordinal, text=fact_check.explanation)
        segments.append(segment)
        citations.append(
            CitationWrite(
                id=uuid4(),
                segment_id=segment.id,
                source_anchor_id=fact_check.source_anchor_id,
            )
        )
        citations.extend(
            WebCitationWrite(id=uuid4(), segment_id=segment.id, web_evidence_id=evidence_id)
            for evidence_id in fact_check.web_evidence_ids
        )
        claims.append(
            ResearchClaimWrite(
                id=uuid4(),
                claim_text=fact_check.source_claim_quote,
                source_anchor_id=fact_check.source_anchor_id,
                verdict=fact_check.verdict,
                explanation=fact_check.explanation,
            )
        )
        ordinal += 1
    return GenerationCompletion(
        snapshot_id=snapshot_id,
        kind="research",
        pipeline_version=pipeline_version,
        document_id=uuid4(),
        structured_content=research.structured_content(),
        segments=tuple(segments),
        citations=tuple(citations),
        web_evidence=tuple(
            WebEvidenceWrite(
                id=evidence.id,
                url=evidence.url,
                title=evidence.title,
                domain=evidence.domain,
                accessed_at=evidence.accessed_at,
                snippet_hash=evidence.snippet_hash,
            )
            for evidence in research.web_evidence
        ),
        research_claims=tuple(claims),
        provider=provider.provider,
        model=provider.model,
        prompt_version=provider.prompt_version,
    )


def _failed_execution(
    *,
    snapshot_id: UUID,
    kind: Literal["summary", "research"],
    pipeline_version: str,
    error_code: str,
    retryable: bool,
) -> GenerationExecution:
    target_state = JobState.FAILED_RETRYABLE if retryable else JobState.FAILED_TERMINAL
    return GenerationExecution(
        snapshot_id=snapshot_id,
        kind=kind,
        pipeline_version=pipeline_version,
        target_state=target_state,
        result={
            "snapshot_id": str(snapshot_id),
            "kind": kind,
            "status": target_state.value,
            "error_code": error_code,
        },
        error_code=error_code,
        retryable=retryable,
    )


def _synthesize_document_summaries(
    summaries: tuple[GroundedSummary, ...],
) -> GroundedSummary:
    """Deterministically reduce document summaries into one cited report."""

    items_by_heading: dict[str, list[GroundedSummaryItem]] = {}
    seen: set[tuple[str, tuple[UUID, ...]]] = set()
    per_document = [
        tuple((section.heading, item) for section in summary.sections for item in section.items)
        for summary in summaries
    ]
    total_items = 0
    for item_index in range(max((len(items) for items in per_document), default=0)):
        for items in per_document:
            if item_index >= len(items):
                continue
            heading, item = items[item_index]
            signature = (item.text, item.source_anchor_ids)
            if signature in seen:
                continue
            seen.add(signature)
            items_by_heading.setdefault(heading, []).append(item)
            total_items += 1
            if total_items == 100:
                break
        if total_items == 100:
            break
    sections = tuple(
        GroundedSummarySection(heading=heading, items=tuple(items))
        for heading, items in items_by_heading.items()
        if items
    )
    if not sections:
        raise SummaryGroundingError("empty_hierarchical_summary", "no document summary survived")
    return GroundedSummary(sections=sections)


def _claimed_generation_identity(
    claimed: ClaimedJob,
) -> tuple[UUID, Literal["summary", "research"], str]:
    if claimed.kind not in _GENERATION_KINDS:
        raise GenerationRunnerError("claimed job is not a generation kind")
    raw_snapshot_id = claimed.payload.get("snapshot_id")
    raw_kind = claimed.payload.get("kind")
    raw_pipeline = claimed.payload.get("pipeline_version")
    if not isinstance(raw_snapshot_id, str):
        raise GenerationRunnerError("generation job lacks snapshot identity")
    try:
        snapshot_id = UUID(raw_snapshot_id)
    except ValueError as error:
        raise GenerationRunnerError("generation job snapshot identity is invalid") from error
    if raw_kind != claimed.kind or raw_kind not in _GENERATION_KINDS:
        raise GenerationRunnerError("generation job kind does not match its payload")
    if not isinstance(raw_pipeline, str) or not raw_pipeline.strip():
        raise GenerationRunnerError("generation job lacks pipeline version")
    return snapshot_id, cast(Literal["summary", "research"], raw_kind), raw_pipeline


def _uuid_value(value: object, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError as error:
            raise GenerationRunnerError(f"{label} is invalid") from error
    raise GenerationRunnerError(f"{label} is invalid")


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GenerationRunnerError(f"{label} is invalid")
    return value
