"""Add durable automatic comparison suggestions."""

from alembic import op


revision = "0011_auto_report_suggestions"
down_revision = "0010_file_limit_200m"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE jobs DROP CONSTRAINT jobs_kind_check;
        ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check
          CHECK (kind IN ('extraction', 'summary', 'research', 'report_suggestions'));

        ALTER TABLE report_suggestions
          ADD COLUMN kind TEXT NOT NULL DEFAULT 'add',
          ADD COLUMN origin TEXT NOT NULL DEFAULT 'member',
          ADD COLUMN comparison_key TEXT NULL;
        ALTER TABLE report_suggestions
          ADD CONSTRAINT report_suggestions_kind_check
            CHECK (kind IN ('add', 'edit', 'remove')),
          ADD CONSTRAINT report_suggestions_origin_check
            CHECK (origin IN ('member', 'automatic_comparison')),
          ADD CONSTRAINT report_suggestions_origin_shape
            CHECK (
              (origin = 'member' AND comparison_key IS NULL)
              OR
              (origin = 'automatic_comparison'
               AND comparison_key ~ '^[0-9a-f]{64}$')
            );
        CREATE UNIQUE INDEX report_suggestions_snapshot_comparison_unique
          ON report_suggestions(snapshot_id, comparison_key)
          WHERE comparison_key IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX report_suggestions_snapshot_comparison_unique;
        ALTER TABLE report_suggestions
          DROP CONSTRAINT report_suggestions_origin_shape,
          DROP CONSTRAINT report_suggestions_origin_check,
          DROP CONSTRAINT report_suggestions_kind_check,
          DROP COLUMN comparison_key,
          DROP COLUMN origin,
          DROP COLUMN kind;

        ALTER TABLE jobs DROP CONSTRAINT jobs_kind_check;
        ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check
          CHECK (kind IN ('extraction', 'summary', 'research'));
        """
    )
