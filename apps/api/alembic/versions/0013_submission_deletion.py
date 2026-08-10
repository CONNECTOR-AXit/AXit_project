"""Allow a submission's author to soft-delete it, mirroring the comments tombstone pattern."""

from alembic import op

revision = "0013_submission_deletion"
down_revision = "0012_notification_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
    ALTER TABLE submissions ADD COLUMN deleted_at TIMESTAMPTZ NULL;

    CREATE FUNCTION axit_reject_submission_delete() RETURNS trigger AS $$ BEGIN
      RAISE EXCEPTION 'submissions require a tombstone' USING ERRCODE='55000'; END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER submissions_reject_delete BEFORE DELETE ON submissions
      FOR EACH ROW EXECUTE FUNCTION axit_reject_submission_delete();

    ALTER TABLE audit_events DROP CONSTRAINT audit_events_event_type_check;
    ALTER TABLE audit_events ADD CONSTRAINT audit_events_event_type_check CHECK (event_type IN (
      'account.registered','profile.updated','notification_preferences.updated',
      'friendship.requested','friendship.accepted','friendship.rejected','room.created','room.member_added',
      'session.created','session.closed','session.retry_requested','session.processing','session.ready',
      'session.needs_attention','submission.created','submission.revised','submission.deleted',
      'source_revision.ready','source_revision.failed','source_revision.retry_requested',
      'suggestion.created','suggestion.accepted',
      'suggestion.rejected','comment.created','comment.updated','comment.deleted'
    ));
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE audit_events DROP CONSTRAINT audit_events_event_type_check;
    ALTER TABLE audit_events ADD CONSTRAINT audit_events_event_type_check CHECK (event_type IN (
      'account.registered','profile.updated','notification_preferences.updated',
      'friendship.requested','friendship.accepted','friendship.rejected','room.created','room.member_added',
      'session.created','session.closed','session.retry_requested','session.processing','session.ready',
      'session.needs_attention','submission.created','submission.revised',
      'source_revision.ready','source_revision.failed','suggestion.created','suggestion.accepted',
      'suggestion.rejected','comment.created','comment.updated','comment.deleted'
    ));

    DROP TRIGGER submissions_reject_delete ON submissions;
    DROP FUNCTION axit_reject_submission_delete();
    ALTER TABLE submissions DROP COLUMN deleted_at;
    """)
