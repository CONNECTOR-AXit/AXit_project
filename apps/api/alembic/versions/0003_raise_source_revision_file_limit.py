"""Allow locally stored source files up to 100 MiB.

Revision ID: 0003_file_limit_100m
Revises: 0002_file_extraction_provenance
"""

from alembic import op


revision = "0003_file_limit_100m"
down_revision = "0002_file_extraction_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("source_revisions_byte_size_check", "source_revisions", type_="check")
    op.create_check_constraint(
        "source_revisions_byte_size_check",
        "source_revisions",
        "byte_size >= 0 AND byte_size <= 104857600",
    )


def downgrade() -> None:
    op.drop_constraint("source_revisions_byte_size_check", "source_revisions", type_="check")
    op.create_check_constraint(
        "source_revisions_byte_size_check",
        "source_revisions",
        "byte_size >= 0 AND byte_size <= 20971520",
    )
