"""Add persisted, optimistically-concurrent merged document editing state."""

from alembic import op

revision = "0016_merged_document_states"
down_revision = "0015_project_membership_actions"
branch_labels = None
depends_on = None

_BASE_EVENT_TYPES = (
    "'account.registered','profile.updated','notification_preferences.updated',"
    "'friendship.requested','friendship.accepted','friendship.rejected','room.created','room.member_added',"
    "'session.created','session.closed','session.retry_requested','session.processing','session.ready',"
    "'session.needs_attention','session.reopened','submission.created','submission.revised','submission.deleted',"
    "'source_revision.ready','source_revision.failed','source_revision.retry_requested',"
    "'suggestion.created','suggestion.accepted','suggestion.rejected',"
    "'comment.created','comment.updated','comment.deleted',"
    "'session.archived','room.member_left'"
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE merged_document_states (
            id UUID PRIMARY KEY,
            session_id UUID NOT NULL REFERENCES talk_sessions(id) ON DELETE RESTRICT,
            snapshot_id UUID NOT NULL REFERENCES generation_snapshots(id) ON DELETE RESTRICT,
            version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
            blocks_json JSONB NOT NULL,
            updated_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (session_id, snapshot_id)
        );
        CREATE INDEX merged_document_states_session_idx ON merged_document_states(session_id);
        """)
    op.execute(f"""
    ALTER TABLE audit_events DROP CONSTRAINT audit_events_event_type_check;
    ALTER TABLE audit_events ADD CONSTRAINT audit_events_event_type_check CHECK (event_type IN (
      {_BASE_EVENT_TYPES}, 'merged_document.saved'
    ));
    """)


def downgrade() -> None:
    op.execute(
        "DELETE FROM audit_events WHERE event_type IN ('merged_document.saved')"
    )
    op.execute(f"""
    ALTER TABLE audit_events DROP CONSTRAINT audit_events_event_type_check;
    ALTER TABLE audit_events ADD CONSTRAINT audit_events_event_type_check CHECK (event_type IN (
      {_BASE_EVENT_TYPES}
    ));
    """)
    op.execute("DROP TABLE merged_document_states")
