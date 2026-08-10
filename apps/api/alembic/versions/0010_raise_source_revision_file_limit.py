"""Allow locally stored source files up to 200 MiB.

Revision ID: 0010_file_limit_200m
Revises: 0009_report_hash_guard
"""

from alembic import op


revision = "0010_file_limit_200m"
down_revision = "0009_report_hash_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("source_revisions_byte_size_check", "source_revisions", type_="check")
    op.create_check_constraint(
        "source_revisions_byte_size_check",
        "source_revisions",
        "byte_size >= 0 AND byte_size <= 209715200",
    )


def downgrade() -> None:
    op.drop_constraint("source_revisions_byte_size_check", "source_revisions", type_="check")
    op.create_check_constraint(
        "source_revisions_byte_size_check",
        "source_revisions",
        "byte_size >= 0 AND byte_size <= 104857600",
    )
