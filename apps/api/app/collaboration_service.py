"""Durable friends, private rooms, invitations, and relay-session services.

All object reads start at a current room membership join.  That makes the
membership boundary the first authorization decision and avoids turning room
or session IDs into an existence oracle for non-members.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from app.activity_policy import build_event_key
from app.activity_service import ActivityService, NotificationEffect
from app.auth_service import UserRecord


class CollaborationError(ValueError):
    """Base class for collaboration state failures."""


class CollaborationAccessError(PermissionError):
    """Membership was absent, so resource details must remain hidden."""


class CollaborationHostRequiredError(PermissionError):
    """A current member attempted a host-only collaboration action."""


class FriendshipRequiredError(PermissionError):
    """Only accepted friends may enter a private room together."""


class FriendshipConflictError(CollaborationError):
    """A canonical friendship pair already exists in an incompatible state."""


class FriendshipStateError(CollaborationError):
    """A friendship cannot transition from its current persisted state."""


class UserUnavailableError(CollaborationError):
    """A requested user is not a valid collaborator target."""


class SessionUnavailableError(CollaborationAccessError):
    """A session cannot be revealed before room-membership authorization."""


@dataclass(frozen=True, slots=True)
class FriendshipView:
    id: UUID
    requester: UserRecord
    addressee: UserRecord
    status: Literal["pending", "accepted", "rejected"]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FriendView:
    user: UserRecord
    friendship_id: UUID


@dataclass(frozen=True, slots=True)
class RoomMemberView:
    user: UserRecord
    role: Literal["host", "member"]


@dataclass(frozen=True, slots=True)
class RoomView:
    id: UUID
    name: str
    owner_id: UUID
    role: Literal["host", "member"]


@dataclass(frozen=True, slots=True)
class RoomInvitationView:
    id: UUID
    room_id: UUID
    invitee_id: UUID
    status: Literal["pending", "accepted", "rejected"]


@dataclass(frozen=True, slots=True)
class TalkSessionView:
    id: UUID
    room_id: UUID
    host_id: UUID
    topic: str
    description: str
    deadline: datetime | None
    state: Literal[
        "draft",
        "open",
        "closed",
        "processing",
        "ready",
        "needs_attention",
    ]
    generation_epoch: int
    created_at: datetime
    closed_at: datetime | None


class CollaborationService:
    """Perform private-room state changes in short PostgreSQL transactions."""

    def __init__(self, activity_service: ActivityService | None = None) -> None:
        self._activities = activity_service or ActivityService()

    def create_friend_request(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        actor_id: UUID,
        addressee_id: UUID,
    ) -> FriendshipView:
        """Create one canonical friend-request pair, safely under races."""

        if actor_id == addressee_id:
            raise FriendshipConflictError("cannot create a friendship with self")
        friendship_id = uuid4()
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT id FROM users WHERE id = %s", (addressee_id,))
                if cursor.fetchone() is None:
                    raise UserUnavailableError("user is unavailable")
                cursor.execute(
                    """
                    INSERT INTO friendships (id, requester_id, addressee_id, status)
                    VALUES (%s, %s, %s, 'pending')
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """,
                    (friendship_id, actor_id, addressee_id),
                )
                inserted = cursor.fetchone()
                if inserted is None:
                    existing = _friendship_pair_for_update(
                        cursor, actor_id, addressee_id
                    )
                    if existing is None:
                        raise CollaborationError("friendship pair was not persisted")
                    # Same-direction duplicate clicks are intentionally
                    # idempotent; opposite-direction races are not silently
                    # converted into acceptance.
                    if (
                        existing["requester_id"] != actor_id
                        or existing["addressee_id"] != addressee_id
                    ):
                        raise FriendshipConflictError("friendship already exists")
                    friendship_id = _uuid(existing["id"], "friendship id")
                else:
                    for audience_user_id in (actor_id, addressee_id):
                        effects: tuple[NotificationEffect, ...] = ()
                        if audience_user_id == addressee_id:
                            effects = (
                                NotificationEffect(
                                    (addressee_id,),
                                    "friend_request",
                                    "friend_request",
                                    friendship_id,
                                    "respond_friend_request",
                                    "친구 요청",
                                    "새 친구 요청이 도착했습니다.",
                                    "friend_request",
                                    {},
                                ),
                            )
                        self._activities.record(
                            cursor,
                            event_key=build_event_key(
                                "friendship.requested",
                                friendship_id=friendship_id,
                                audience_user_id=audience_user_id,
                            ),
                            event_type="friendship.requested",
                            actor_id=actor_id,
                            scope_type="personal",
                            audience_user_id=audience_user_id,
                            entity_type="friendship",
                            entity_id=friendship_id,
                            metadata={"status": "pending"},
                            notification_effects=effects,
                        )
                return _fetch_friendship_view(cursor, friendship_id)

    def respond_to_friend_request(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        actor_id: UUID,
        friendship_id: UUID,
        accept: bool,
    ) -> FriendshipView:
        """Accept or reject a request only as its addressee.

        A repeated response with the same terminal state is idempotent.  A
        conflicting terminal action is rejected rather than rewriting audit
        history.
        """

        target_status = "accepted" if accept else "rejected"
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, requester_id, addressee_id, status
                    FROM friendships
                    WHERE id = %s AND addressee_id = %s
                    FOR UPDATE
                    """,
                    (friendship_id, actor_id),
                )
                current = cursor.fetchone()
                if current is None:
                    raise CollaborationAccessError("friend request is unavailable")
                current_status = _status(current["status"], "friendship status")
                if current_status == "pending":
                    cursor.execute(
                        """
                        UPDATE friendships
                        SET status = %s, responded_at = clock_timestamp()
                        WHERE id = %s AND status = 'pending'
                        """,
                        (target_status, friendship_id),
                    )
                    if cursor.rowcount != 1:
                        raise FriendshipStateError(
                            "friend request changed while locked"
                        )
                    requester_id = _uuid(current["requester_id"], "requester id")
                    addressee_id = _uuid(current["addressee_id"], "addressee id")
                    event_type = f"friendship.{target_status}"
                    for audience_user_id in (requester_id, addressee_id):
                        self._activities.record(
                            cursor,
                            event_key=build_event_key(
                                event_type,
                                friendship_id=friendship_id,
                                audience_user_id=audience_user_id,
                            ),
                            event_type=event_type,
                            actor_id=actor_id,
                            scope_type="personal",
                            audience_user_id=audience_user_id,
                            entity_type="friendship",
                            entity_id=friendship_id,
                            metadata={"status": target_status},
                        )
                elif current_status != target_status:
                    raise FriendshipStateError(
                        "friend request has already been answered"
                    )
                return _fetch_friendship_view(cursor, friendship_id)

    def list_friend_requests(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        actor_id: UUID,
    ) -> list[FriendshipView]:
        """Return only requests where the actor is one of the two participants."""

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT friendship.id
                FROM friendships AS friendship
                WHERE friendship.requester_id = %s OR friendship.addressee_id = %s
                ORDER BY friendship.created_at, friendship.id
                """,
                (actor_id, actor_id),
            )
            friendship_ids = [
                _uuid(row["id"], "friendship id") for row in cursor.fetchall()
            ]
            return [
                _fetch_friendship_view(cursor, friendship_id)
                for friendship_id in friendship_ids
            ]

    def list_friends(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        actor_id: UUID,
    ) -> list[FriendView]:
        """Return only accepted friendship counterparts in deterministic order."""

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT friendship.id AS friendship_id,
                       user_row.id AS user_id,
                       user_row.email,
                       user_row.display_name
                FROM friendships AS friendship
                JOIN users AS user_row
                  ON user_row.id = CASE
                      WHEN friendship.requester_id = %s THEN friendship.addressee_id
                      ELSE friendship.requester_id
                  END
                WHERE friendship.status = 'accepted'
                  AND (friendship.requester_id = %s OR friendship.addressee_id = %s)
                ORDER BY user_row.display_name, user_row.id
                """,
                (actor_id, actor_id, actor_id),
            )
            rows = cursor.fetchall()
        return [
            FriendView(
                user=UserRecord(
                    id=_uuid(row["user_id"], "friend user id"),
                    email=_text(row["email"], "friend email"),
                    display_name=_text(row["display_name"], "friend display name"),
                ),
                friendship_id=_uuid(row["friendship_id"], "friendship id"),
            )
            for row in rows
        ]

    def create_room(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        actor_id: UUID,
        name: str,
    ) -> RoomView:
        """Create a private room and its owner membership atomically."""

        normalized_name = _room_name(name)
        room_id = uuid4()
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "INSERT INTO rooms (id, owner_id, name) VALUES (%s, %s, %s)",
                    (room_id, actor_id, normalized_name),
                )
                cursor.execute(
                    """
                    INSERT INTO room_memberships (room_id, user_id, role)
                    VALUES (%s, %s, 'host')
                    """,
                    (room_id, actor_id),
                )
                self._activities.record(
                    cursor,
                    event_key=build_event_key("room.created", room_id=room_id),
                    event_type="room.created",
                    actor_id=actor_id,
                    scope_type="room",
                    room_id=room_id,
                    entity_type="room",
                    entity_id=room_id,
                    metadata={"member_count": 1},
                )
        return RoomView(room_id, normalized_name, actor_id, "host")

    def list_rooms(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        actor_id: UUID,
    ) -> list[RoomView]:
        """Return current private-room memberships without revealing departed rooms."""

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT room.id, room.name, room.owner_id, membership.role
                FROM room_memberships AS membership
                JOIN rooms AS room ON room.id = membership.room_id
                WHERE membership.user_id = %s AND membership.left_at IS NULL
                ORDER BY room.created_at, room.id
                """,
                (actor_id,),
            )
            rows = cursor.fetchall()
        return [_room_from_row(row) for row in rows]

    def list_room_members(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        actor_id: UUID,
        room_id: UUID,
    ) -> list[RoomMemberView]:
        """List active room members only after establishing actor membership."""

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT user_row.id AS user_id, user_row.email,
                       user_row.display_name, membership.role
                FROM room_memberships AS actor_membership
                JOIN room_memberships AS membership
                  ON membership.room_id = actor_membership.room_id
                 AND membership.left_at IS NULL
                JOIN users AS user_row ON user_row.id = membership.user_id
                WHERE actor_membership.room_id = %s
                  AND actor_membership.user_id = %s
                  AND actor_membership.left_at IS NULL
                ORDER BY membership.user_id
                """,
                (room_id, actor_id),
            )
            rows = cursor.fetchall()
        if not rows:
            raise CollaborationAccessError("room is unavailable")
        return [
            RoomMemberView(
                user=UserRecord(
                    id=_uuid(row["user_id"], "room member user id"),
                    email=_text(row["email"], "room member email"),
                    display_name=_text(row["display_name"], "room member display name"),
                ),
                role=_role(row["role"]),
            )
            for row in rows
        ]

    def create_room_invitation(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        actor_id: UUID,
        room_id: UUID,
        invitee_id: UUID,
    ) -> RoomInvitationView:
        """Atomically admit an accepted friend as an accepted invitation/member.

        Phase 3 has no separate invitation-accept endpoint.  Therefore this
        operation is intentionally an admission transaction: it verifies an
        accepted friendship, writes an ``accepted`` invitation, and creates
        (or restores) membership before committing any of those facts.
        """

        if actor_id == invitee_id:
            raise FriendshipConflictError("cannot invite self")
        invitation_id = uuid4()
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                membership = _locked_room_membership(cursor, room_id, actor_id)
                if membership is None:
                    raise CollaborationAccessError("room is unavailable")
                if membership["role"] != "host":
                    raise CollaborationHostRequiredError("room host role is required")
                cursor.execute("SELECT id FROM users WHERE id = %s", (invitee_id,))
                if cursor.fetchone() is None:
                    raise UserUnavailableError("user is unavailable")
                friendship = _friendship_pair_for_update(cursor, actor_id, invitee_id)
                if friendship is None or friendship["status"] != "accepted":
                    raise FriendshipRequiredError(
                        "only accepted friends may be invited"
                    )
                cursor.execute(
                    """SELECT id,status FROM room_invitations
                       WHERE room_id=%s AND invitee_id=%s FOR UPDATE""",
                    (room_id, invitee_id),
                )
                prior_invitation = cursor.fetchone()
                cursor.execute(
                    """SELECT left_at FROM room_memberships
                       WHERE room_id=%s AND user_id=%s FOR UPDATE""",
                    (room_id, invitee_id),
                )
                prior_membership = cursor.fetchone()
                if (
                    prior_invitation is not None
                    and prior_invitation["status"] == "accepted"
                    and (
                        prior_membership is None
                        or prior_membership["left_at"] is not None
                    )
                ):
                    raise FriendshipConflictError(
                        "departed room members cannot be readmitted by replaying an invitation"
                    )
                admission_changed = (
                    prior_invitation is None
                    or prior_invitation["status"] != "accepted"
                    or prior_membership is None
                    or prior_membership["left_at"] is not None
                )
                if prior_invitation is None:
                    cursor.execute(
                        """INSERT INTO room_invitations
                           (id,room_id,invitee_id,inviter_id,status,responded_at)
                           VALUES(%s,%s,%s,%s,'accepted',clock_timestamp())
                           RETURNING id,room_id,invitee_id,status""",
                        (invitation_id, room_id, invitee_id, actor_id),
                    )
                elif prior_invitation["status"] != "accepted":
                    invitation_id = _uuid(prior_invitation["id"], "room invitation id")
                    cursor.execute(
                        """UPDATE room_invitations SET inviter_id=%s,status='accepted',
                           responded_at=clock_timestamp() WHERE id=%s
                           RETURNING id,room_id,invitee_id,status""",
                        (actor_id, invitation_id),
                    )
                else:
                    invitation_id = _uuid(prior_invitation["id"], "room invitation id")
                    cursor.execute(
                        "SELECT id,room_id,invitee_id,status FROM room_invitations WHERE id=%s",
                        (invitation_id,),
                    )
                invitation = _require_row(cursor.fetchone(), "room invitation")
                if prior_membership is None:
                    cursor.execute(
                        """INSERT INTO room_memberships (room_id,user_id,role)
                           VALUES (%s,%s,'member')""",
                        (room_id, invitee_id),
                    )
                elif prior_membership["left_at"] is not None:
                    cursor.execute(
                        """UPDATE room_memberships SET left_at=NULL,
                           role=CASE WHEN role='host' THEN 'host' ELSE 'member' END
                           WHERE room_id=%s AND user_id=%s""",
                        (room_id, invitee_id),
                    )
                if admission_changed:
                    self._activities.record(
                        cursor,
                        event_key=build_event_key(
                            "room.member_added",
                            room_id=room_id,
                            user_id=invitee_id,
                        ),
                        event_type="room.member_added",
                        actor_id=actor_id,
                        scope_type="room",
                        room_id=room_id,
                        entity_type="room_member",
                        entity_id=invitee_id,
                        metadata={"role": "member"},
                        notification_effects=(
                            NotificationEffect(
                                (invitee_id,),
                                "room_member_added",
                                "room",
                                room_id,
                                "open_room",
                                "프로젝트 초대",
                                "프로젝트에 참여했습니다.",
                                "room_member_added",
                                {"room_id": room_id},
                            ),
                        ),
                    )
        return _invitation_from_row(invitation)

    def create_talk_session(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        actor_id: UUID,
        room_id: UUID,
        topic: str,
        description: str = "",
        deadline: datetime | None = None,
    ) -> TalkSessionView:
        """Open a relay session only for the current room host."""

        normalized_topic = _topic(topic)
        normalized_description = _description(description)
        session_id = uuid4()
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                membership = _locked_room_membership(cursor, room_id, actor_id)
                if membership is None:
                    raise CollaborationAccessError("room is unavailable")
                if membership["role"] != "host":
                    raise CollaborationHostRequiredError("room host role is required")
                cursor.execute(
                    """
                    INSERT INTO talk_sessions (
                        id, room_id, host_id, mode, topic, description, deadline, state
                    ) VALUES (%s, %s, %s, 'relay', %s, %s, %s, 'open')
                    RETURNING id, room_id, host_id, topic, description, deadline,
                              state, generation_epoch, created_at, closed_at
                    """,
                    (
                        session_id,
                        room_id,
                        actor_id,
                        normalized_topic,
                        normalized_description,
                        deadline,
                    ),
                )
                row = _require_row(cursor.fetchone(), "talk session")
                self._activities.record(
                    cursor,
                    event_key=build_event_key("session.created", session_id=session_id),
                    event_type="session.created",
                    actor_id=actor_id,
                    scope_type="session",
                    room_id=room_id,
                    session_id=session_id,
                    entity_type="session",
                    entity_id=session_id,
                    metadata={"state": "open"},
                )
        return _session_from_row(row)

    def list_talk_sessions(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        actor_id: UUID,
        room_id: UUID,
    ) -> list[TalkSessionView]:
        """List room sessions only after establishing actor membership."""

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT session_row.id, session_row.room_id, session_row.host_id,
                       session_row.topic, session_row.description, session_row.deadline,
                       session_row.state, session_row.generation_epoch,
                       session_row.created_at, session_row.closed_at
                FROM room_memberships AS actor_membership
                LEFT JOIN talk_sessions AS session_row
                  ON session_row.room_id = actor_membership.room_id
                 AND session_row.archived_at IS NULL
                WHERE actor_membership.room_id = %s
                  AND actor_membership.user_id = %s
                  AND actor_membership.left_at IS NULL
                ORDER BY session_row.created_at, session_row.id
                """,
                (room_id, actor_id),
            )
            rows = cursor.fetchall()
        if not rows:
            raise CollaborationAccessError("room is unavailable")
        return [_session_from_row(row) for row in rows if row["id"] is not None]

    def get_talk_session(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        actor_id: UUID,
        session_id: UUID,
    ) -> TalkSessionView:
        """Read a session only through an active room-membership join."""

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT session_row.id, session_row.room_id, session_row.host_id,
                       session_row.topic, session_row.description, session_row.deadline,
                       session_row.state, session_row.generation_epoch,
                       session_row.created_at, session_row.closed_at
                FROM talk_sessions AS session_row
                JOIN room_memberships AS membership
                  ON membership.room_id = session_row.room_id
                 AND membership.user_id = %s
                 AND membership.left_at IS NULL
                WHERE session_row.id = %s
                  AND session_row.archived_at IS NULL
                """,
                (actor_id, session_id),
            )
            row = cursor.fetchone()
        if row is None:
            raise SessionUnavailableError("session is unavailable")
        return _session_from_row(row)

    def archive_talk_session(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        actor_id: UUID,
        session_id: UUID,
    ) -> None:
        """Hide a project session from every member, enforcing the host boundary."""

        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT session_row.room_id, session_row.archived_at, membership.role
                    FROM talk_sessions AS session_row
                    JOIN room_memberships AS membership
                      ON membership.room_id = session_row.room_id
                     AND membership.user_id = %s
                     AND membership.left_at IS NULL
                    WHERE session_row.id = %s
                    FOR UPDATE OF session_row, membership
                    """,
                    (actor_id, session_id),
                )
                row = cursor.fetchone()
                if row is None:
                    raise SessionUnavailableError("session is unavailable")
                if row["role"] != "host":
                    raise CollaborationHostRequiredError("room host role is required")
                if row["archived_at"] is not None:
                    return
                cursor.execute(
                    "UPDATE talk_sessions SET archived_at=clock_timestamp() WHERE id=%s",
                    (session_id,),
                )
                self._activities.record(
                    cursor,
                    event_key=build_event_key(
                        "session.archived", session_id=session_id
                    ),
                    event_type="session.archived",
                    actor_id=actor_id,
                    scope_type="session",
                    room_id=_uuid(row["room_id"], "session room id"),
                    session_id=session_id,
                    entity_type="session",
                    entity_id=session_id,
                    metadata={"visibility": "archived"},
                )

    def leave_room(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        actor_id: UUID,
        room_id: UUID,
    ) -> None:
        """End a participant membership while preventing the host from orphaning a room."""

        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                membership = _locked_room_membership(cursor, room_id, actor_id)
                if membership is None:
                    raise CollaborationAccessError("room is unavailable")
                if membership["role"] == "host":
                    raise CollaborationHostRequiredError("room host cannot leave")
                cursor.execute(
                    """
                    UPDATE room_memberships
                    SET left_at=clock_timestamp()
                    WHERE room_id=%s AND user_id=%s AND left_at IS NULL
                    """,
                    (room_id, actor_id),
                )
                self._activities.record(
                    cursor,
                    event_key=build_event_key(
                        "room.member_left", room_id=room_id, user_id=actor_id
                    ),
                    event_type="room.member_left",
                    actor_id=actor_id,
                    scope_type="room",
                    room_id=room_id,
                    entity_type="room_member",
                    entity_id=actor_id,
                    metadata={"role": "member"},
                )

    def require_session_membership(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        *,
        actor_id: UUID,
        session_id: UUID,
    ) -> TalkSessionView:
        """Alias for adapters that need a membership-gated session projection."""

        return self.get_talk_session(
            connection,
            actor_id=actor_id,
            session_id=session_id,
        )


def _friendship_pair_for_update(
    cursor: psycopg.Cursor[dict[str, Any]],
    first_user_id: UUID,
    second_user_id: UUID,
) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT id, requester_id, addressee_id, status
        FROM friendships
        WHERE LEAST(requester_id, addressee_id) = LEAST(%s, %s)
          AND GREATEST(requester_id, addressee_id) = GREATEST(%s, %s)
        FOR UPDATE
        """,
        (first_user_id, second_user_id, first_user_id, second_user_id),
    )
    return cursor.fetchone()


