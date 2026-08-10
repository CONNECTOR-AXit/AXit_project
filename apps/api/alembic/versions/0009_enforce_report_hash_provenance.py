"""Enforce that suggestion hashes identify the canonical snapshot report."""
from alembic import op

revision = "0009_report_hash_guard"
down_revision = "0008_normalize_report_hashes"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("""
    CREATE OR REPLACE FUNCTION enforce_report_suggestion_provenance() RETURNS trigger AS $$
    DECLARE expected_hash TEXT;
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM generation_snapshots snapshot WHERE snapshot.id=NEW.snapshot_id AND snapshot.session_id=NEW.session_id)
      THEN RAISE EXCEPTION 'report suggestion snapshot provenance mismatch'; END IF;
      SELECT encode(digest(max(document.content_hash) FILTER (WHERE document.kind='summary') || max(document.content_hash) FILTER (WHERE document.kind='research'), 'sha256'), 'hex')
      INTO expected_hash FROM generation_snapshots snapshot
      JOIN generation_runs run ON run.snapshot_id=snapshot.id AND run.state='succeeded' AND run.pipeline_version=snapshot.pipeline_version
      JOIN generated_documents document ON document.run_id=run.id
      WHERE snapshot.id=NEW.snapshot_id HAVING count(*)=2 AND count(DISTINCT document.kind)=2;
      IF expected_hash IS NULL OR expected_hash <> NEW.report_content_hash
      THEN RAISE EXCEPTION 'report suggestion content hash provenance mismatch'; END IF;
      IF NEW.source_anchor_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM snapshot_revisions sr JOIN source_anchors anchor
          ON anchor.source_revision_id=sr.source_revision_id AND anchor.extraction_run_id=sr.extraction_run_id
        WHERE sr.snapshot_id=NEW.snapshot_id AND anchor.id=NEW.source_anchor_id)
      THEN RAISE EXCEPTION 'report suggestion anchor provenance mismatch'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    DROP TRIGGER report_suggestion_provenance ON report_suggestions;
    CREATE TRIGGER report_suggestion_provenance BEFORE INSERT OR UPDATE OF session_id,snapshot_id,source_anchor_id,report_content_hash
      ON report_suggestions FOR EACH ROW EXECUTE FUNCTION enforce_report_suggestion_provenance();
    """)

def downgrade() -> None:
    op.execute("""
    DROP TRIGGER report_suggestion_provenance ON report_suggestions;
    CREATE OR REPLACE FUNCTION enforce_report_suggestion_provenance() RETURNS trigger AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM generation_snapshots snapshot WHERE snapshot.id=NEW.snapshot_id AND snapshot.session_id=NEW.session_id)
      THEN RAISE EXCEPTION 'report suggestion snapshot provenance mismatch'; END IF;
      IF NEW.source_anchor_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM snapshot_revisions sr JOIN source_anchors anchor
          ON anchor.source_revision_id=sr.source_revision_id AND anchor.extraction_run_id=sr.extraction_run_id
        WHERE sr.snapshot_id=NEW.snapshot_id AND anchor.id=NEW.source_anchor_id)
      THEN RAISE EXCEPTION 'report suggestion anchor provenance mismatch'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER report_suggestion_provenance
      BEFORE INSERT OR UPDATE OF session_id,snapshot_id,source_anchor_id ON report_suggestions
      FOR EACH ROW EXECUTE FUNCTION enforce_report_suggestion_provenance();
    """)
