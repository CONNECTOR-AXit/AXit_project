"""Fenced automatic report suggestions derived from pinned document comparisons."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Final, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.activity_policy import build_event_key
from app.activity_service import ActivityService
from app.document_comparison import (
    ComparisonAnchor,
    DocumentComparison,
    compare_anchor_sets,
)
from app.domain import JobState, StaleLeaseError
from app.integrated_report import report_content_hash
from app.grok_report_provider import ReportAnchor
from app.provider_errors import GenerationProviderFailure
from app.queue_repository import ClaimedJob, PostgresJobQueue


_JOB_KIND: Final = "report_suggestions"
_FAILURE_CODE: Final = "automatic_suggestion_failure"
_MAX_PROPOSALS: Final = 100
_MAX_DOCUMENT_PAIRS: Final = 100
_MAX_PROVIDER_ATTEMPTS: Final = 3
_MAX_PROVIDER_ANCHORS: Final = 400
_MAX_MERGED_DOCUMENT_BLOCKS: Final = 500
_MAX_MERGED_PARAGRAPH_LENGTH: Final = 20_000
_MAX_COVERAGE_ANCHORS_PER_BLOCK: Final = 10
_LOGGER = logging.getLogger(__name__)

SuggestionKind = Literal["add", "edit", "remove"]
ConnectionFactory = Callable[
    [], AbstractContextManager[psycopg.Connection[dict[str, Any]]]
]


class AutomaticSuggestionRunnerError(ValueError):
    """Raised when a claimed automatic suggestion job is not executable."""


class ReportPipelineProvider(Protocol):
    def generate(
        self,
        *,
        summary: dict[str, object],
        research: dict[str, object],
        anchors: Sequence[ReportAnchor],
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class AutomaticSuggestionProposal:
    comparison_key: str
    kind: SuggestionKind
    source_anchor_id: UUID
    suggested_text: str
    rationale: str
    target_block_id: str | None = None


@dataclass(frozen=True, slots=True)
class AutomaticSuggestionExecution:
    snapshot_id: UUID
    session_id: UUID
    room_id: UUID
    author_id: UUID
    report_content_hash: str
    proposals: tuple[AutomaticSuggestionProposal, ...]
    final_blocks: tuple[dict[str, object], ...] = ()

    def fenced_completion(
        self,
    ) -> tuple[dict[str, object], Callable[[psycopg.Cursor[Any]], None]]:
        result: dict[str, object] = {
            "snapshot_id": str(self.snapshot_id),
            "status": JobState.SUCCEEDED.value,
            "suggestion_count": 0,
        }
        def effect(cursor: psycopg.Cursor[Any]) -> None:
            if self.final_blocks:
                cursor.execute(
                    """
                    INSERT INTO merged_document_states (
                        id, session_id, snapshot_id, version, blocks_json, updated_by
                    ) VALUES (%s, %s, %s, 1, %s, %s)
                    ON CONFLICT (session_id, snapshot_id) DO NOTHING
                    """,
                    (
                        uuid4(),
                        self.session_id,
                        self.snapshot_id,
                        Jsonb(list(self.final_blocks)),
                        self.author_id,
                    ),
                )
            inserted_count = 0
            for proposal in self.proposals:
                suggestion_id = uuid5(
                    NAMESPACE_URL,
                    f"axit:{self.snapshot_id}:automatic-comparison:{proposal.comparison_key}",
                )
                cursor.execute(
                    """
                    INSERT INTO report_suggestions (
                        id, session_id, author_id, source_anchor_id, target_block_id,
                        suggested_text, rationale, snapshot_id, report_content_hash,
                        kind, origin, comparison_key
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, 'automatic_comparison', %s
                    )
                    ON CONFLICT (snapshot_id, comparison_key)
                      WHERE comparison_key IS NOT NULL DO NOTHING
                    RETURNING id
                    """,
                    (
                        suggestion_id,
                        self.session_id,
                        self.author_id,
                        proposal.source_anchor_id,
                        proposal.target_block_id,
                        proposal.suggested_text,
                        proposal.rationale,
                        self.snapshot_id,
                        self.report_content_hash,
                        proposal.kind,
                        proposal.comparison_key,
                    ),
                )
                inserted = cursor.fetchone()
                if inserted is not None:
                    inserted_count += 1
                    suggestion_id = inserted["id"]
                    ActivityService().append(
                        cursor,
                        event_key=build_event_key(
                            "suggestion.created", suggestion_id=suggestion_id
                        ),
                        event_type="suggestion.created",
                        actor_id=None,
                        scope_type="session",
                        room_id=self.room_id,
                        session_id=self.session_id,
                        entity_type="suggestion",
                        entity_id=suggestion_id,
                        metadata={
                            "origin": "automatic_comparison",
                            "kind": proposal.kind,
                        },
                    )
            result["suggestion_count"] = inserted_count

        return result, effect


@dataclass(frozen=True, slots=True)
class AutomaticSuggestionWorkerOutcome:
    job_id: UUID | None
    claimed: bool
    completed: bool
    stale_completion: bool
    target_state: JobState | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class _SnapshotDocument:
    revision_id: UUID
    title: str
    anchors: tuple[ComparisonAnchor, ...]


class AutomaticSuggestionRunner:
    """Generate the approved grounded final report and editor recommendations."""

    def __init__(self, provider: ReportPipelineProvider | None = None) -> None:
        # ``None`` remains an explicit deterministic test seam. Production's
        # composition root always injects the fail-closed Grok provider.
        self._provider = provider

    def execute(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        claimed: ClaimedJob,
    ) -> AutomaticSuggestionExecution:
        snapshot_id, pipeline_version = _claimed_identity(claimed)
        session_id, room_id, author_id, content_hash = _load_report_identity(
            connection,
            snapshot_id=snapshot_id,
            pipeline_version=pipeline_version,
        )
        documents = _load_snapshot_documents(connection, snapshot_id=snapshot_id)
        if self._provider is not None:
            summary, research = _load_generated_inputs(
                connection,
                snapshot_id=snapshot_id,
                pipeline_version=pipeline_version,
            )
            anchors = _select_report_anchors(
                documents,
                max_anchors=_MAX_PROVIDER_ANCHORS,
            )
            generated = self._provider.generate(
                summary=summary,
                research=research,
                anchors=anchors,
            )
            proposals = tuple(
                AutomaticSuggestionProposal(
                    comparison_key=suggestion.comparison_key,
                    kind=suggestion.kind,
                    source_anchor_id=suggestion.source_anchor_id,
                    suggested_text=suggestion.suggested_text,
                    rationale=suggestion.rationale,
                    target_block_id=suggestion.target_block_id,
                )
                for suggestion in generated.suggestions
            )
            final_blocks = tuple(block.editor_json() for block in generated.final)
            source_coverage_blocks = _build_source_coverage_blocks(documents)
            if len(final_blocks) + len(source_coverage_blocks) > _MAX_MERGED_DOCUMENT_BLOCKS:
                raise AutomaticSuggestionRunnerError(
                    "complete merged document exceeds editor block limit"
                )
            return AutomaticSuggestionExecution(
                snapshot_id=snapshot_id,
                session_id=session_id,
                room_id=room_id,
                author_id=author_id,
                report_content_hash=content_hash,
                proposals=proposals,
                final_blocks=final_blocks + source_coverage_blocks,
            )
        comparisons: list[tuple[str, str, DocumentComparison]] = []
        document_pairs = tuple(combinations(documents, 2))
        if len(document_pairs) > _MAX_DOCUMENT_PAIRS:
            raise AutomaticSuggestionRunnerError("snapshot document comparison limit exceeded")
        for left, right in document_pairs:
            try:
                comparison = compare_anchor_sets(
                    left_revision_id=left.revision_id,
                    right_revision_id=right.revision_id,
                    left=left.anchors,
                    right=right.anchors,
                )
            except ValueError as error:
                raise AutomaticSuggestionRunnerError(
                    "snapshot comparison could not be completed"
                ) from error
            comparisons.append(
                (
                    left.title,
                    right.title,
                    comparison,
                )
            )
        return AutomaticSuggestionExecution(
            snapshot_id=snapshot_id,
            session_id=session_id,
            room_id=room_id,
            author_id=author_id,
            report_content_hash=content_hash,
            proposals=build_automatic_proposals(comparisons=tuple(comparisons)),
        )


class FencedAutomaticSuggestionWorker:
    """Claim, compare, and persist suggestions through the queue lease CAS."""

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory,
        runner: AutomaticSuggestionRunner | None = None,
        queue: PostgresJobQueue | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._runner = runner or AutomaticSuggestionRunner()
        self._queue = queue or PostgresJobQueue()

    def run_once(
        self,
        *,
        owner: str,
        lease_seconds: int = 60,
    ) -> AutomaticSuggestionWorkerOutcome:
        with self._connection_factory() as connection:
            claimed = self._queue.claim_next(
                connection,
                owner=owner,
                lease_seconds=lease_seconds,
                kinds=(_JOB_KIND,),
            )
        if claimed is None:
            return AutomaticSuggestionWorkerOutcome(
                job_id=None,
                claimed=False,
                completed=False,
                stale_completion=False,
                target_state=None,
                error_code=None,
            )

        try:
            with self._connection_factory() as connection:
                execution = self._runner.execute(connection, claimed)
        except (AutomaticSuggestionRunnerError, GenerationProviderFailure) as error:
            retryable = isinstance(error, GenerationProviderFailure) and error.retryable
            if claimed.lease_generation >= _MAX_PROVIDER_ATTEMPTS:
                retryable = False
            error_code = error.code if isinstance(error, GenerationProviderFailure) else _FAILURE_CODE
            with self._connection_factory() as connection:
                self._queue.complete_with_effects(
                    connection,
                    claimed,
                    target_state=(JobState.FAILED_RETRYABLE if retryable else JobState.FAILED_TERMINAL),
                    result={"outcome": "failed", "error_code": error_code},
                    error_code=error_code,
                    effect=None if retryable else _attention_effect(claimed),
                )
            if retryable:
                try:
                    with self._connection_factory() as connection:
                        self._queue.requeue_retryable(
                            connection,
                            job_id=claimed.id,
                            expected_lease_generation=claimed.lease_generation,
                        )
                except StaleLeaseError:
                    pass
            return _outcome(
                claimed,
                completed=True,
                stale_completion=False,
                target_state=(JobState.FAILED_RETRYABLE if retryable else JobState.FAILED_TERMINAL),
                error_code=error_code,
            )
        except Exception as error:
            _LOGGER.exception(
                "unexpected automatic suggestion execution failure correlation_id=%s exception_type=%s",
                uuid4().hex,
                type(error).__name__,
            )
            raise

        try:
            with self._connection_factory() as connection:
                result, effect = execution.fenced_completion()
                self._queue.complete_with_effects(
                    connection,
                    claimed,
                    target_state=JobState.SUCCEEDED,
                    result=result,
                    effect=effect,
                )
        except StaleLeaseError:
            return _outcome(
                claimed,
                completed=False,
                stale_completion=True,
                target_state=JobState.SUCCEEDED,
                error_code=None,
            )
        return _outcome(
            claimed,
            completed=True,
            stale_completion=False,
            target_state=JobState.SUCCEEDED,
            error_code=None,
        )


def build_automatic_proposals(
    *,
    comparisons: Sequence[tuple[str, str, DocumentComparison]],
) -> tuple[AutomaticSuggestionProposal, ...]:
    """Convert deterministic comparisons into grounded, idempotent review proposals."""

    proposals: list[AutomaticSuggestionProposal] = []
    seen: set[tuple[SuggestionKind, UUID]] = set()
    matched_anchor_ids = {
        anchor_id
        for _, _, comparison in comparisons
        for match in comparison.matches
        for anchor_id in (match.left.anchor_id, match.right.anchor_id)
    }

    def append(
        *,
        kind: SuggestionKind,
        anchor: ComparisonAnchor,
        rationale: str,
        paired_anchor_id: UUID | None = None,
    ) -> None:
        dedupe_key = (kind, anchor.anchor_id)
        if dedupe_key in seen or len(proposals) >= _MAX_PROPOSALS:
            return
        seen.add(dedupe_key)
        key_material = ":".join(
            (
                kind,
                str(anchor.anchor_id),
                str(paired_anchor_id) if paired_anchor_id is not None else "none",
            )
        )
        proposals.append(
            AutomaticSuggestionProposal(
                comparison_key=hashlib.sha256(key_material.encode("ascii")).hexdigest(),
                kind=kind,
                source_anchor_id=anchor.anchor_id,
                suggested_text=anchor.text.strip()[:10_000],
                rationale=rationale[:2_000],
            )
        )

    for left_title, right_title, comparison in comparisons:
        for match in comparison.matches:
            if match.relation == "duplicate":
                append(
                    kind="remove",
                    anchor=match.right,
                    paired_anchor_id=match.left.anchor_id,
                    rationale=(
                        f"'{right_title}'의 내용이 '{left_title}'와 중복됩니다 "
                        f"(유사도 {match.similarity:.2f}). 통합 보고서의 중복 표현 제거를 검토하세요."
                    ),
                )
            else:
                append(
                    kind="edit",
                    anchor=match.right,
                    paired_anchor_id=match.left.anchor_id,
                    rationale=(
                        f"'{right_title}'와 '{left_title}'의 유사한 진술이 서로 다릅니다 "
                        f"(유사도 {match.similarity:.2f}). 표현과 사실 관계를 하나로 정리하세요."
                    ),
                )
        for anchor in comparison.left_only:
            if anchor.anchor_id in matched_anchor_ids:
                continue
            append(
                kind="add",
                anchor=anchor,
                rationale=(
                    f"'{left_title}'에만 있는 내용입니다. '{right_title}'와 비교해 "
                    "통합 보고서에서 누락되지 않았는지 검토하세요."
                ),
            )
        for anchor in comparison.right_only:
            if anchor.anchor_id in matched_anchor_ids:
                continue
            append(
                kind="add",
                anchor=anchor,
                rationale=(
                    f"'{right_title}'에만 있는 내용입니다. '{left_title}'와 비교해 "
                    "통합 보고서에서 누락되지 않았는지 검토하세요."
                ),
            )
    return tuple(proposals)


def _claimed_identity(claimed: ClaimedJob) -> tuple[UUID, str]:
    raw_snapshot_id = claimed.payload.get("snapshot_id")
    raw_kind = claimed.payload.get("kind")
    raw_pipeline = claimed.payload.get("pipeline_version")
    if (
        claimed.kind != _JOB_KIND
        or raw_kind != _JOB_KIND
        or not isinstance(raw_snapshot_id, str)
        or not isinstance(raw_pipeline, str)
        or not raw_pipeline.strip()
    ):
        raise AutomaticSuggestionRunnerError("automatic suggestion job identity is invalid")
    try:
        return UUID(raw_snapshot_id), raw_pipeline
    except ValueError as error:
        raise AutomaticSuggestionRunnerError(
            "automatic suggestion snapshot id is invalid"
        ) from error


def _load_report_identity(
    connection: psycopg.Connection[dict[str, Any]],
    *,
    snapshot_id: UUID,
    pipeline_version: str,
) -> tuple[UUID, UUID, UUID, str]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT snapshot.session_id, session_row.room_id, snapshot.created_by,
                   max(document.content_hash) FILTER (WHERE document.kind='summary') AS summary_hash,
                   max(document.content_hash) FILTER (WHERE document.kind='research') AS research_hash
            FROM generation_snapshots snapshot
            JOIN talk_sessions session_row ON session_row.id=snapshot.session_id
            JOIN generation_runs run
              ON run.snapshot_id=snapshot.id
             AND run.pipeline_version=snapshot.pipeline_version
             AND run.state='succeeded'
            JOIN generated_documents document ON document.run_id=run.id
            WHERE snapshot.id=%s AND snapshot.pipeline_version=%s
            GROUP BY snapshot.id, snapshot.session_id, session_row.room_id,
                     snapshot.created_by
            HAVING count(*)=2 AND count(DISTINCT document.kind)=2
            """,
            (snapshot_id, pipeline_version),
        )
        row = cursor.fetchone()
    if row is None:
        raise AutomaticSuggestionRunnerError("generated report is unavailable")
    return (
        row["session_id"],
        row["room_id"],
        row["created_by"],
        report_content_hash(str(row["summary_hash"]), str(row["research_hash"])),
    )


