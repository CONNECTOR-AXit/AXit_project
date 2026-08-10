"""Membership-first comment persistence primitives."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg

from app.activity_pagination import decode_time_cursor, encode_time_cursor


@dataclass(frozen=True, slots=True)
class SessionAccess:
    room_id: UUID
    room_owner_id: UUID
    member_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class CommentPage:
    items: tuple[dict[str, Any], ...]
    next_cursor: str | None


class CommentsRepository:
    def require_membership(self, cursor: psycopg.Cursor[dict[str, Any]], *, session_id: UUID,
                           user_id: UUID) -> SessionAccess:
        cursor.execute("""SELECT s.room_id,r.owner_id FROM talk_sessions s JOIN rooms r ON r.id=s.room_id
                          JOIN room_memberships own ON own.room_id=s.room_id AND own.user_id=%s AND own.left_at IS NULL
                          WHERE s.id=%s FOR SHARE OF s,r,own""", (user_id, session_id))
        access = cursor.fetchone()
        if access is None:
            raise PermissionError("session is unavailable")
        cursor.execute("""SELECT m.user_id FROM room_memberships m WHERE m.room_id=%s
                          AND m.left_at IS NULL ORDER BY m.user_id FOR SHARE""", (access["room_id"],))
        members = tuple(row["user_id"] for row in cursor.fetchall())
        return SessionAccess(access["room_id"], access["owner_id"], members)

    def insert_mentions(self, cursor: psycopg.Cursor[dict[str, Any]], *, comment_id: UUID,
                        mentioned_user_ids: Sequence[UUID]) -> None:
        cursor.executemany("INSERT INTO comment_mentions(comment_id,user_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                           [(comment_id, user_id) for user_id in dict.fromkeys(mentioned_user_ids)])

    def list(self, cursor: psycopg.Cursor[dict[str, Any]], *, session_id: UUID, requester_id: UUID,
             page_cursor: str | None, limit: int) -> CommentPage:
        self.require_membership(cursor, session_id=session_id, user_id=requester_id)
        bounded_limit = max(1, min(limit, 100))
        anchor: tuple[datetime, UUID] | None = decode_time_cursor(page_cursor) if page_cursor else None
        if anchor is not None:
            cursor.execute("SELECT created_at FROM comments WHERE id=%s AND session_id=%s",
                           (anchor[1], session_id))
            owned_anchor = cursor.fetchone()
            if owned_anchor is None or owned_anchor["created_at"] != anchor[0]:
                raise PermissionError("comment cursor is unavailable")
        cursor.execute("""SELECT c.*,COALESCE(array_agg(cm.user_id ORDER BY cm.user_id)
                          FILTER (WHERE cm.user_id IS NOT NULL),'{}') AS mentioned_user_ids
                          FROM comments c LEFT JOIN comment_mentions cm ON cm.comment_id=c.id
                          WHERE c.session_id=%s AND (%s::timestamptz IS NULL OR (c.created_at,c.id)<(%s,%s))
                          GROUP BY c.id ORDER BY c.created_at DESC,c.id DESC LIMIT %s""",
                       (session_id, anchor[0] if anchor else None, anchor[0] if anchor else None,
                        anchor[1] if anchor else None, bounded_limit + 1))
        rows = cursor.fetchall()
        visible = rows[:bounded_limit]
        next_cursor = (encode_time_cursor(visible[-1]["created_at"], visible[-1]["id"])
                       if len(rows) > bounded_limit else None)
        return CommentPage(tuple(visible), next_cursor)
