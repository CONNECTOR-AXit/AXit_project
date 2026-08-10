"""Allow a host to reopen an already-analyzed session for more input."""

from alembic import op

revision = "0014_session_reopen"
down_revision = "0013_submission_deletion"
branch_labels = None
depends_on = None

_BASE_EVENT_TYPES = (
    "'account.registered','profile.updated','notification_preferences.updated',"
    "'friendship.requested','friendship.accepted','friendship.rejected','room.created','room.member_added',"
    "'session.created','session.closed','session.retry_requested','session.processing','session.ready',"
    "'session.needs_attention','submission.created','submission.revised','submission.deleted',"
    "'source_revision.ready','source_revision.failed','source_revision.retry_requested',"
    "'suggestion.created','suggestion.accepted',"
    "'suggestion.rejected','comment.created','comment.updated','comment.deleted'"
)


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE audit_events DROP CONSTRAINT audit_events_event_type_check;
    ALTER TABLE audit_events ADD CONSTRAINT audit_events_event_type_check CHECK (event_type IN (
      {_BASE_EVENT_TYPES}, 'session.reopened'
    ));
    """)


def downgrade() -> None:
    op.execute(f"""
    ALTER TABLE audit_events DROP CONSTRAINT audit_events_event_type_check;
    ALTER TABLE audit_events ADD CONSTRAINT audit_events_event_type_check CHECK (event_type IN (
      {_BASE_EVENT_TYPES}
    ));
    """)
