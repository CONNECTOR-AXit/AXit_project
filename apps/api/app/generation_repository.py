"""Fenced-transaction persistence for normalized generation artifacts.

``GenerationRepository`` deliberately accepts a cursor owned by the queue's
``complete_with_effects`` callback.  It never opens its own transaction: a
stale queue lease must roll back the canonical generation row, document,
segments, citations, and aggregate projection together.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.activity_policy import build_event_key
from app.activity_service import ActivityService, NotificationEffect
from app.domain import (
    GenerationKind,
    GenerationRunState,
    GenerationRunView,
    TalkSessionState,
    project_generation_aggregate,
)


_GENERATION_KINDS: Final[frozenset[str]] = frozenset({"summary", "research"})
_ERROR_CODE: Final = re.compile(r"^[a-z0-9][a-z0-9_]{0,127}$")
_SUMMARY_FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "alias",
        "fixture_alias",
        "fixture_id",
        "web_evidence",
        "web_evidence_ids",
        "url",
        "verdict",
    }
)
_FIXTURE_FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {"alias", "fixture_alias", "fixture_id", "source_anchor_alias"}
)


class GenerationRepositoryError(RuntimeError):
    """A repository caller attempted an impossible canonical write."""


class GenerationDocumentUnavailableError(PermissionError):
    """Hide absent/unfinished/non-member generated documents uniformly."""


@dataclass(frozen=True, slots=True)
class GeneratedSegmentWrite:
    """One rendered summary/research segment with a server UUID assigned early."""

    id: UUID
    ordinal: int
    text: str

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("generated segment ordinal must not be negative")
        if not self.text.strip():
            raise ValueError("generated segment text must not be blank")


@dataclass(frozen=True, slots=True)
class CitationWrite:
    """A generated segment's source anchor citation.

    Phase 3 intentionally permits only source-anchor citations here.  Phase 5
    may add separately validated web-evidence persistence without weakening
    the summary boundary.
    """

    id: UUID
    segment_id: UUID
    source_anchor_id: UUID


@dataclass(frozen=True, slots=True)
class WebEvidenceWrite:
    id: UUID
    url: str
    title: str
    domain: str
    accessed_at: datetime
    snippet_hash: str

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.url, self.title, self.domain)):
            raise ValueError("web evidence fields must not be blank")
        if not re.fullmatch(r"[0-9a-f]{64}", self.snippet_hash):
            raise ValueError("web evidence snippet hash must be lowercase sha256")
        if self.accessed_at.tzinfo is None:
            raise ValueError("web evidence accessed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class WebCitationWrite:
    id: UUID
    segment_id: UUID
    web_evidence_id: UUID


@dataclass(frozen=True, slots=True)
class ResearchClaimWrite:
    id: UUID
    claim_text: str
    source_anchor_id: UUID
    verdict: Literal["supported", "refuted", "mixed", "unverifiable"]
    explanation: str

    def __post_init__(self) -> None:
        if not self.claim_text.strip() or not self.explanation.strip():
            raise ValueError("research claim text and explanation must not be blank")


@dataclass(frozen=True, slots=True)
class GenerationCompletion:
    """Fully normalized provider result ready for a fenced persistence effect."""

    snapshot_id: UUID
    kind: Literal["summary", "research"]
    pipeline_version: str
    document_id: UUID
    structured_content: Mapping[str, object]
    segments: tuple[GeneratedSegmentWrite, ...]
    citations: tuple[CitationWrite | WebCitationWrite, ...]
    web_evidence: tuple[WebEvidenceWrite, ...] = ()
    research_claims: tuple[ResearchClaimWrite, ...] = ()
    provider: str = "mock"
    model: str = "fixture-v1"
    prompt_version: str = "mock-provider.prompt.v1"

    def __post_init__(self) -> None:
        if self.kind not in _GENERATION_KINDS:
            raise ValueError("generation completion kind must be summary or research")
        for name, value in (
            ("pipeline_version", self.pipeline_version),
            ("provider", self.provider),
            ("model", self.model),
            ("prompt_version", self.prompt_version),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        _canonical_json_bytes(dict(self.structured_content))
        segment_ids = {segment.id for segment in self.segments}
        if len(segment_ids) != len(self.segments):
            raise ValueError("generated segment IDs must be unique")
        if {segment.ordinal for segment in self.segments} != set(
            range(len(self.segments))
        ):
            raise ValueError("generated segment ordinals must be contiguous from zero")
        citation_ids = {citation.id for citation in self.citations}
        if len(citation_ids) != len(self.citations):
            raise ValueError("citation IDs must be unique")
        if not all(citation.segment_id in segment_ids for citation in self.citations):
            raise ValueError("citation must target a generated segment")
        evidence_ids = {evidence.id for evidence in self.web_evidence}
        if len(evidence_ids) != len(self.web_evidence):
            raise ValueError("web evidence IDs must be unique")
        web_citations = tuple(
            citation
            for citation in self.citations
            if isinstance(citation, WebCitationWrite)
        )
        if not all(
            citation.web_evidence_id in evidence_ids for citation in web_citations
        ):
            raise ValueError("web citation must target completion web evidence")
        claim_ids = {claim.id for claim in self.research_claims}
        if len(claim_ids) != len(self.research_claims):
            raise ValueError("research claim IDs must be unique")
        if self.kind == "summary":
            if not self.segments or not self.citations:
                raise ValueError(
                    "summary completion requires segments and source citations"
                )
            if self.web_evidence or self.research_claims or web_citations:
                raise ValueError(
                    "summary completion cannot contain research persistence"
                )
            source_citations = tuple(
                citation
                for citation in self.citations
                if isinstance(citation, CitationWrite)
            )
            cited_segment_ids = {citation.segment_id for citation in self.citations}
            if cited_segment_ids != segment_ids:
                raise ValueError("every summary segment requires a source citation")
            citation_pairs = {
                (citation.segment_id, citation.source_anchor_id)
                for citation in source_citations
            }
            if len(citation_pairs) != len(self.citations):
                raise ValueError(
                    "summary citations must not duplicate a segment/anchor pair"
                )
            _assert_summary_content_is_isolated(self.structured_content)
        else:
            if any(
                not isinstance(citation, (CitationWrite, WebCitationWrite))
                for citation in self.citations
            ):
                raise ValueError("unsupported research citation")
            if self.research_claims and not self.web_evidence:
                raise ValueError("research claims require web evidence")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(
            _canonical_json_bytes(dict(self.structured_content))
        ).hexdigest()

    def job_result(self) -> dict[str, object]:
        """Return alias-free result metadata appropriate for ``job_results``."""

        return {
            "snapshot_id": str(self.snapshot_id),
            "kind": self.kind,
            "document_id": str(self.document_id),
            "content_hash": self.content_hash,
            "status": "succeeded",
        }


@dataclass(frozen=True, slots=True)
class GenerationAggregateProjection:
    """The post-write session state, useful to an orchestrator and tests."""

    session_id: UUID
    state: TalkSessionState
    reason_codes: tuple[str, ...]
    transitioned_to_ready: bool


@dataclass(frozen=True, slots=True)
class MemberGenerationDocument:
    """A membership-gated persisted document without provider fixture metadata."""

    session_id: UUID
    snapshot_id: UUID
    document_id: UUID
    kind: Literal["summary", "research"]
    structured_content: dict[str, object]


class GenerationRepository:
    """Persist one fenced generation result and recompute the session aggregate."""

    def __init__(self, activity_service: ActivityService | None = None) -> None:
        self._activities = activity_service or ActivityService()

    def persist_success(
        self,
        cursor: psycopg.Cursor[Any],
        completion: GenerationCompletion,
    ) -> GenerationAggregateProjection:
        """Write an artifact after queue CAS succeeds, then project state.

        The caller must invoke this only inside
        ``PostgresJobQueue.complete_with_effects(..., effect=...)``.  This
        method contains no transaction boundary intentionally.
        """

        generation_run_id = self._mark_run_succeeded(cursor, completion)
        cursor.execute(
            """
            INSERT INTO generated_documents (
                id, run_id, kind, structured_content_json, content_hash
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (
                completion.document_id,
                generation_run_id,
                completion.kind,
                Jsonb(dict(completion.structured_content)),
                completion.content_hash,
            ),
        )
        for segment in completion.segments:
            cursor.execute(
                """
                INSERT INTO generated_segments (id, document_id, ordinal, text)
                VALUES (%s, %s, %s, %s)
                """,
                (segment.id, completion.document_id, segment.ordinal, segment.text),
            )
        for evidence in completion.web_evidence:
            cursor.execute(
                """
                INSERT INTO web_evidence (id, url, title, domain, accessed_at, snippet_hash)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    evidence.id,
                    evidence.url,
                    evidence.title,
                    evidence.domain,
                    evidence.accessed_at,
                    evidence.snippet_hash,
                ),
            )
        for citation in completion.citations:
            if isinstance(citation, CitationWrite):
                cursor.execute(
                    """
                    INSERT INTO citations (id, segment_id, target_type, source_anchor_id)
                    VALUES (%s, %s, 'source_anchor', %s)
                    """,
                    (citation.id, citation.segment_id, citation.source_anchor_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO citations (id, segment_id, target_type, web_evidence_id)
                    VALUES (%s, %s, 'web_evidence', %s)
                    """,
                    (citation.id, citation.segment_id, citation.web_evidence_id),
                )
        for claim in completion.research_claims:
            cursor.execute(
                """
                INSERT INTO research_claims (
                    id, run_id, claim_text, source_anchor_id, verdict, explanation
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    claim.id,
                    generation_run_id,
                    claim.claim_text,
                    claim.source_anchor_id,
                    claim.verdict,
                    claim.explanation,
                ),
            )
        return self.recompute_aggregate(cursor, snapshot_id=completion.snapshot_id)

    def get_summary_for_member(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
    ) -> dict[str, object]:
        """Return a contract-ready summary only after membership-gated lookup.

        Persisted summary content intentionally omits citation UUIDs from its
        canonical hash.  This adapter joins the immutable segments/citations
        and adds the server-issued citation IDs at read time.
        """

        document = self._member_document(
            connection,
            session_id=session_id,
            actor_id=actor_id,
            kind="summary",
        )
        structured = _summary_content_with_citation_ids(connection, document)
        return {"snapshot_id": str(document.snapshot_id), **structured}

    def get_research_for_member(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
    ) -> dict[str, object]:
        """Return the current member-visible research artifact if it exists."""

        document = self._member_document(
            connection,
            session_id=session_id,
            actor_id=actor_id,
            kind="research",
        )
        _assert_no_fixture_aliases(document.structured_content)
        return {
            "snapshot_id": str(document.snapshot_id),
            **document.structured_content,
        }

    def get_rag_contributions_for_member(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
    ) -> list[dict[str, object]]:
        """Count snapshot-pinned information-unit anchors and their summary use."""

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                WITH current_snapshot AS (
                    SELECT snapshot.id
                    FROM generation_snapshots snapshot
                    JOIN talk_sessions session_row
                      ON session_row.id = snapshot.session_id
                     AND session_row.generation_epoch = snapshot.generation_epoch
                    JOIN room_memberships membership
                      ON membership.room_id = session_row.room_id
                     AND membership.user_id = %s
                     AND membership.left_at IS NULL
                    WHERE session_row.id = %s
                ), used AS (
                    SELECT anchor.source_revision_id,
                           array_agg(DISTINCT anchor.id ORDER BY anchor.id) AS anchor_ids
                    FROM current_snapshot snapshot
                    JOIN generation_runs run
                      ON run.snapshot_id = snapshot.id
                     AND run.kind = 'summary' AND run.state = 'succeeded'
                    JOIN generated_documents document ON document.run_id = run.id
                    JOIN generated_segments segment ON segment.document_id = document.id
                    JOIN citations citation
                      ON citation.segment_id = segment.id
                     AND citation.target_type = 'source_anchor'
                    JOIN source_anchors anchor ON anchor.id = citation.source_anchor_id
                    GROUP BY anchor.source_revision_id
                )
                SELECT submission.id AS document_id, revision.id AS revision_id,
                       submission.title,
                       count(anchor.id) AS rag_unit_count,
                       coalesce(cardinality(used.anchor_ids), 0) AS used_rag_unit_count,
                       coalesce(used.anchor_ids, ARRAY[]::uuid[]) AS used_anchor_ids
                FROM current_snapshot snapshot
                JOIN snapshot_revisions pinned ON pinned.snapshot_id = snapshot.id
                JOIN source_revisions revision ON revision.id = pinned.source_revision_id
                JOIN submissions submission ON submission.id = revision.submission_id
                JOIN source_anchors anchor
                  ON anchor.source_revision_id = revision.id
                 AND anchor.extraction_run_id = pinned.extraction_run_id
                 AND anchor.rag_eligible
                LEFT JOIN used ON used.source_revision_id = revision.id
                GROUP BY submission.id, revision.id, submission.title,
                         submission.created_at, used.anchor_ids
                ORDER BY submission.created_at, submission.id
                """,
                (actor_id, session_id),
            )
            rows = cursor.fetchall()
        return [
            {
                "document_id": str(row["document_id"]),
                "revision_id": str(row["revision_id"]),
                "title": str(row["title"]),
                "rag_unit_count": int(row["rag_unit_count"]),
                "used_rag_unit_count": int(row["used_rag_unit_count"]),
                "used_anchor_ids": [str(value) for value in row["used_anchor_ids"]],
            }
            for row in rows
        ]

    def get_source_quality_for_member(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
    ) -> dict[str, object]:
        """Summarize locally excluded anchors without exposing their text."""

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT anchor.rag_eligible, anchor.rag_exclusion_reason
                FROM talk_sessions session_row
                JOIN room_memberships membership
                  ON membership.room_id = session_row.room_id
                 AND membership.user_id = %s
                 AND membership.left_at IS NULL
                JOIN generation_snapshots snapshot
                  ON snapshot.session_id = session_row.id
                 AND snapshot.generation_epoch = session_row.generation_epoch
                JOIN snapshot_revisions pinned ON pinned.snapshot_id = snapshot.id
                JOIN source_anchors anchor
                  ON anchor.source_revision_id = pinned.source_revision_id
                 AND anchor.extraction_run_id = pinned.extraction_run_id
                WHERE session_row.id = %s
                ORDER BY anchor.source_revision_id, anchor.ordinal, anchor.id
                """,
                (actor_id, session_id),
            )
            rows = cursor.fetchall()
        reason_counts: dict[str, int] = {}
        accepted_count = sum(1 for row in rows if row["rag_eligible"] is True)
        for row in rows:
            if row["rag_eligible"] is True:
                continue
            reason = str(row["rag_exclusion_reason"] or "unknown")
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        excluded_count = len(rows) - accepted_count
        return {
            "status": "filtered" if excluded_count else "clean",
            "total_anchor_count": len(rows),
            "accepted_anchor_count": accepted_count,
            "excluded_anchor_count": excluded_count,
            "reason_counts": dict(sorted(reason_counts.items())),
        }

    def _member_document(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
        kind: Literal["summary", "research"],
    ) -> MemberGenerationDocument:
        """Resolve a completed document through session membership in one query."""

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT session_row.id AS session_id,
                       snapshot.id AS snapshot_id,
                       document.id AS document_id,
                       document.kind,
                       document.structured_content_json
                FROM talk_sessions AS session_row
                JOIN room_memberships AS membership
                  ON membership.room_id = session_row.room_id
                 AND membership.user_id = %s
                 AND membership.left_at IS NULL
                JOIN generation_snapshots AS snapshot
                  ON snapshot.session_id = session_row.id
                 AND snapshot.generation_epoch = session_row.generation_epoch
                JOIN generation_runs AS run
                  ON run.snapshot_id = snapshot.id
                 AND run.kind = %s
                 AND run.state = 'succeeded'
                JOIN generated_documents AS document
                  ON document.run_id = run.id
                WHERE session_row.id = %s
                ORDER BY snapshot.generation_epoch DESC
                LIMIT 1
                """,
                (actor_id, kind, session_id),
            )
            row = cursor.fetchone()
        if row is None:
            raise GenerationDocumentUnavailableError(
                "generated document is unavailable"
            )
        content = row["structured_content_json"]
        if not isinstance(content, dict):
            raise GenerationRepositoryError(
                "persisted document content must be an object"
            )
        return MemberGenerationDocument(
            session_id=_uuid_column(row, "session id"),
            snapshot_id=_uuid_column(row, "snapshot id", index=1),
            document_id=_uuid_column(row, "document id", index=2),
            kind=_literal_kind(_string_column(row, "document kind", index=3)),
            structured_content=_json_object_copy(content),
        )

    def persist_failure(
        self,
        cursor: psycopg.Cursor[Any],
        *,
        snapshot_id: UUID,
        kind: Literal["summary", "research"],
        pipeline_version: str,
        error_code: str,
        retryable: bool,
    ) -> GenerationAggregateProjection:
        """Record a typed failed canonical run after the queue's fenced CAS."""

        if kind not in _GENERATION_KINDS:
            raise GenerationRepositoryError("unsupported generation kind")
        if not pipeline_version.strip():
            raise GenerationRepositoryError("pipeline_version must not be blank")
        if not _ERROR_CODE.fullmatch(error_code):
            raise GenerationRepositoryError(
                "error_code must be a typed lowercase token"
            )
        state = "failed_retryable" if retryable else "failed_terminal"
        cursor.execute(
            """
            UPDATE generation_runs
            SET state = %s,
                error_code = %s,
                completed_at = CURRENT_TIMESTAMP
            WHERE snapshot_id = %s
              AND kind = %s
              AND pipeline_version = %s
              AND state IN ('queued', 'running', 'failed_retryable')
            """,
            (state, error_code, snapshot_id, kind, pipeline_version),
        )
        if cursor.rowcount != 1:
            raise GenerationRepositoryError("canonical generation run is not writable")
        return self.recompute_aggregate(cursor, snapshot_id=snapshot_id)

    def mark_running(
        self,
        cursor: psycopg.Cursor[Any],
        *,
        snapshot_id: UUID,
        kind: Literal["summary", "research"],
        pipeline_version: str,
    ) -> None:
        """Optionally reflect a current worker claim without changing the queue.

        This is a separate short transaction only for visible run telemetry;
        it must never be mistaken for fencing.  Queue claim/CAS remains the
        authority for write ownership.
        """

        cursor.execute(
            """
            UPDATE generation_runs
            SET state = 'running', error_code = NULL, completed_at = NULL
            WHERE snapshot_id = %s
              AND kind = %s
              AND pipeline_version = %s
              AND state = 'queued'
            """,
            (snapshot_id, kind, pipeline_version),
        )
        if cursor.rowcount not in {0, 1}:
            raise GenerationRepositoryError("generation run mark-running was ambiguous")

    def recompute_aggregate(
        self,
        cursor: psycopg.Cursor[Any],
        *,
        snapshot_id: UUID,
    ) -> GenerationAggregateProjection:
        """Project two canonical run states into the owning session atomically."""

        cursor.execute(
            """
            SELECT snapshot.session_id, session_row.state, snapshot.pipeline_version,
                   session_row.room_id, session_row.generation_epoch,
                   session_row.state_version
            FROM generation_snapshots AS snapshot
            JOIN talk_sessions AS session_row ON session_row.id = snapshot.session_id
            WHERE snapshot.id = %s
            FOR UPDATE OF session_row
            """,
            (snapshot_id,),
        )
        snapshot_row = cursor.fetchone()
        if snapshot_row is None:
            raise GenerationRepositoryError("generation snapshot does not exist")
        session_id = _uuid_column(snapshot_row, "session id")
        current_state = TalkSessionState(
            _string_column(snapshot_row, "session state", index=1)
        )
        pipeline_version = _string_column(snapshot_row, "pipeline version", index=2)
        room_id = _uuid_column(snapshot_row, "room id", index=3)
        generation_epoch = int(snapshot_row["generation_epoch"])
        state_version = int(snapshot_row["state_version"])

        cursor.execute(
            """
            SELECT kind, state, error_code
            FROM generation_runs
            WHERE snapshot_id = %s
            ORDER BY kind
            """,
            (snapshot_id,),
        )
        run_rows = cursor.fetchall()
        runs = tuple(
            GenerationRunView(
                kind=GenerationKind(_string_column(row, "generation kind")),
                state=GenerationRunState(
                    _string_column(row, "generation state", index=1)
                ),
                error_code=_nullable_string_column(row, "generation error", index=2),
            )
            for row in run_rows
        )
        projection = project_generation_aggregate(runs)
        transitioned_to_ready = False
        if current_state is not projection.state:
            next_state_version = state_version + 1
            cursor.execute(
                "UPDATE talk_sessions SET state = %s, state_version = %s WHERE id = %s",
                (projection.state.value, next_state_version, session_id),
            )
            if cursor.rowcount != 1:
                raise GenerationRepositoryError(
                    "talk session aggregate update was lost"
                )
            event_type = f"session.{projection.state.value}"
            event_key = build_event_key(
                event_type,
                session_id=session_id,
                state_version=next_state_version,
            )
            transitioned_to_ready = projection.state is TalkSessionState.READY
            notification_effects: tuple[NotificationEffect, ...] = ()
            if transitioned_to_ready:
                cursor.execute(
                    """SELECT user_id FROM room_memberships
                       WHERE room_id=%s AND left_at IS NULL ORDER BY user_id""",
                    (room_id,),
                )
                recipient_ids = tuple(row["user_id"] for row in cursor.fetchall())
                notification_effects = (
                    NotificationEffect(
                        recipient_ids=recipient_ids,
                        kind="analysis_completed",
                        resource_type="session",
                        resource_id=session_id,
                        action_kind="open_session",
                        title="분석이 완료되었습니다",
                        body="회의 요약과 리서치 결과를 확인할 수 있습니다.",
                        template_key="analysis_completed",
                        template_data={
                            "session_id": str(session_id),
                            "generation_epoch": generation_epoch,
                        },
                        dedupe_key=f"analysis:{session_id}:{generation_epoch}",
                    ),
                )
            self._activities.record(
                cursor,
                event_key=event_key,
                event_type=event_type,
                actor_id=None,
                scope_type="session",
                room_id=room_id,
                session_id=session_id,
                entity_type="session",
                entity_id=session_id,
                metadata={
                    "previous_state": current_state.value,
                    "state": projection.state.value,
                    "generation_epoch": generation_epoch,
                    "reason_codes": [reason.code for reason in projection.reasons],
                },
                notification_effects=notification_effects,
            )
        if projection.state is TalkSessionState.READY:
            cursor.execute(
                """
                INSERT INTO jobs (
                    id, logical_key, kind, snapshot_id, payload_json, state
                ) VALUES (%s, %s, 'report_suggestions', %s, %s, 'pending')
                ON CONFLICT (logical_key) DO NOTHING
                """,
                (
                    uuid4(),
                    f"report-suggestions:{snapshot_id}:{pipeline_version}",
                    snapshot_id,
                    Jsonb(
                        {
                            "snapshot_id": str(snapshot_id),
                            "kind": "report_suggestions",
                            "pipeline_version": pipeline_version,
                        }
                    ),
                ),
            )
        return GenerationAggregateProjection(
            session_id=session_id,
            state=projection.state,
            reason_codes=tuple(reason.code for reason in projection.reasons),
            transitioned_to_ready=transitioned_to_ready,
        )

    def _mark_run_succeeded(
        self,
        cursor: psycopg.Cursor[Any],
        completion: GenerationCompletion,
    ) -> UUID:
        cursor.execute(
            """
            UPDATE generation_runs
            SET state = 'succeeded',
                provider = %s,
                model = %s,
                prompt_version = %s,
                error_code = NULL,
                completed_at = CURRENT_TIMESTAMP
            WHERE snapshot_id = %s
              AND kind = %s
              AND pipeline_version = %s
              AND state IN ('queued', 'running', 'failed_retryable')
            RETURNING id
            """,
            (
                completion.provider,
                completion.model,
                completion.prompt_version,
                completion.snapshot_id,
                completion.kind,
                completion.pipeline_version,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise GenerationRepositoryError("canonical generation run is not writable")
        return _uuid_column(row, "generation run id")


def _canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise GenerationRepositoryError(
            "generation content must be finite JSON"
        ) from error


def _assert_summary_content_is_isolated(value: Mapping[str, object]) -> None:
    def walk(node: object) -> None:
        if isinstance(node, Mapping):
            forbidden = set(node) & _SUMMARY_FORBIDDEN_KEYS
            if forbidden:
                raise ValueError(
                    "summary content contains forbidden isolation fields: "
                    + ", ".join(sorted(str(key) for key in forbidden))
                )
            for child in node.values():
                walk(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                walk(child)

    walk(value)


def _assert_no_fixture_aliases(value: Mapping[str, object]) -> None:
    def walk(node: object) -> None:
        if isinstance(node, Mapping):
            forbidden = set(node) & _FIXTURE_FORBIDDEN_KEYS
            if forbidden:
                raise GenerationRepositoryError(
                    "persisted content exposes fixture aliases"
                )
            for child in node.values():
                walk(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                walk(child)

    walk(value)


def _summary_content_with_citation_ids(
    connection: psycopg.Connection[dict[str, Any]],
    document: MemberGenerationDocument,
) -> dict[str, object]:
    _assert_summary_content_is_isolated(document.structured_content)
    _assert_no_fixture_aliases(document.structured_content)
    content = _json_object_copy(document.structured_content)
    sections = content.get("sections")
    if not isinstance(sections, list) or not sections:
        raise GenerationRepositoryError("summary document sections are invalid")
    flattened_items: list[dict[str, object]] = []
    for section in sections:
        if not isinstance(section, dict) or set(section) != {"heading", "items"}:
            raise GenerationRepositoryError("summary section is invalid")
        items = section.get("items")
        if not isinstance(items, list) or not items:
            raise GenerationRepositoryError("summary section items are invalid")
        for item in items:
            if not isinstance(item, dict):
                raise GenerationRepositoryError("summary item is invalid")
            flattened_items.append(item)

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT segment.ordinal, citation.id, citation.source_anchor_id
            FROM generated_segments AS segment
            JOIN citations AS citation ON citation.segment_id = segment.id
            WHERE segment.document_id = %s
              AND citation.target_type = 'source_anchor'
            ORDER BY segment.ordinal, citation.id
            """,
            (document.document_id,),
        )
        citation_rows = cursor.fetchall()
    citations_by_support: dict[tuple[int, str], str] = {}
    for row in citation_rows:
        ordinal = row["ordinal"]
        if isinstance(ordinal, bool) or not isinstance(ordinal, int):
            raise GenerationRepositoryError("citation segment ordinal is invalid")
        source_anchor_id = str(_uuid_column(row, "citation source anchor", index=2))
        key = (ordinal, source_anchor_id)
        if key in citations_by_support:
            raise GenerationRepositoryError("summary has duplicate support citations")
        citations_by_support[key] = str(_uuid_column(row, "citation id", index=1))

    for ordinal, item in enumerate(flattened_items):
        supports = item.get("supports")
        if not isinstance(supports, list) or not supports:
            raise GenerationRepositoryError("summary item supports are invalid")
        for support in supports:
            if not isinstance(support, dict):
                raise GenerationRepositoryError("summary support is invalid")
            support_anchor_id = support.get("source_anchor_id")
            if not isinstance(support_anchor_id, str):
                raise GenerationRepositoryError("summary support anchor is invalid")
            citation_id = citations_by_support.get((ordinal, support_anchor_id))
            if citation_id is None:
                raise GenerationRepositoryError("summary support citation is missing")
            support["citation_id"] = citation_id
    return content


def _json_object_copy(value: Mapping[str, object]) -> dict[str, object]:
    try:
        copied = json.loads(json.dumps(value, allow_nan=False, ensure_ascii=False))
    except (TypeError, ValueError) as error:
        raise GenerationRepositoryError("persisted content is not JSON-safe") from error
    if not isinstance(copied, dict):  # pragma: no cover - input is a Mapping.
        raise GenerationRepositoryError("persisted content must remain an object")
    return copied


def _literal_kind(value: str) -> Literal["summary", "research"]:
    if value not in _GENERATION_KINDS:
        raise GenerationRepositoryError("persisted document kind is invalid")
    return value  # type: ignore[return-value]


def _uuid_column(row: object, label: str, *, index: int = 0) -> UUID:
    value = _column(row, label, index=index)
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise GenerationRepositoryError(f"{label} must be UUID")


def _string_column(row: object, label: str, *, index: int = 0) -> str:
    value = _column(row, label, index=index)
    if not isinstance(value, str) or not value.strip():
        raise GenerationRepositoryError(f"{label} must be non-empty text")
    return value


def _nullable_string_column(row: object, label: str, *, index: int) -> str | None:
    value = _column(row, label, index=index)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise GenerationRepositoryError(f"{label} must be null or non-empty text")
    return value


def _column(row: object, label: str, *, index: int) -> object:
    if isinstance(row, Mapping):
        keys = tuple(row)
        if index >= len(keys):
            raise GenerationRepositoryError(f"{label} column is missing")
        return row[keys[index]]
    if isinstance(row, Sequence) and not isinstance(row, (str, bytes)):
        if index >= len(row):
            raise GenerationRepositoryError(f"{label} column is missing")
        return row[index]
    raise GenerationRepositoryError(f"{label} row has unexpected shape")
