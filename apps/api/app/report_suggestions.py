"""Membership-scoped asynchronous suggestions over immutable generated reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from app.activity_policy import build_event_key
from app.activity_service import ActivityService
from app.integrated_report import load_report_identity


class ReportSuggestionAccessError(PermissionError):
    pass


class ReportSuggestionStateError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReportSuggestion:
    id: UUID
    session_id: UUID
    author_id: UUID
    source_anchor_id: UUID | None
    target_block_id: str | None
    snapshot_id: UUID
    report_content_hash: str
    kind: Literal["add", "edit", "remove"]
    origin: Literal["member", "automatic_comparison"]
    suggested_text: str
    rationale: str
    status: Literal["open", "accepted", "rejected"]
    resolved_by: UUID | None
    created_at: datetime
    resolved_at: datetime | None


class ReportSuggestionService:
    def __init__(self, activity_service: ActivityService | None = None) -> None:
        self._activities = activity_service or ActivityService()

    def create(self, connection: psycopg.Connection[dict[str, object]], *, session_id: UUID,
               actor_id: UUID, suggested_text: str, rationale: str = "",
               source_anchor_id: UUID | None = None,
               target_block_id: str | None = None,
               kind: Literal["add", "edit", "remove"] = "add") -> ReportSuggestion:
        text = suggested_text.strip()
        reason = rationale.strip()
        target = target_block_id.strip() if target_block_id else None
        if kind not in {"add", "edit", "remove"}:
            raise ValueError("suggestion kind is invalid")
        if not 1 <= len(text) <= 10_000 or len(reason) > 2_000 or (target and len(target) > 200):
            raise ValueError("suggestion content is invalid")
        suggestion_id = uuid4()
        with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
            room_id = self._require_member(cursor, session_id, actor_id)
            report = load_report_identity(connection, session_id=session_id)
            if report is None:
                raise ReportSuggestionStateError("integrated report is unavailable")
            if source_anchor_id is not None:
                cursor.execute(
                    """SELECT 1 FROM snapshot_revisions sr JOIN source_anchors a
                         ON a.source_revision_id=sr.source_revision_id
                        AND a.extraction_run_id=sr.extraction_run_id
                       WHERE sr.snapshot_id=%s AND a.id=%s""",
                    (report.snapshot_id, source_anchor_id),
                )
                if cursor.fetchone() is None:
                    raise ReportSuggestionAccessError("source anchor is unavailable")
            cursor.execute(
                """INSERT INTO report_suggestions
                   (id,session_id,author_id,source_anchor_id,target_block_id,suggested_text,rationale,
                    snapshot_id,report_content_hash,kind,origin)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'member') RETURNING *""",
                (suggestion_id, session_id, actor_id, source_anchor_id, target, text, reason,
                 report.snapshot_id, report.content_hash, kind),
            )
            row = cursor.fetchone()
            self._activities.record(
                cursor,
                event_key=build_event_key("suggestion.created", suggestion_id=suggestion_id),
                event_type="suggestion.created", actor_id=actor_id,
                scope_type="session", room_id=room_id, session_id=session_id,
                entity_type="suggestion", entity_id=suggestion_id,
                metadata={"kind": kind, "origin": "member", "status": "open"},
            )
        assert row is not None
        return _view(row)

    def list(self, connection: psycopg.Connection[dict[str, object]], *, session_id: UUID,
             actor_id: UUID) -> tuple[ReportSuggestion, ...]:
        with connection.cursor(row_factory=dict_row) as cursor:
            self._require_member(cursor, session_id, actor_id)
            cursor.execute(
                "SELECT * FROM report_suggestions WHERE session_id=%s ORDER BY created_at,id",
                (session_id,),
            )
            return tuple(_view(row) for row in cursor.fetchall())

    def resolve(self, connection: psycopg.Connection[dict[str, object]], *, suggestion_id: UUID,
                actor_id: UUID, decision: Literal["accepted", "rejected"]) -> ReportSuggestion:
        if decision not in {"accepted", "rejected"}:
            raise ValueError("suggestion decision is invalid")
        with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT suggestion.session_id, session_row.host_id, suggestion.status,
                          membership.user_id AS current_member_id, session_row.room_id
                   FROM report_suggestions suggestion
                   JOIN talk_sessions session_row ON session_row.id=suggestion.session_id
                   LEFT JOIN room_memberships membership
                     ON membership.room_id=session_row.room_id
                    AND membership.user_id=%s AND membership.left_at IS NULL
                   WHERE suggestion.id=%s FOR UPDATE OF suggestion""",
                (actor_id, suggestion_id),
            )
            row = cursor.fetchone()
            if row is None or row["host_id"] != actor_id or row["current_member_id"] is None:
                raise ReportSuggestionAccessError("host permission is required")
            if row["status"] != "open":
                raise ReportSuggestionStateError("suggestion is already resolved")
            cursor.execute(
                """UPDATE report_suggestions SET status=%s,resolved_by=%s,
                   resolved_at=clock_timestamp() WHERE id=%s RETURNING *""",
                (decision, actor_id, suggestion_id),
            )
            updated = cursor.fetchone()
            room_id = cast(UUID, row["room_id"])
            event_type = f"suggestion.{decision}"
            self._activities.record(
                cursor,
                event_key=build_event_key(
                    event_type, suggestion_id=suggestion_id, version=1,
                ),
                event_type=event_type, actor_id=actor_id,
                scope_type="session", room_id=room_id,
                session_id=cast(UUID, row["session_id"]), entity_type="suggestion",
                entity_id=suggestion_id, metadata={"status": decision, "version": 1},
            )
        assert updated is not None
        return _view(updated)

    @staticmethod
    def _require_member(cursor: Any, session_id: UUID, actor_id: UUID) -> UUID:
        cursor.execute(
            """SELECT s.room_id FROM talk_sessions s JOIN room_memberships m ON m.room_id=s.room_id
               AND m.user_id=%s AND m.left_at IS NULL WHERE s.id=%s""",
            (actor_id, session_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise ReportSuggestionAccessError("talk session is unavailable")
        return cast(UUID, row["room_id"])


def _view(row: dict[str, object]) -> ReportSuggestion:
    return ReportSuggestion(
        id=cast(UUID, row["id"]), session_id=cast(UUID, row["session_id"]),
        author_id=cast(UUID, row["author_id"]),
        source_anchor_id=cast(UUID | None, row["source_anchor_id"]),
        target_block_id=cast(str | None, row.get("target_block_id")),
        snapshot_id=cast(UUID, row["snapshot_id"]),
        report_content_hash=str(row["report_content_hash"]),
        kind=cast(Literal["add", "edit", "remove"], row["kind"]),
        origin=cast(Literal["member", "automatic_comparison"], row["origin"]),
        suggested_text=str(row["suggested_text"]), rationale=str(row["rationale"]),
        status=cast(Literal["open", "accepted", "rejected"], row["status"]),
        resolved_by=cast(UUID | None, row["resolved_by"]),
        created_at=cast(datetime, row["created_at"]),
        resolved_at=cast(datetime | None, row["resolved_at"]),
    )
