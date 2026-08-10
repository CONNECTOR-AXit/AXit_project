"""Bind asynchronous extraction runs to their exact fenced queue attempt.

Revision ID: 0002_file_extraction_provenance
Revises: 0001_durable_core
"""

from alembic import op


revision = "0002_file_extraction_provenance"
down_revision = "0001_durable_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE extraction_runs ADD COLUMN job_attempt_id UUID NULL;
        ALTER TABLE extraction_runs
            ADD CONSTRAINT extraction_runs_job_attempt_fk
            FOREIGN KEY (job_attempt_id) REFERENCES job_attempts(id) ON DELETE RESTRICT;
        CREATE UNIQUE INDEX extraction_runs_job_attempt_unique
            ON extraction_runs (job_attempt_id) WHERE job_attempt_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX extraction_runs_job_attempt_unique;
        ALTER TABLE extraction_runs DROP CONSTRAINT extraction_runs_job_attempt_fk;
        ALTER TABLE extraction_runs DROP COLUMN job_attempt_id;
        """
    )
