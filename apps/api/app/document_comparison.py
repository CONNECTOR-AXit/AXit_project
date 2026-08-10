"""Deterministic, citation-preserving comparison of two extracted revisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.local_embeddings import embed_text, semantic_similarity

_MAX_COMPARISON_ANCHORS = 2_000
_MAX_CANDIDATE_PAIRS = 200_000


class DocumentComparisonAccessError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class ComparisonAnchor:
    anchor_id: UUID
    revision_id: UUID
    text: str
    block_type: str = "unknown"
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class ComparisonMatch:
    left: ComparisonAnchor
    right: ComparisonAnchor
    similarity: float
    relation: Literal["duplicate", "similar"]


@dataclass(frozen=True, slots=True)
class DocumentComparison:
    left_revision_id: UUID
    right_revision_id: UUID
    matches: tuple[ComparisonMatch, ...]
    left_only: tuple[ComparisonAnchor, ...]
    right_only: tuple[ComparisonAnchor, ...]


def compare_anchor_sets(
    *,
    left_revision_id: UUID,
    right_revision_id: UUID,
    left: tuple[ComparisonAnchor, ...],
    right: tuple[ComparisonAnchor, ...],
    similarity_threshold: float = 0.72,
) -> DocumentComparison:
    """Compare two already-authorized immutable anchor sets deterministically."""

    _validate_comparison_identity(
        left_revision_id=left_revision_id,
        right_revision_id=right_revision_id,
        similarity_threshold=similarity_threshold,
    )
    if any(anchor.revision_id != left_revision_id for anchor in left):
        raise ValueError("left comparison anchors do not match their revision")
    if any(anchor.revision_id != right_revision_id for anchor in right):
        raise ValueError("right comparison anchors do not match their revision")
    if len(left) > _MAX_COMPARISON_ANCHORS or len(right) > _MAX_COMPARISON_ANCHORS:
        raise ValueError("comparison anchor limit exceeded")

    candidates: list[tuple[float, int, int]] = []
    right_buckets: dict[int, set[int]] = {}
    for right_index, right_anchor in enumerate(right):
        vector = embed_text(right_anchor.text)
        for bucket in _dominant_buckets(vector):
            right_buckets.setdefault(bucket, set()).add(right_index)
    compared_pairs = 0
    for left_index, left_anchor in enumerate(left):
        possible: set[int] = set()
        for bucket in _dominant_buckets(embed_text(left_anchor.text)):
            possible.update(right_buckets.get(bucket, ()))
        for right_index in sorted(possible):
            compared_pairs += 1
            if compared_pairs > _MAX_CANDIDATE_PAIRS:
                raise ValueError("comparison work budget exceeded")
            right_anchor = right[right_index]
            score = _semantic_similarity(left_anchor.text, right_anchor.text)
            if score >= similarity_threshold:
                candidates.append((score, left_index, right_index))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    used_left: set[int] = set()
    used_right: set[int] = set()
    matches: list[ComparisonMatch] = []
    for score, left_index, right_index in candidates:
        if left_index in used_left or right_index in used_right:
            continue
        used_left.add(left_index)
        used_right.add(right_index)
        relation: Literal["duplicate", "similar"] = (
            "duplicate" if score >= 0.92 else "similar"
        )
        matches.append(
            ComparisonMatch(left[left_index], right[right_index], round(score, 6), relation)
        )
    matches.sort(key=lambda item: (str(item.left.anchor_id), str(item.right.anchor_id)))
    return DocumentComparison(
        left_revision_id=left_revision_id,
        right_revision_id=right_revision_id,
        matches=tuple(matches),
        left_only=tuple(anchor for index, anchor in enumerate(left) if index not in used_left),
        right_only=tuple(anchor for index, anchor in enumerate(right) if index not in used_right),
    )


class DocumentComparisonService:
    def compare(
        self,
        connection: psycopg.Connection[dict[str, object]],
        *,
        session_id: UUID,
        actor_id: UUID,
        left_revision_id: UUID,
        right_revision_id: UUID,
        similarity_threshold: float = 0.72,
    ) -> DocumentComparison:
        _validate_comparison_identity(
            left_revision_id=left_revision_id,
            right_revision_id=right_revision_id,
            similarity_threshold=similarity_threshold,
        )
        anchors = self._load_anchors(
            connection,
            session_id=session_id,
            actor_id=actor_id,
            revision_ids=(left_revision_id, right_revision_id),
        )
        left = anchors.get(left_revision_id)
        right = anchors.get(right_revision_id)
        if left is None or right is None:
            raise DocumentComparisonAccessError("source revision is unavailable")
        return compare_anchor_sets(
            left_revision_id=left_revision_id,
            right_revision_id=right_revision_id,
            left=left,
            right=right,
            similarity_threshold=similarity_threshold,
        )

    @staticmethod
    def _load_anchors(
        connection: psycopg.Connection[dict[str, object]],
        *,
        session_id: UUID,
        actor_id: UUID,
        revision_ids: tuple[UUID, UUID],
    ) -> dict[UUID, tuple[ComparisonAnchor, ...]]:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT revision.id AS revision_id, anchor.id AS anchor_id, anchor.text,
                       anchor.block_type, anchor.confidence
                FROM talk_sessions session_row
                JOIN room_memberships membership
                  ON membership.room_id = session_row.room_id
                 AND membership.user_id = %s AND membership.left_at IS NULL
                JOIN submissions submission ON submission.session_id = session_row.id
                JOIN source_revisions revision
                  ON revision.submission_id = submission.id
                 AND revision.is_current AND revision.processing_state = 'ready'
                JOIN source_anchors anchor
                  ON anchor.source_revision_id = revision.id
                 AND anchor.extraction_run_id = revision.approved_extraction_run_id
                WHERE session_row.id = %s AND revision.id = ANY(%s)
                  AND anchor.rag_eligible
                ORDER BY revision.id, anchor.ordinal, anchor.id
                """,
                (actor_id, session_id, list(revision_ids)),
            )
            rows = cursor.fetchall()
        grouped: dict[UUID, list[ComparisonAnchor]] = {}
        for row in rows:
            revision_id = row["revision_id"]
            grouped.setdefault(revision_id, []).append(
                ComparisonAnchor(
                    row["anchor_id"],
                    revision_id,
                    str(row["text"]),
                    str(row["block_type"]),
                    None if row["confidence"] is None else float(row["confidence"]),
                )
            )
        return {key: tuple(value) for key, value in grouped.items()}


def _semantic_similarity(left: str, right: str) -> float:
    return semantic_similarity(left, right)


def _validate_comparison_identity(
    *,
    left_revision_id: UUID,
    right_revision_id: UUID,
    similarity_threshold: float,
) -> None:
    if left_revision_id == right_revision_id:
        raise ValueError("comparison revisions must be different")
    if not 0.5 <= similarity_threshold <= 1:
        raise ValueError("similarity threshold must be between 0.5 and 1")


def _dominant_buckets(vector: tuple[float, ...], count: int = 12) -> tuple[int, ...]:
    return tuple(
        index
        for index, value in sorted(
            enumerate(vector), key=lambda item: (-abs(item[1]), item[0])
        )[:count]
        if value
    )
