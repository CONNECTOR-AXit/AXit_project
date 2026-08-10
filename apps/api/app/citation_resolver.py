"""Membership-first resolver for persisted source and web citations.

No caller receives a citation target before the SQL join proves current room
membership through the complete generated-document/snapshot/session ancestry.
The same unavailable error intentionally covers a missing, stale, corrupt, or
unauthorized citation so this endpoint cannot become an IDOR oracle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


class CitationUnavailableError(PermissionError):
    """The actor cannot resolve this citation without revealing why."""


class CitationResolverInvariantError(RuntimeError):
    """A persisted citation breaks the provenance shape expected by the API."""


@dataclass(frozen=True, slots=True)
class ResolvedCitation:
    """Alias-free target identity used to construct the public citation DTO."""

    citation_id: UUID
    target_type: Literal["source_anchor", "web_evidence"]
    source_anchor_id: UUID | None = None
    source_revision_id: UUID | None = None
    web_evidence_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.target_type == "source_anchor":
            if (
                self.source_anchor_id is None
                or self.source_revision_id is None
                or self.web_evidence_id is not None
            ):
                raise CitationResolverInvariantError("invalid source-anchor citation shape")
        elif self.target_type == "web_evidence":
            if (
                self.web_evidence_id is None
                or self.source_anchor_id is not None
                or self.source_revision_id is not None
            ):
                raise CitationResolverInvariantError("invalid web-evidence citation shape")
        else:  # pragma: no cover - Literal protects callers; persisted rows do not.
            raise CitationResolverInvariantError("unsupported citation target type")


@dataclass(frozen=True, slots=True)
class ResolvedSourceAnchor:
    """A viewer-safe source anchor returned only after membership proof."""

    id: UUID
    revision_id: UUID
    exact_quote: str
    anchor_json: dict[str, object]


@dataclass(frozen=True, slots=True)
class ResolvedWebEvidence:
    """A member-visible normalized web reference."""

    id: UUID
    url: str
    title: str
    domain: str
    accessed_at: datetime
    snippet_hash: str


class CitationResolver:
    """Resolve citations while preserving private-room non-disclosure."""

    def resolve(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        citation_id: UUID,
        actor_id: UUID,
    ) -> ResolvedCitation:
        """Follow citation -> segment -> document -> run -> snapshot -> session -> member.

        Source anchors additionally join through ``snapshot_revisions`` so a
        corrupted or cross-snapshot target is unavailable even if an older DB
        row somehow bypassed the Phase 2 trigger.
        """

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT citation.id,
                       citation.target_type,
                       citation.source_anchor_id,
                       source_anchor.source_revision_id,
                       citation.web_evidence_id
                FROM citations AS citation
                JOIN generated_segments AS segment
                  ON segment.id = citation.segment_id
                JOIN generated_documents AS document
                  ON document.id = segment.document_id
                JOIN generation_runs AS run
                  ON run.id = document.run_id
                JOIN generation_snapshots AS snapshot
                  ON snapshot.id = run.snapshot_id
                JOIN talk_sessions AS session_row
                  ON session_row.id = snapshot.session_id
                JOIN room_memberships AS membership
                  ON membership.room_id = session_row.room_id
                 AND membership.user_id = %s
                 AND membership.left_at IS NULL
                LEFT JOIN source_anchors AS source_anchor
                  ON source_anchor.id = citation.source_anchor_id
                LEFT JOIN snapshot_revisions AS snapshot_revision
                  ON snapshot_revision.snapshot_id = snapshot.id
                 AND snapshot_revision.source_revision_id = source_anchor.source_revision_id
                 AND snapshot_revision.extraction_run_id = source_anchor.extraction_run_id
                LEFT JOIN web_evidence AS evidence
                  ON evidence.id = citation.web_evidence_id
                WHERE citation.id = %s
                  AND (
                    citation.target_type = 'web_evidence'
                    OR snapshot_revision.snapshot_id IS NOT NULL
                  )
                  AND (
                    citation.target_type = 'source_anchor'
                    OR evidence.id IS NOT NULL
                  )
                """,
                (actor_id, citation_id),
            )
            row = cursor.fetchone()
        if row is None:
            raise CitationUnavailableError("citation is unavailable")
        target_type = row["target_type"]
        if target_type == "source_anchor":
            return ResolvedCitation(
                citation_id=_uuid(row["id"], "citation id"),
                target_type="source_anchor",
                source_anchor_id=_uuid(row["source_anchor_id"], "source anchor id"),
                source_revision_id=_uuid(
                    row["source_revision_id"], "source revision id"
                ),
            )
        if target_type == "web_evidence":
            return ResolvedCitation(
                citation_id=_uuid(row["id"], "citation id"),
                target_type="web_evidence",
                web_evidence_id=_uuid(row["web_evidence_id"], "web evidence id"),
            )
        raise CitationResolverInvariantError("persisted citation target type is invalid")

    def resolve_source_anchor_for_viewer(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        source_revision_id: UUID,
        actor_id: UUID,
        source_anchor_id: UUID | None = None,
    ) -> ResolvedSourceAnchor | None:
        """Load a member-visible source anchor without trusting client coordinates.

        ``None`` is a valid no-highlight viewer result; an unavailable
        revision remains indistinguishable from a private/missing one.
        """

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT revision.id
                FROM source_revisions AS revision
                JOIN submissions AS submission ON submission.id = revision.submission_id
                JOIN talk_sessions AS session_row ON session_row.id = submission.session_id
                JOIN room_memberships AS membership
                  ON membership.room_id = session_row.room_id
                 AND membership.user_id = %s
                 AND membership.left_at IS NULL
                WHERE revision.id = %s
                """,
                (actor_id, source_revision_id),
            )
            if cursor.fetchone() is None:
                raise CitationUnavailableError("source revision is unavailable")
            if source_anchor_id is None:
                return None
            cursor.execute(
                """
                SELECT id, source_revision_id, text, anchor_json
                FROM source_anchors
                WHERE id = %s AND source_revision_id = %s
                """,
                (source_anchor_id, source_revision_id),
            )
            row = cursor.fetchone()
        if row is None:
            raise CitationUnavailableError("source anchor is unavailable")
        anchor_json = row["anchor_json"]
        if not isinstance(anchor_json, dict):
            raise CitationResolverInvariantError("source anchor JSON is invalid")
        text = row["text"]
        if not isinstance(text, str) or not text:
            raise CitationResolverInvariantError("source anchor text is invalid")
        return ResolvedSourceAnchor(
            id=_uuid(row["id"], "source anchor id"),
            revision_id=_uuid(row["source_revision_id"], "source revision id"),
            exact_quote=text,
            anchor_json=dict(anchor_json),
        )

    def resolve_web_evidence_for_member(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        web_evidence_id: UUID,
        actor_id: UUID,
    ) -> ResolvedWebEvidence:
        """Resolve evidence only through a research document visible to the actor."""

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT DISTINCT evidence.id, evidence.url, evidence.title, evidence.domain,
                                evidence.accessed_at, evidence.snippet_hash
                FROM web_evidence AS evidence
                JOIN citations AS citation
                  ON citation.web_evidence_id = evidence.id
                 AND citation.target_type = 'web_evidence'
                JOIN generated_segments AS segment ON segment.id = citation.segment_id
                JOIN generated_documents AS document
                  ON document.id = segment.document_id AND document.kind = 'research'
                JOIN generation_runs AS run ON run.id = document.run_id
                JOIN generation_snapshots AS snapshot ON snapshot.id = run.snapshot_id
                JOIN talk_sessions AS session_row ON session_row.id = snapshot.session_id
                JOIN room_memberships AS membership
                  ON membership.room_id = session_row.room_id
                 AND membership.user_id = %s
                 AND membership.left_at IS NULL
                WHERE evidence.id = %s
                """,
                (actor_id, web_evidence_id),
            )
            row = cursor.fetchone()
        if row is None:
            raise CitationUnavailableError("web evidence is unavailable")
        accessed_at = row["accessed_at"]
        if not isinstance(accessed_at, datetime):
            raise CitationResolverInvariantError("web evidence timestamp is invalid")
        return ResolvedWebEvidence(
            id=_uuid(row["id"], "web evidence id"),
            url=_text(row["url"], "web evidence URL"),
            title=_text(row["title"], "web evidence title"),
            domain=_text(row["domain"], "web evidence domain"),
            accessed_at=accessed_at,
            snippet_hash=_text(row["snippet_hash"], "web evidence snippet hash"),
        )

    def resolve_source_anchor_for_member(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        source_anchor_id: UUID,
        actor_id: UUID,
    ) -> ResolvedSourceAnchor:
        """Resolve an anchor through its private-room membership boundary."""

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT anchor.id, anchor.source_revision_id, anchor.text, anchor.anchor_json
                FROM source_anchors AS anchor
                JOIN source_revisions AS revision ON revision.id = anchor.source_revision_id
                JOIN submissions AS submission ON submission.id = revision.submission_id
                JOIN talk_sessions AS session_row ON session_row.id = submission.session_id
                JOIN room_memberships AS membership
                  ON membership.room_id = session_row.room_id
                 AND membership.user_id = %s
                 AND membership.left_at IS NULL
                WHERE anchor.id = %s
                """,
                (actor_id, source_anchor_id),
            )
            row = cursor.fetchone()
        if row is None:
            raise CitationUnavailableError("source anchor is unavailable")
        anchor_json = row["anchor_json"]
        if not isinstance(anchor_json, dict):
            raise CitationResolverInvariantError("source anchor JSON is invalid")
        return ResolvedSourceAnchor(
            id=_uuid(row["id"], "source anchor id"),
            revision_id=_uuid(row["source_revision_id"], "source revision id"),
            exact_quote=_text(row["text"], "source anchor text"),
            anchor_json=dict(anchor_json),
        )


def _uuid(value: object, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError as error:
            raise CitationResolverInvariantError(f"{label} is invalid") from error
    raise CitationResolverInvariantError(f"{label} is invalid")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CitationResolverInvariantError(f"{label} is invalid")
    return value
