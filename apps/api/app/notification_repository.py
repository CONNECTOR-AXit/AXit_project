"""Bulk persistence for local notification and address-free outbox effects."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from app.activity_pagination import decode_time_cursor, encode_time_cursor


Channel = Literal["in_app", "email_intent"]


@dataclass(frozen=True, slots=True)
class RecipientPreference:
    user_id: UUID
    channels: frozenset[Channel]


@dataclass(frozen=True, slots=True)
class TimePage:
    items: tuple[dict[str, Any], ...]
    next_cursor: str | None


class NotificationRepository:
    def snapshot_preferences(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        recipient_ids: Sequence[UUID],
        kind: str,
    ) -> tuple[RecipientPreference, ...]:
        if not recipient_ids:
            return ()
        if kind in {"friend_request", "room_member_added"}:
            return tuple(
                RecipientPreference(user_id, frozenset({"in_app"}))
                for user_id in dict.fromkeys(recipient_ids)
            )
        cursor.execute(
            """SELECT user_id,channel FROM notification_preferences
               WHERE user_id=ANY(%s) AND kind=%s AND enabled ORDER BY user_id,channel""",
            (list(dict.fromkeys(recipient_ids)), kind),
        )
        channels: dict[UUID, set[Channel]] = {}
        for row in cursor.fetchall():
            channel = row["channel"]
            if channel not in {"in_app", "email_intent"}:
                raise RuntimeError("invalid persisted notification channel")
            channels.setdefault(row["user_id"], set()).add(channel)
        return tuple(
            RecipientPreference(user_id, frozenset(values))
            for user_id, values in channels.items()
        )

    def materialize(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        recipients: Sequence[RecipientPreference],
        kind: str,
        actor_id: UUID | None,
        resource_type: str,
        resource_id: UUID,
        action_kind: str,
        title: str,
        body: str,
        base_dedupe_key: str,
        template_key: str,
        template_data: dict[str, Any],
    ) -> tuple[int, int]:
        notification_recipient_ids = tuple(
            dict.fromkeys(
                recipient.user_id
                for recipient in recipients
                if "in_app" in recipient.channels
            )
        )
        outbox_recipient_ids = tuple(
            dict.fromkeys(
                recipient.user_id
                for recipient in recipients
                if "email_intent" in recipient.channels
            )
        )
        inserted_notifications = 0
        inserted_outbox = 0
        if notification_recipient_ids:
            cursor.execute(
                """INSERT INTO notifications(id,recipient_id,kind,actor_id,resource_type,resource_id,
                     action_kind,title,body,dedupe_key)
                   SELECT batch.id,batch.recipient_id,%s,%s,%s,%s,%s,%s,%s,
                          %s || ':' || batch.recipient_id::text || ':in_app'
                   FROM unnest(%s::uuid[],%s::uuid[]) WITH ORDINALITY
                        AS batch(id,recipient_id,position)
                   ORDER BY batch.position
                   ON CONFLICT(recipient_id,dedupe_key) DO NOTHING""",
                (
                    kind,
                    actor_id,
                    resource_type,
                    resource_id,
                    action_kind,
                    title,
                    body,
                    base_dedupe_key,
                    [uuid4() for _ in notification_recipient_ids],
                    list(notification_recipient_ids),
                ),
            )
            inserted_notifications = cursor.rowcount
        if outbox_recipient_ids:
            cursor.execute(
                """INSERT INTO email_outbox(id,recipient_id,notification_kind,dedupe_key,template_key,template_data)
                   SELECT batch.id,batch.recipient_id,%s,
                          %s || ':' || batch.recipient_id::text || ':email_intent',%s,%s
                   FROM unnest(%s::uuid[],%s::uuid[]) WITH ORDINALITY
                        AS batch(id,recipient_id,position)
                   ORDER BY batch.position
                   ON CONFLICT(recipient_id,dedupe_key) DO NOTHING""",
                (
                    kind,
                    base_dedupe_key,
                    template_key,
                    Jsonb(template_data),
                    [uuid4() for _ in outbox_recipient_ids],
                    list(outbox_recipient_ids),
                ),
            )
            inserted_outbox = cursor.rowcount
        return inserted_notifications, inserted_outbox

    def list_notifications(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        recipient_id: UUID,
        page_cursor: str | None,
        limit: int,
    ) -> tuple[TimePage, int]:
        bounded_limit = max(1, min(limit, 100))
        anchor: tuple[datetime, UUID] | None = (
            decode_time_cursor(page_cursor) if page_cursor else None
        )
        if anchor is not None:
            cursor.execute(
                "SELECT created_at FROM notifications WHERE id=%s AND recipient_id=%s",
                (anchor[1], recipient_id),
            )
            owned_anchor = cursor.fetchone()
            if owned_anchor is None or owned_anchor["created_at"] != anchor[0]:
                raise PermissionError("notification cursor is unavailable")
        cursor.execute(
            """SELECT n.*,CASE
                 WHEN n.resource_type='comment' THEN c.session_id
                 ELSE NULL END AS session_id
               FROM notifications n
               LEFT JOIN comments c ON n.resource_type='comment' AND c.id=n.resource_id
               WHERE n.recipient_id=%s
                 AND (%s::timestamptz IS NULL OR (n.created_at,n.id) < (%s,%s))
               ORDER BY n.created_at DESC,n.id DESC LIMIT %s""",
            (
                recipient_id,
                anchor[0] if anchor else None,
                anchor[0] if anchor else None,
                anchor[1] if anchor else None,
                bounded_limit + 1,
            ),
        )
        rows = cursor.fetchall()
        visible = rows[:bounded_limit]
        next_cursor = (
            encode_time_cursor(visible[-1]["created_at"], visible[-1]["id"])
            if len(rows) > bounded_limit
            else None
        )
        cursor.execute(
            "SELECT count(*) AS count FROM notifications WHERE recipient_id=%s AND read_at IS NULL",
            (recipient_id,),
        )
        count = cursor.fetchone()
        if count is None:
            raise RuntimeError("notification unread count was not returned")
        return TimePage(tuple(visible), next_cursor), count["count"]

    def list_outbox(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        recipient_id: UUID,
        page_cursor: str | None,
        limit: int,
    ) -> TimePage:
        bounded_limit = max(1, min(limit, 100))
        anchor = decode_time_cursor(page_cursor) if page_cursor else None
        if anchor is not None:
            cursor.execute(
                "SELECT created_at FROM email_outbox WHERE id=%s AND recipient_id=%s",
                (anchor[1], recipient_id),
            )
            owned_anchor = cursor.fetchone()
            if owned_anchor is None or owned_anchor["created_at"] != anchor[0]:
                raise PermissionError("outbox cursor is unavailable")
        cursor.execute(
            """SELECT id,notification_kind,dedupe_key,template_key,template_data,status,created_at
               FROM email_outbox WHERE recipient_id=%s
                 AND (%s::timestamptz IS NULL OR (created_at,id) < (%s,%s))
               ORDER BY created_at DESC,id DESC LIMIT %s""",
            (
                recipient_id,
                anchor[0] if anchor else None,
                anchor[0] if anchor else None,
                anchor[1] if anchor else None,
                bounded_limit + 1,
            ),
        )
        rows = cursor.fetchall()
        visible = rows[:bounded_limit]
        next_cursor = (
            encode_time_cursor(visible[-1]["created_at"], visible[-1]["id"])
            if len(rows) > bounded_limit
            else None
        )
        return TimePage(tuple(visible), next_cursor)
