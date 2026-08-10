"""Normalize existing suggestion pins to the canonical report-pair hash."""
from alembic import op

revision = "0008_normalize_report_hashes"
down_revision = "0007_pin_report_suggestions"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("""CREATE EXTENSION IF NOT EXISTS pgcrypto;
    UPDATE report_suggestions suggestion SET report_content_hash=(
      SELECT encode(digest(string_agg(document.content_hash, '' ORDER BY
        CASE document.kind WHEN 'summary' THEN 0 ELSE 1 END), 'sha256'), 'hex')
      FROM generation_runs run JOIN generated_documents document ON document.run_id=run.id
      WHERE run.snapshot_id=suggestion.snapshot_id AND run.state='succeeded'
      HAVING count(DISTINCT document.kind)=2
    );""")

def downgrade() -> None:
    pass