def _locked_room_membership(
    cursor: psycopg.Cursor[dict[str, Any]],
    room_id: UUID,
    actor_id: UUID,
) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT membership.role
        FROM rooms AS room
        JOIN room_memberships AS membership
          ON membership.room_id = room.id
         AND membership.user_id = %s
         AND membership.left_at IS NULL
        WHERE room.id = %s
        FOR UPDATE OF room, membership
        """,
        (actor_id, room_id),
    )
    return cursor.fetchone()


def _fetch_friendship_view(
    cursor: psycopg.Cursor[dict[str, Any]],
    friendship_id: UUID,
) -> FriendshipView:
    cursor.execute(
        """
        SELECT friendship.id,
               friendship.status,
               friendship.created_at,
               requester.id AS requester_id,
               requester.email AS requester_email,
               requester.display_name AS requester_display_name,
               addressee.id AS addressee_id,
               addressee.email AS addressee_email,
               addressee.display_name AS addressee_display_name
        FROM friendships AS friendship
        JOIN users AS requester ON requester.id = friendship.requester_id
        JOIN users AS addressee ON addressee.id = friendship.addressee_id
        WHERE friendship.id = %s
        """,
        (friendship_id,),
    )
    row = _require_row(cursor.fetchone(), "friendship")
    return FriendshipView(
        id=_uuid(row["id"], "friendship id"),
        requester=UserRecord(
            id=_uuid(row["requester_id"], "requester id"),
            email=_text(row["requester_email"], "requester email"),
            display_name=_text(row["requester_display_name"], "requester display name"),
        ),
        addressee=UserRecord(
            id=_uuid(row["addressee_id"], "addressee id"),
            email=_text(row["addressee_email"], "addressee email"),
            display_name=_text(row["addressee_display_name"], "addressee display name"),
        ),
        status=_status(row["status"], "friendship status"),
        created_at=_datetime(row["created_at"], "friendship created_at"),
    )


def _room_from_row(row: dict[str, Any]) -> RoomView:
    role = _role(row["role"])
    return RoomView(
        id=_uuid(row["id"], "room id"),
        name=_text(row["name"], "room name"),
        owner_id=_uuid(row["owner_id"], "room owner id"),
        role=role,
    )


def _invitation_from_row(row: dict[str, Any]) -> RoomInvitationView:
    return RoomInvitationView(
        id=_uuid(row["id"], "room invitation id"),
        room_id=_uuid(row["room_id"], "room invitation room id"),
        invitee_id=_uuid(row["invitee_id"], "room invitation invitee id"),
        status=_status(row["status"], "room invitation status"),
    )


def _session_from_row(row: dict[str, Any]) -> TalkSessionView:
    state = _session_state(row["state"])
    deadline = row["deadline"]
    if deadline is not None and not isinstance(deadline, datetime):
        raise RuntimeError("persisted session deadline must be datetime or null")
    generation_epoch = row["generation_epoch"]
    if isinstance(generation_epoch, bool) or not isinstance(generation_epoch, int):
        raise RuntimeError("persisted session generation epoch must be an integer")
    return TalkSessionView(
        id=_uuid(row["id"], "session id"),
        room_id=_uuid(row["room_id"], "session room id"),
        host_id=_uuid(row["host_id"], "session host id"),
        topic=_text(row["topic"], "session topic"),
        description=_text_or_empty(row["description"], "session description"),
        deadline=deadline,
        state=state,
        generation_epoch=generation_epoch,
        created_at=_datetime(row["created_at"], "session created_at"),
        closed_at=_optional_datetime(row["closed_at"], "session closed_at"),
    )


def _datetime(value: object, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError(f"persisted {label} must be datetime")
    return value


def _optional_datetime(value: object, label: str) -> datetime | None:
    if value is None:
        return None
    return _datetime(value, label)


def _room_name(value: str) -> str:
    if not isinstance(value, str):
        raise CollaborationError("room name is required")
    normalized = value.strip()
    if not 1 <= len(normalized) <= 240 or "\x00" in normalized:
        raise CollaborationError("room name is invalid")
    return normalized


def _topic(value: str) -> str:
    if not isinstance(value, str):
        raise CollaborationError("session topic is required")
    normalized = value.strip()
    if not 1 <= len(normalized) <= 500 or "\x00" in normalized:
        raise CollaborationError("session topic is invalid")
    return normalized


def _description(value: str) -> str:
    if not isinstance(value, str) or len(value) > 10_000 or "\x00" in value:
        raise CollaborationError("session description is invalid")
    return value.strip()


def _require_row(row: dict[str, Any] | None, label: str) -> dict[str, Any]:
    if row is None:
        raise RuntimeError(f"{label} was not returned")
    return row


def _uuid(value: object, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise RuntimeError(f"persisted {label} must be UUID")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"persisted {label} must be non-empty text")
    return value


def _text_or_empty(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"persisted {label} must be text")
    return value


def _status(value: object, label: str) -> Literal["pending", "accepted", "rejected"]:
    if value in {"pending", "accepted", "rejected"}:
        return value
    raise RuntimeError(f"persisted {label} is invalid")


def _role(value: object) -> Literal["host", "member"]:
    if value in {"host", "member"}:
        return value
    raise RuntimeError("persisted room role is invalid")


def _session_state(
    value: object,
) -> Literal["draft", "open", "closed", "processing", "ready", "needs_attention"]:
    if value in {"draft", "open", "closed", "processing", "ready", "needs_attention"}:
        return value
    raise RuntimeError("persisted session state is invalid")
