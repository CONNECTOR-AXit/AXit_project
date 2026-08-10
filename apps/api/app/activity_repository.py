"""Caller-transaction-owned persistence for the append-only activity ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from app.activity_pagination import decode_event_cursor, encode_event_cursor


ActivityScope = Literal["personal", "room", "session"]


@dataclass(frozen=True, slots=True)
class AppendedActivity:
    id: UUID
    event_key: str
    ledger_sequence: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ActivityPage:
    items: tuple[dict[str, Any], ...]
    next_cursor: str | None
    coverage_started_at: datetime


class ActivityRepository:
    def append(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        event_key: str,
        event_type: str,
        actor_id: UUID | None,
        scope_type: ActivityScope,
        audience_user_id: UUID | None,
        room_id: UUID | None,
        session_id: UUID | None,
        entity_type: str,
        entity_id: UUID,
        metadata: dict[str, Any],
    ) -> AppendedActivity | None:
        event_id = uuid4()
        cursor.execute(
            """INSERT INTO audit_events(id,event_key,event_type,actor_id,scope_type,
                   audience_user_id,room_id,session_id,entity_type,entity_id,metadata_json)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(event_key) DO NOTHING
               RETURNING id,event_key,ledger_sequence,created_at""",
            (
                event_id,
                event_key,
                event_type,
                actor_id,
                scope_type,
                audience_user_id,
                room_id,
                session_id,
                entity_type,
                entity_id,
                Jsonb(metadata),
            ),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return AppendedActivity(
            row["id"], row["event_key"], row["ledger_sequence"], row["created_at"]
        )

    def list_authorized(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        requester_id: UUID,
        scope: Literal["all", "personal", "room", "session"],
        scope_id: UUID | None,
        page_cursor: str | None,
        limit: int,
    ) -> ActivityPage:
        bounded_limit = max(1, min(limit, 100))
        predicate, parameters = self._authorized_predicate(
            cursor, requester_id=requester_id, scope=scope, scope_id=scope_id
        )
        anchor_sequence: int | None = None
        if page_cursor is not None:
            anchor_id = decode_event_cursor(page_cursor)
            cursor.execute(
                f"SELECT ledger_sequence FROM audit_events e WHERE e.id=%s AND ({predicate})",  # noqa: S608
                (anchor_id, *parameters),
            )
            anchor = cursor.fetchone()
            if anchor is None:
                raise PermissionError("audit cursor is unavailable")
            anchor_sequence = anchor["ledger_sequence"]
        query = f"""SELECT e.*,u.display_name AS actor_display_name
                    FROM audit_events e LEFT JOIN users u ON u.id=e.actor_id
                    WHERE ({predicate})
                    AND (%s::bigint IS NULL OR e.ledger_sequence < %s)
                    ORDER BY e.ledger_sequence DESC LIMIT %s"""  # noqa: S608
        cursor.execute(
            query, (*parameters, anchor_sequence, anchor_sequence, bounded_limit + 1)
        )
        rows = cursor.fetchall()
        visible = rows[:bounded_limit]
        next_cursor = (
            encode_event_cursor(visible[-1]["id"])
            if len(rows) > bounded_limit
            else None
        )
        cursor.execute(
            "SELECT coverage_started_at FROM audit_ledger_metadata WHERE singleton=TRUE"
        )
        coverage = cursor.fetchone()
        if coverage is None:
            raise RuntimeError("audit coverage marker is absent")
        return ActivityPage(
            tuple(visible), next_cursor, coverage["coverage_started_at"]
        )

    def _authorized_predicate(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        requester_id: UUID,
        scope: Literal["all", "personal", "room", "session"],
        scope_id: UUID | None,
    ) -> tuple[str, tuple[object, ...]]:
        if scope in {"all", "personal"} and scope_id is not None:
            raise ValueError("scope_id is forbidden for all/personal scope")
        if scope in {"room", "session"} and scope_id is None:
            raise ValueError("scope_id is required for room/session scope")
        membership = "EXISTS(SELECT 1 FROM room_memberships m WHERE m.room_id=e.room_id AND m.user_id=%s AND m.left_at IS NULL)"
        if scope == "personal":
            return "e.scope_type='personal' AND e.audience_user_id=%s", (requester_id,)
        if scope == "all":
            return (
                f"(e.scope_type='personal' AND e.audience_user_id=%s) OR (e.scope_type IN ('room','session') AND {membership})",
                (requester_id, requester_id),
            )
        if scope == "room":
            cursor.execute(
                "SELECT 1 FROM room_memberships WHERE room_id=%s AND user_id=%s AND left_at IS NULL",
                (scope_id, requester_id),
            )
            if cursor.fetchone() is None:
                raise PermissionError("audit scope is unavailable")
            return (
                "e.scope_type='room' AND e.room_id=%s AND "
                "EXISTS(SELECT 1 FROM room_memberships m WHERE m.room_id=e.room_id "
                "AND m.user_id=%s AND m.left_at IS NULL)"
            ), (scope_id, requester_id)
        cursor.execute(
            """SELECT 1 FROM talk_sessions s JOIN room_memberships m ON m.room_id=s.room_id
                          WHERE s.id=%s AND m.user_id=%s AND m.left_at IS NULL""",
            (scope_id, requester_id),
        )
        if cursor.fetchone() is None:
            raise PermissionError("audit scope is unavailable")
        return (
            "e.scope_type='session' AND e.session_id=%s AND "
            "EXISTS(SELECT 1 FROM talk_sessions s JOIN room_memberships m ON m.room_id=s.room_id "
            "WHERE s.id=e.session_id AND s.room_id=e.room_id AND m.user_id=%s "
            "AND m.left_at IS NULL)"
        ), (scope_id, requester_id)
