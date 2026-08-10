"""Index immutable extracted source text for scoped FTS retrieval."""

from alembic import op

revision = "0005_source_anchor_fts"
down_revision = "0004_submission_titles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX source_anchors_text_fts_idx ON source_anchors "
        "USING GIN (to_tsvector('simple', text))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX source_anchors_text_fts_idx")
