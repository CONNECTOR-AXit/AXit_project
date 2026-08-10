"""Persist user-authored submission titles.

Revision ID: 0004_submission_titles
Revises: 0003_file_limit_100m
"""

from alembic import op


revision = "0004_submission_titles"
down_revision = "0003_file_limit_100m"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE submissions ADD COLUMN title TEXT NOT NULL DEFAULT '공유 자료'"
    )
    op.create_check_constraint(
        "submissions_title_length_check",
        "submissions",
        "char_length(title) BETWEEN 1 AND 500",
    )


def downgrade() -> None:
    op.drop_constraint("submissions_title_length_check", "submissions", type_="check")
    op.drop_column("submissions", "title")
