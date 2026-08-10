"""Pin Grok editor suggestions to merged-document blocks."""

from alembic import op


revision = "0018_suggestion_targets"
down_revision = "0017_merged_doc_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE report_suggestions
          ADD COLUMN target_block_id TEXT NULL
          CHECK (target_block_id IS NULL OR char_length(target_block_id) BETWEEN 1 AND 200);
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE report_suggestions DROP COLUMN target_block_id;")
