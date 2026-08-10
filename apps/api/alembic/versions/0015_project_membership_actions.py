"""Add reversible project archive and participant leave lifecycle actions."""

from alembic import op

revision = "0015_project_membership_actions"
down_revision = "0014_session_reopen"
branch_labels = None
depends_on = None

_BASE_EVENT_TYPES = (
    "'account.registered','profile.updated','notification_preferences.updated',"
    "'friendship.requested','friendship.accepted','friendship.rejected','room.created','room.member_added',"
    "'session.created','session.closed','session.retry_requested','session.processing','session.ready',"
    "'session.needs_attention','session.reopened','submission.created','submission.revised','submission.deleted',"
    "'source_revision.ready','source_revision.failed','source_revision.retry_requested',"
    "'suggestion.created','suggestion.accepted','suggestion.rejected',"
    "'comment.created','comment.updated','comment.deleted'"
)


def upgrade() -> None:
    op.execute("ALTER TABLE talk_sessions ADD COLUMN archived_at TIMESTAMPTZ NULL")
    op.execute(
        "CREATE INDEX talk_sessions_active_room_index "
        "ON talk_sessions (room_id, created_at, id) WHERE archived_at IS NULL"
    )
    op.execute(f"""
    ALTER TABLE audit_events DROP CONSTRAINT audit_events_event_type_check;
    ALTER TABLE audit_events ADD CONSTRAINT audit_events_event_type_check CHECK (event_type IN (
      {_BASE_EVENT_TYPES}, 'session.archived', 'room.member_left'
    ));
    """)


def downgrade() -> None:
    op.execute(
        "DELETE FROM audit_events WHERE event_type IN ('session.archived', 'room.member_left')"
    )
    op.execute(f"""
    ALTER TABLE audit_events DROP CONSTRAINT audit_events_event_type_check;
    ALTER TABLE audit_events ADD CONSTRAINT audit_events_event_type_check CHECK (event_type IN (
      {_BASE_EVENT_TYPES}
    ));
    """)
    op.execute("DROP INDEX talk_sessions_active_room_index")
    op.execute("ALTER TABLE talk_sessions DROP COLUMN archived_at")
