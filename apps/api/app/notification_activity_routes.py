"""Small authorization adapters needed by private activity HTTP routes."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import psycopg


def resolve_visible_comment_session(
    cursor: psycopg.Cursor[dict[str, Any]], *, comment_id: UUID, requester_id: UUID
) -> UUID:
    """Resolve a comment only through a current membership-constrained relation."""

    cursor.execute(
        """SELECT c.session_id
           FROM room_memberships membership
           JOIN talk_sessions session ON session.room_id=membership.room_id
           JOIN comments c ON c.session_id=session.id
           WHERE membership.user_id=%s AND membership.left_at IS NULL AND c.id=%s""",
        (requester_id, comment_id),
    )
    row = cursor.fetchone()
    if row is None:
        raise PermissionError("comment is unavailable")
    return cast(UUID, row["session_id"])