def _load_snapshot_documents(
    connection: psycopg.Connection[dict[str, Any]],
    *,
    snapshot_id: UUID,
) -> tuple[_SnapshotDocument, ...]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT revision.id AS revision_id,
                   COALESCE(NULLIF(submission.title, ''), revision.filename, '문서') AS title,
                   anchor.id AS anchor_id, anchor.text,
                   anchor.block_type, anchor.confidence
            FROM snapshot_revisions snapshot_revision
            JOIN source_revisions revision
              ON revision.id=snapshot_revision.source_revision_id
            JOIN submissions submission ON submission.id=revision.submission_id
            JOIN source_anchors anchor
              ON anchor.source_revision_id=snapshot_revision.source_revision_id
             AND anchor.extraction_run_id=snapshot_revision.extraction_run_id
            WHERE snapshot_revision.snapshot_id=%s
              AND anchor.rag_eligible
            ORDER BY revision.id, anchor.ordinal, anchor.id
            """,
            (snapshot_id,),
        )
        rows = cursor.fetchall()

    grouped: dict[UUID, tuple[str, list[ComparisonAnchor]]] = {}
    for row in rows:
        confidence = None if row["confidence"] is None else float(row["confidence"])
        revision_id = row["revision_id"]
        title, anchors = grouped.setdefault(revision_id, (str(row["title"]), []))
        anchors.append(
            ComparisonAnchor(
                row["anchor_id"],
                revision_id,
                str(row["text"]),
                str(row["block_type"]),
                confidence,
            )
        )
        grouped[revision_id] = (title, anchors)
    return tuple(
        _SnapshotDocument(revision_id, title, tuple(anchors))
        for revision_id, (title, anchors) in sorted(grouped.items(), key=lambda item: str(item[0]))
    )


def _select_report_anchors(
    documents: Sequence[_SnapshotDocument],
    *,
    max_anchors: int,
    max_per_document: int | None = None,
) -> tuple[ReportAnchor, ...]:
    """Select anchors, with exhaustive fail-closed mode as the default."""

    if max_anchors < 1 or (max_per_document is not None and max_per_document < 1):
        raise ValueError("report anchor limits must be positive")
    nonempty = tuple(document for document in documents if document.anchors)
    per_document_limit = max_per_document or max(
        (len(document.anchors) for document in nonempty),
        default=0,
    )
    selected: list[ReportAnchor] = []
    for anchor_ordinal in range(per_document_limit):
        for document in nonempty:
            if anchor_ordinal >= len(document.anchors):
                continue
            anchor = document.anchors[anchor_ordinal]
            selected.append(ReportAnchor(anchor.anchor_id, anchor.text))
            if len(selected) >= max_anchors:
                return tuple(selected)
    return tuple(selected)


def _build_source_coverage_blocks(
    documents: Sequence[_SnapshotDocument],
) -> tuple[dict[str, object], ...]:
    """Append every normalized source anchor verbatim to the merged document.

    The generated report remains the decision-oriented first section. This
    deterministic source section prevents model summarization or retrieval
    limits from silently dropping uploaded-document content.
    """

    blocks: list[dict[str, object]] = [
        {
            "id": "source-coverage-heading",
            "type": "heading",
            "level": 1,
            "text": "업로드 문서 전체 내용",
            "tag": "원문 전체",
        }
    ]
    for document_index, document in enumerate(documents):
        title = document.title.strip() or "제목 없는 문서"
        chunk_texts: list[str] = []
        chunk_anchor_ids: list[UUID] = []
        chunk_index = 0

        def flush_chunk() -> None:
            nonlocal chunk_index
            if not chunk_texts:
                return
            blocks.append(
                {
                    "id": f"source-{document_index}-{chunk_index}",
                    "type": "paragraph",
                    "text": "\n\n".join(chunk_texts),
                    "tag": (
                        f"{title} · "
                        + " ".join(f"RAG:{anchor_id}" for anchor_id in chunk_anchor_ids)
                    ),
                }
            )
            chunk_texts.clear()
            chunk_anchor_ids.clear()
            chunk_index += 1

        for anchor in document.anchors:
            next_length = sum(len(text) for text in chunk_texts) + len(anchor.text)
            if chunk_texts:
                next_length += 2 * len(chunk_texts)
            if (
                len(chunk_texts) >= _MAX_COVERAGE_ANCHORS_PER_BLOCK
                or next_length > _MAX_MERGED_PARAGRAPH_LENGTH
            ):
                flush_chunk()
            chunk_texts.append(anchor.text)
            chunk_anchor_ids.append(anchor.anchor_id)
        flush_chunk()
    return tuple(blocks)


def _load_generated_inputs(
    connection: psycopg.Connection[dict[str, Any]],
    *,
    snapshot_id: UUID,
    pipeline_version: str,
) -> tuple[dict[str, object], dict[str, object]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT document.kind, document.structured_content_json
            FROM generation_runs run
            JOIN generated_documents document ON document.run_id=run.id
            WHERE run.snapshot_id=%s
              AND run.pipeline_version=%s
              AND run.state='succeeded'
              AND document.kind IN ('summary', 'research')
            """,
            (snapshot_id, pipeline_version),
        )
        rows = cursor.fetchall()
    values = {
        str(row["kind"]): row["structured_content_json"]
        for row in rows
        if isinstance(row["structured_content_json"], dict)
    }
    if set(values) != {"summary", "research"}:
        raise AutomaticSuggestionRunnerError("generated report inputs are unavailable")
    return values["summary"], values["research"]


def _outcome(
    claimed: ClaimedJob,
    *,
    completed: bool,
    stale_completion: bool,
    target_state: JobState,
    error_code: str | None,
) -> AutomaticSuggestionWorkerOutcome:
    return AutomaticSuggestionWorkerOutcome(
        job_id=claimed.id,
        claimed=True,
        completed=completed,
        stale_completion=stale_completion,
        target_state=target_state,
        error_code=error_code,
    )


def _attention_effect(claimed: ClaimedJob) -> Callable[[psycopg.Cursor[Any]], None]:
    """Expose an exhausted final-report failure to the analysis progress UI."""

    snapshot_id, _ = _claimed_identity(claimed)

    def effect(cursor: psycopg.Cursor[Any]) -> None:
        cursor.execute(
            """
            UPDATE talk_sessions
            SET state='needs_attention', state_version=state_version+1
            WHERE id=(SELECT session_id FROM generation_snapshots WHERE id=%s)
              AND state='ready'
            """,
            (snapshot_id,),
        )

    return effect
