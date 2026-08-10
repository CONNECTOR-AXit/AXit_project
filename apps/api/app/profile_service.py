"""Optimistic, aggregate-isolated profile and preference changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import psycopg

from app.profile_repository import DEFAULT_PREFERENCES, ProfileRepository
from app.activity_policy import build_event_key
from app.activity_service import ActivityService


class StaleProfileVersionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class UpdateResult:
    version: int
    updated: bool


class ProfileService:
    def __init__(
        self,
        repository: ProfileRepository | None = None,
        activities: ActivityService | None = None,
    ) -> None:
        self.repository = repository or ProfileRepository()
        self.activities = activities or ActivityService()

    def get_profile(
        self, cursor: psycopg.Cursor[dict[str, Any]], *, user_id: UUID
    ) -> dict[str, Any]:
        row = self.repository.lock_profile(cursor, user_id)
        return {
            "user_id": row["id"],
            **{
                key: row[key]
                for key in (
                    "email",
                    "display_name",
                    "job_title",
                    "language",
                    "profile_version",
                    "profile_updated_at",
                )
            },
        }

    def get_preferences(
        self, cursor: psycopg.Cursor[dict[str, Any]], *, user_id: UUID
    ) -> dict[str, Any]:
        row = self.repository.lock_profile(cursor, user_id)
        return {
            "values": self.repository.preferences(cursor, user_id),
            "preferences_version": row["preferences_version"],
            "preferences_updated_at": row["preferences_updated_at"],
        }

    def update_profile(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        user_id: UUID,
        expected_version: int,
        display_name: str,
        job_title: str | None,
        language: Literal["ko", "en", "ja"],
    ) -> UpdateResult:
        name = display_name.strip()
        title = job_title.strip() if job_title is not None else None
        if not 1 <= len(name) <= 200 or (
            title is not None and not 1 <= len(title) <= 200
        ):
            raise ValueError("profile fields exceed approved bounds")
        current = self.repository.lock_profile(cursor, user_id)
        if current["profile_version"] != expected_version:
            raise StaleProfileVersionError("stale profile version")
        if (current["display_name"], current["job_title"], current["language"]) == (
            name,
            title,
            language,
        ):
            return UpdateResult(expected_version, False)
        changed_fields = [
            field
            for field, old, new in (
                ("display_name", current["display_name"], name),
                ("job_title", current["job_title"], title),
                ("language", current["language"], language),
            )
            if old != new
        ]
        cursor.execute("UPDATE users SET display_name=%s WHERE id=%s", (name, user_id))
        cursor.execute(
            """UPDATE user_profiles SET job_title=%s,language=%s,
                          profile_version=profile_version+1,profile_updated_at=clock_timestamp()
                          WHERE user_id=%s RETURNING profile_version""",
            (title, language, user_id),
        )
        row = cursor.fetchone()
        assert row is not None
        version = row["profile_version"]
        self.activities.record(
            cursor,
            event_key=build_event_key(
                "profile.updated", user_id=user_id, profile_version=version
            ),
            event_type="profile.updated",
            actor_id=user_id,
            scope_type="personal",
            audience_user_id=user_id,
            entity_type="user_profile",
            entity_id=user_id,
            metadata={"changed_fields": changed_fields},
        )
        return UpdateResult(version, True)

    def update_preferences(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        user_id: UUID,
        expected_version: int,
        values: dict[tuple[str, str], bool],
    ) -> UpdateResult:
        if set(values) != set(DEFAULT_PREFERENCES):
            raise ValueError("preferences must provide the complete approved matrix")
        current_profile = self.repository.lock_profile(cursor, user_id)
        if current_profile["preferences_version"] != expected_version:
            raise StaleProfileVersionError("stale preferences version")
        current = self.repository.preferences(cursor, user_id)
        changed = [
            (enabled, user_id, kind, channel)
            for (kind, channel), enabled in values.items()
            if current.get((kind, channel)) is not enabled
        ]
        if not changed:
            return UpdateResult(expected_version, False)
        cursor.executemany(
            """UPDATE notification_preferences SET enabled=%s,updated_at=clock_timestamp()
                              WHERE user_id=%s AND kind=%s AND channel=%s""",
            changed,
        )
        cursor.execute(
            """UPDATE user_profiles SET preferences_version=preferences_version+1,
                          preferences_updated_at=clock_timestamp() WHERE user_id=%s
                          RETURNING preferences_version""",
            (user_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        version = row["preferences_version"]
        self.activities.record(
            cursor,
            event_key=build_event_key(
                "notification_preferences.updated",
                user_id=user_id,
                preferences_version=version,
            ),
            event_type="notification_preferences.updated",
            actor_id=user_id,
            scope_type="personal",
            audience_user_id=user_id,
            entity_type="notification_preferences",
            entity_id=user_id,
            metadata={"changed_count": len(changed)},
        )
        return UpdateResult(version, True)
