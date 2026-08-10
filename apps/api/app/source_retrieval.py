"""Membership-scoped PostgreSQL FTS retrieval over immutable source anchors."""

from __future__ import annotations

from dataclasses import dataclass
import re
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


class SourceRetrievalAccessError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class SourceSearchHit:
    anchor_id: UUID
    revision_id: UUID
    submission_id: UUID
    title: str
    filename: str
    mime_type: str
    author_id: UUID
    text: str
    rank: float


class SourceRetrievalService:
    def search(
        self,
        connection: psycopg.Connection[dict[str, object]],
        *,
        session_id: UUID,
        actor_id: UUID,
        query: str,
        limit: int = 8,
        author_id: UUID | None = None,
        mime_type: str | None = None,
    ) -> tuple[SourceSearchHit, ...]:
        normalized = query.strip()
        if not normalized or len(normalized) > 500:
            raise ValueError("search query must contain 1 to 500 characters")
        if isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ValueError("search limit must be between 1 and 20")
        tsquery = _prefix_tsquery(normalized)
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM talk_sessions session_row
                JOIN room_memberships membership
                  ON membership.room_id = session_row.room_id
                 AND membership.user_id = %s AND membership.left_at IS NULL
                WHERE session_row.id = %s
                """,
                (actor_id, session_id),
            )
            if cursor.fetchone() is None:
                raise SourceRetrievalAccessError("talk session is unavailable")
            cursor.execute(
                """
                WITH search_query AS (
                    SELECT to_tsquery('simple', %s) AS query
                )
                SELECT anchor.id AS anchor_id,
                       revision.id AS revision_id,
                       submission.id AS submission_id,
                       submission.title, revision.filename, revision.mime_type,
                       submission.author_id, anchor.text,
                       ts_rank_cd(to_tsvector('simple', anchor.text), search_query.query) AS rank
                FROM search_query, submissions submission
                JOIN source_revisions revision
                  ON revision.submission_id = submission.id
                 AND revision.is_current
                 AND revision.processing_state = 'ready'
                JOIN source_anchors anchor
                  ON anchor.source_revision_id = revision.id
                 AND anchor.extraction_run_id = revision.approved_extraction_run_id
                WHERE submission.session_id = %s
                  AND anchor.rag_eligible
                  AND (%s::uuid IS NULL OR submission.author_id = %s::uuid)
                  AND (%s::text IS NULL OR revision.mime_type = %s::text)
                  AND to_tsvector('simple', anchor.text) @@ search_query.query
                ORDER BY rank DESC, revision.id, anchor.ordinal, anchor.id
                LIMIT %s
                """,
                (tsquery, session_id, author_id, author_id, mime_type, mime_type, limit),
            )
            rows = cursor.fetchall()
        return tuple(
            SourceSearchHit(
                anchor_id=row["anchor_id"], revision_id=row["revision_id"],
                submission_id=row["submission_id"], title=str(row["title"]),
                filename=str(row["filename"]), mime_type=str(row["mime_type"]),
                author_id=row["author_id"], text=str(row["text"]), rank=float(row["rank"]),
            )
            for row in rows
        )


def _prefix_tsquery(query: str) -> str:
    """Build an operator-free prefix query suitable for Korean suffixes."""

    tokens = re.findall(r"[^\W_]+", query, flags=re.UNICODE)[:20]
    if not tokens:
        raise ValueError("search query must contain searchable characters")
    return " & ".join(f"{token}:*" for token in tokens)
