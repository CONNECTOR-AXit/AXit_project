"""Add non-realtime, reviewable report suggestions."""

from alembic import op

revision = "0006_report_suggestions"
down_revision = "0005_source_anchor_fts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE report_suggestions (
            id UUID PRIMARY KEY,
            session_id UUID NOT NULL REFERENCES talk_sessions(id) ON DELETE RESTRICT,
            author_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            source_anchor_id UUID NULL REFERENCES source_anchors(id) ON DELETE RESTRICT,
            suggested_text TEXT NOT NULL CHECK (char_length(suggested_text) BETWEEN 1 AND 10000),
            rationale TEXT NOT NULL DEFAULT '' CHECK (char_length(rationale) <= 2000),
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','accepted','rejected')),
            resolved_by UUID NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMPTZ NULL,
            CHECK ((status = 'open') = (resolved_by IS NULL AND resolved_at IS NULL))
        );
        CREATE INDEX report_suggestions_session_created_idx
          ON report_suggestions(session_id, created_at, id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE report_suggestions")
