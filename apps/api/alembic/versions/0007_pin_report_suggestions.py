"""Pin suggestions to the immutable generated report they discuss."""

from alembic import op

revision = "0007_pin_report_suggestions"
down_revision = "0006_report_suggestions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE EXTENSION IF NOT EXISTS pgcrypto;
        ALTER TABLE report_suggestions ADD COLUMN snapshot_id UUID NULL;
        ALTER TABLE report_suggestions ADD COLUMN report_content_hash TEXT NULL;
        UPDATE report_suggestions suggestion
        SET (snapshot_id, report_content_hash) = (
          SELECT snapshot.id AS snapshot_id,
                 encode(digest(string_agg(document.content_hash, '' ORDER BY
                   CASE document.kind WHEN 'summary' THEN 0 ELSE 1 END), 'sha256'), 'hex') AS report_hash
          FROM generation_snapshots snapshot
          JOIN generation_runs run ON run.snapshot_id=snapshot.id AND run.state='succeeded'
          JOIN generated_documents document ON document.run_id=run.id
          WHERE snapshot.session_id=suggestion.session_id
          GROUP BY snapshot.id, snapshot.generation_epoch
          HAVING count(DISTINCT document.kind)=2
          ORDER BY snapshot.generation_epoch DESC LIMIT 1
        );
        DELETE FROM report_suggestions WHERE snapshot_id IS NULL;
        ALTER TABLE report_suggestions ALTER COLUMN snapshot_id SET NOT NULL;
        ALTER TABLE report_suggestions ALTER COLUMN report_content_hash SET NOT NULL;
        ALTER TABLE report_suggestions
          ADD CONSTRAINT report_suggestions_snapshot_fk
          FOREIGN KEY (snapshot_id) REFERENCES generation_snapshots(id) ON DELETE RESTRICT;
        ALTER TABLE report_suggestions
          ADD CONSTRAINT report_suggestions_hash_check
          CHECK (report_content_hash ~ '^[0-9a-f]{64}$');

        CREATE FUNCTION enforce_report_suggestion_provenance() RETURNS trigger AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM generation_snapshots snapshot
            WHERE snapshot.id=NEW.snapshot_id AND snapshot.session_id=NEW.session_id
          ) THEN RAISE EXCEPTION 'report suggestion snapshot provenance mismatch'; END IF;
          IF NEW.source_anchor_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM snapshot_revisions sr JOIN source_anchors anchor
              ON anchor.source_revision_id=sr.source_revision_id
             AND anchor.extraction_run_id=sr.extraction_run_id
            WHERE sr.snapshot_id=NEW.snapshot_id AND anchor.id=NEW.source_anchor_id
          ) THEN RAISE EXCEPTION 'report suggestion anchor provenance mismatch'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER report_suggestion_provenance
          BEFORE INSERT OR UPDATE OF session_id,snapshot_id,source_anchor_id ON report_suggestions
          FOR EACH ROW EXECUTE FUNCTION enforce_report_suggestion_provenance();
        """
    )

def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER report_suggestion_provenance ON report_suggestions;
        DROP FUNCTION enforce_report_suggestion_provenance();
        ALTER TABLE report_suggestions DROP COLUMN report_content_hash;
        ALTER TABLE report_suggestions DROP COLUMN snapshot_id;
        """
    )
