"""Locked profile and notification-preference aggregate persistence."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg


DEFAULT_PREFERENCES = {
    (kind, channel): channel == "in_app"
    for kind in ("analysis_completed", "mention", "comment")
    for channel in ("in_app", "email_intent")
}


class ProfileInvariantError(RuntimeError):
    """Persisted profile aggregates are missing or structurally incomplete."""


class ProfileRepository:
    def lock_profile(
        self, cursor: psycopg.Cursor[dict[str, Any]], user_id: UUID
    ) -> dict[str, Any]:
        cursor.execute(
            """SELECT u.id,u.email,u.display_name,p.job_title,p.language,p.profile_version,
                      p.preferences_version,p.profile_updated_at,p.preferences_updated_at
               FROM users u JOIN user_profiles p ON p.user_id=u.id WHERE u.id=%s FOR UPDATE OF u,p""",
            (user_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ProfileInvariantError("profile aggregate is incomplete")
        return row

    def preferences(
        self, cursor: psycopg.Cursor[dict[str, Any]], user_id: UUID
    ) -> dict[tuple[str, str], bool]:
        cursor.execute(
            "SELECT kind,channel,enabled FROM notification_preferences WHERE user_id=%s",
            (user_id,),
        )
        values = {
            (row["kind"], row["channel"]): row["enabled"] for row in cursor.fetchall()
        }
        if set(values) != set(DEFAULT_PREFERENCES):
            raise ProfileInvariantError("profile aggregate is incomplete")
        return values
