"""Private notification read state and allowlisted same-origin navigation."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg

from app.notification_repository import NotificationRepository, TimePage


def validate_notification_catalog(*, action_kind: str, resource_type: str) -> None:
    allowed = {
        ("respond_friend_request", "friend_request"), ("open_room", "room"),
        ("open_session", "session"), ("open_comment", "comment"),
    }
    if action_kind != "none" and (action_kind, resource_type) not in allowed:
        raise ValueError("unsupported notification action/resource pair")


def notification_href(*, action_kind: str, resource_type: str, resource_id: UUID,
                      session_id: UUID | None = None) -> str:
    """Compute, never persist, an internal relative path from approved typed fields."""
    validate_notification_catalog(action_kind=action_kind, resource_type=resource_type)
    if action_kind == "none":
        href = "/"
    elif action_kind == "respond_friend_request":
        href = "/friends"
    elif action_kind == "open_room":
        href = f"/projects/{resource_id}"
    elif action_kind == "open_session":
        href = f"/projects/{resource_id}"
    else:
        if session_id is None:
            raise ValueError("open_comment requires its owning session")
        href = f"/projects/{session_id}/editor?comment={resource_id}"
    if len(href) > 256 or not href.startswith("/") or href.startswith("//"):
        raise ValueError("unsafe internal notification path")
    return href


class NotificationService:
    def __init__(self, repository: NotificationRepository | None = None) -> None:
        self.repository = repository or NotificationRepository()

    def mark_read(self, cursor: psycopg.Cursor[dict[str, Any]], *, recipient_id: UUID,
                  notification_id: UUID) -> bool:
        cursor.execute("""UPDATE notifications SET read_at=COALESCE(read_at,clock_timestamp())
                          WHERE id=%s AND recipient_id=%s RETURNING id""",
                       (notification_id, recipient_id))
        return cursor.fetchone() is not None

    def mark_all_read(self, cursor: psycopg.Cursor[dict[str, Any]], *, recipient_id: UUID) -> int:
        cursor.execute("""UPDATE notifications SET read_at=clock_timestamp()
                          WHERE recipient_id=%s AND read_at IS NULL""", (recipient_id,))
        return cursor.rowcount

    def list_notifications(self, cursor: psycopg.Cursor[dict[str, Any]], *, recipient_id: UUID,
                           page_cursor: str | None = None, limit: int = 50) -> tuple[TimePage, int]:
        page, unread = self.repository.list_notifications(cursor, recipient_id=recipient_id,
            page_cursor=page_cursor, limit=limit)
        rendered: list[dict[str, Any]] = []
        for item in page.items:
            response = dict(item)
            response["href"] = notification_href(action_kind=item["action_kind"],
                resource_type=item["resource_type"], resource_id=item["resource_id"],
                session_id=item.get("session_id"))
            response.pop("session_id", None)
            response.pop("recipient_id", None)
            response.pop("dedupe_key", None)
            rendered.append(response)
        return TimePage(tuple(rendered), page.next_cursor), unread

    def queued_local_outbox(self, cursor: psycopg.Cursor[dict[str, Any]], *, recipient_id: UUID,
                            page_cursor: str | None = None, limit: int = 50) -> TimePage:
        return self.repository.list_outbox(cursor, recipient_id=recipient_id,
            page_cursor=page_cursor, limit=limit)
