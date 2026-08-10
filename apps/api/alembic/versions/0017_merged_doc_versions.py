"""Add named, restorable merged-document version snapshots."""

from alembic import op

revision = "0017_merged_doc_versions"
down_revision = "0016_merged_document_states"
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
    "'session.archived','room.member_left','merged_document.saved'"
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE merged_document_version_snapshots (
            id UUID PRIMARY KEY,
            session_id UUID NOT NULL REFERENCES talk_sessions(id) ON DELETE RESTRICT,
            snapshot_id UUID NOT NULL REFERENCES generation_snapshots(id) ON DELETE RESTRICT,
            label TEXT NOT NULL CHECK (char_length(label) BETWEEN 1 AND 200),
            blocks_json JSONB NOT NULL,
            document_version INTEGER NOT NULL CHECK (document_version >= 0),
            created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX merged_document_version_snapshots_session_idx
          ON merged_document_version_snapshots(session_id, snapshot_id, created_at);
        """)
    op.execute(f"""
    ALTER TABLE audit_events DROP CONSTRAINT audit_events_event_type_check;
    ALTER TABLE audit_events ADD CONSTRAINT audit_events_event_type_check CHECK (event_type IN (
      {_BASE_EVENT_TYPES}, 'merged_document.version_created'
    ));
    """)


def downgrade() -> None:
    op.execute(
        "DELETE FROM audit_events WHERE event_type IN ('merged_document.version_created')"
    )
    op.execute(f"""
    ALTER TABLE audit_events DROP CONSTRAINT audit_events_event_type_check;
    ALTER TABLE audit_events ADD CONSTRAINT audit_events_event_type_check CHECK (event_type IN (
      {_BASE_EVENT_TYPES}
    ));
    """)
    op.execute("DROP TABLE merged_document_version_snapshots")
