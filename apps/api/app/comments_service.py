"""Transactional comments, explicit mentions, activity, and recipient effects."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg

from app.activity_policy import build_event_key, plan_comment_recipients
from app.activity_service import ActivityService, NotificationEffect
from app.comments_repository import CommentPage, CommentsRepository, SessionAccess


class CommentReplayConflictError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CommentMutation:
    id: UUID
    version: int
    idempotent: bool


class CommentsService:
    def __init__(
        self,
        repository: CommentsRepository | None = None,
        activities: ActivityService | None = None,
    ) -> None:
        self.repository = repository or CommentsRepository()
        self.activities = activities or ActivityService()

    def list(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        session_id: UUID,
        requester_id: UUID,
        page_cursor: str | None = None,
        limit: int = 50,
    ) -> CommentPage:
        return self.repository.list(
            cursor,
            session_id=session_id,
            requester_id=requester_id,
            page_cursor=page_cursor,
            limit=limit,
        )

    def create(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        session_id: UUID,
        author_id: UUID,
        client_request_id: UUID,
        body: str,
        anchor_kind: Literal["report", "generated_segment"] | None,
        anchor_id: UUID | None,
        mentioned_user_ids: tuple[UUID, ...],
    ) -> CommentMutation:
        normalized = _body(body)
        _anchor(anchor_kind, anchor_id)
        access = self.repository.require_membership(
            cursor, session_id=session_id, user_id=author_id
        )
        mentions = _mentions(mentioned_user_ids, actor_id=author_id, access=access)
        fingerprint = _fingerprint(normalized, anchor_kind, anchor_id, mentions)
        comment_id = uuid4()
        cursor.execute(
            """INSERT INTO comments(id,session_id,author_id,client_request_id,request_fingerprint,
                          body,anchor_kind,anchor_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                          ON CONFLICT(author_id,client_request_id) DO NOTHING RETURNING id,version""",
            (
                comment_id,
                session_id,
                author_id,
                client_request_id,
                fingerprint,
                normalized,
                anchor_kind,
                anchor_id,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            cursor.execute(
                """SELECT id,session_id,version,request_fingerprint FROM comments
                              WHERE author_id=%s AND client_request_id=%s""",
                (author_id, client_request_id),
            )
            existing = cursor.fetchone()
            if existing is None:
                raise RuntimeError("concurrent comment replay did not converge")
            if (
                existing["session_id"] != session_id
                or existing["request_fingerprint"] != fingerprint
            ):
                raise CommentReplayConflictError(
                    "client request id was reused with different content"
                )
            return CommentMutation(existing["id"], existing["version"], True)
        self.repository.insert_mentions(
            cursor, comment_id=comment_id, mentioned_user_ids=mentions
        )
        self._record(
            cursor,
            event_type="comment.created",
            comment_id=comment_id,
            version=row["version"],
            actor_id=author_id,
            session_id=session_id,
            access=access,
            notification_effects=_create_effects(
                author_id, comment_id, access, mentions
            ),
        )
        return CommentMutation(comment_id, row["version"], False)

    def update(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
        comment_id: UUID,
        expected_version: int,
        body: str,
        anchor_kind: Literal["report", "generated_segment"] | None,
        anchor_id: UUID | None,
        mentioned_user_ids: tuple[UUID, ...],
    ) -> CommentMutation:
        normalized = _body(body)
        _anchor(anchor_kind, anchor_id)
        access = self.repository.require_membership(
            cursor, session_id=session_id, user_id=actor_id
        )
        mentions = _mentions(mentioned_user_ids, actor_id=actor_id, access=access)
        cursor.execute(
            """SELECT id,author_id,version,body,anchor_kind,anchor_id,deleted_at
                          FROM comments WHERE id=%s AND session_id=%s FOR UPDATE""",
            (comment_id, session_id),
        )
        current = cursor.fetchone()
        if (
            current is None
            or current["author_id"] != actor_id
            or current["deleted_at"] is not None
        ):
            raise PermissionError("comment is unavailable")
        if current["version"] != expected_version:
            raise CommentReplayConflictError("stale comment version")
        cursor.execute(
            "SELECT user_id FROM comment_mentions WHERE comment_id=%s ORDER BY user_id",
            (comment_id,),
        )
        old_mentions = frozenset(row["user_id"] for row in cursor.fetchall())
        if (
            current["body"],
            current["anchor_kind"],
            current["anchor_id"],
            old_mentions,
        ) == (normalized, anchor_kind, anchor_id, frozenset(mentions)):
            return CommentMutation(comment_id, expected_version, True)
        cursor.execute(
            """UPDATE comments SET body=%s,anchor_kind=%s,anchor_id=%s,version=version+1,
                          updated_at=clock_timestamp() WHERE id=%s RETURNING version""",
            (normalized, anchor_kind, anchor_id, comment_id),
        )
        updated = cursor.fetchone()
        assert updated is not None
        removed = old_mentions - set(mentions)
        if removed:
            cursor.execute(
                "DELETE FROM comment_mentions WHERE comment_id=%s AND user_id=ANY(%s)",
                (comment_id, list(removed)),
            )
        added = tuple(user_id for user_id in mentions if user_id not in old_mentions)
        self.repository.insert_mentions(
            cursor, comment_id=comment_id, mentioned_user_ids=added
        )
        effects = () if not added else (_mention_effect(comment_id, added),)
        self._record(
            cursor,
            event_type="comment.updated",
            comment_id=comment_id,
            version=updated["version"],
            actor_id=actor_id,
            session_id=session_id,
            access=access,
            notification_effects=effects,
        )
        return CommentMutation(comment_id, updated["version"], False)

    def delete(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        session_id: UUID,
        actor_id: UUID,
        comment_id: UUID,
        expected_version: int,
    ) -> CommentMutation:
        access = self.repository.require_membership(
            cursor, session_id=session_id, user_id=actor_id
        )
        cursor.execute(
            "SELECT author_id,version,deleted_at FROM comments WHERE id=%s AND session_id=%s FOR UPDATE",
            (comment_id, session_id),
        )
        current = cursor.fetchone()
        if current is None or actor_id not in {
            current["author_id"],
            access.room_owner_id,
        }:
            raise PermissionError("comment is unavailable")
        if current["version"] != expected_version:
            raise CommentReplayConflictError("stale comment version")
        if current["deleted_at"] is not None:
            return CommentMutation(comment_id, expected_version, True)
        cursor.execute(
            """UPDATE comments SET body='',version=version+1,updated_at=clock_timestamp(),
                          deleted_at=clock_timestamp() WHERE id=%s RETURNING version""",
            (comment_id,),
        )
        updated = cursor.fetchone()
        assert updated is not None
        self._record(
            cursor,
            event_type="comment.deleted",
            comment_id=comment_id,
            version=updated["version"],
            actor_id=actor_id,
            session_id=session_id,
            access=access,
            notification_effects=(),
        )
        return CommentMutation(comment_id, updated["version"], False)

    def _record(
        self,
        cursor: psycopg.Cursor[dict[str, Any]],
        *,
        event_type: str,
        comment_id: UUID,
        version: int,
        actor_id: UUID,
        session_id: UUID,
        access: SessionAccess,
        notification_effects: tuple[NotificationEffect, ...],
    ) -> None:
        self.activities.record(
            cursor,
            event_key=build_event_key(
                event_type, comment_id=comment_id, version=version
            ),
            event_type=event_type,
            actor_id=actor_id,
            scope_type="session",
            room_id=access.room_id,
            session_id=session_id,
            entity_type="comment",
            entity_id=comment_id,
            metadata={"version": version},
            notification_effects=notification_effects,
        )


def _body(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 5_000 or "\x00" in normalized:
        raise ValueError("comment body is invalid")
    return normalized


def _anchor(kind: str | None, anchor_id: UUID | None) -> None:
    if (kind is None) != (anchor_id is None) or kind not in {
        None,
        "report",
        "generated_segment",
    }:
        raise ValueError("comment anchor is invalid")


def _mentions(
    values: tuple[UUID, ...], *, actor_id: UUID, access: SessionAccess
) -> tuple[UUID, ...]:
    mentions = tuple(dict.fromkeys(value for value in values if value != actor_id))
    if len(mentions) > 20:
        raise ValueError("at most 20 explicit mentions are allowed")
    if any(value not in access.member_ids for value in mentions):
        raise PermissionError("mentioned user is not a current member")
    return mentions


def _fingerprint(
    body: str,
    anchor_kind: str | None,
    anchor_id: UUID | None,
    mentions: tuple[UUID, ...],
) -> str:
    payload = {
        "body": body,
        "anchor_kind": anchor_kind,
        "anchor_id": str(anchor_id) if anchor_id else None,
        "mentions": sorted(str(item) for item in mentions),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _mention_effect(
    comment_id: UUID, recipients: tuple[UUID, ...]
) -> NotificationEffect:
    return NotificationEffect(
        recipients,
        "mention",
        "comment",
        comment_id,
        "open_comment",
        "댓글에서 회원님을 언급했습니다",
        "새 댓글 멘션이 있습니다.",
        "comment_mention",
        {"comment_id": str(comment_id)},
    )


def _create_effects(
    actor_id: UUID, comment_id: UUID, access: SessionAccess, mentions: tuple[UUID, ...]
) -> tuple[NotificationEffect, ...]:
    plan = plan_comment_recipients(
        actor_id=actor_id, member_ids=access.member_ids, mentioned_user_ids=mentions
    )
    effects: list[NotificationEffect] = []
    if plan["mention"]:
        effects.append(_mention_effect(comment_id, plan["mention"]))
    if plan["comment"]:
        effects.append(
            NotificationEffect(
                plan["comment"],
                "comment",
                "comment",
                comment_id,
                "open_comment",
                "새 댓글이 작성되었습니다",
                "새 댓글이 있습니다.",
                "comment_created",
                {"comment_id": str(comment_id)},
            )
        )
    return tuple(effects)
