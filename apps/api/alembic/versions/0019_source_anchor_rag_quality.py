"""Exclude low-quality extraction anchors from the local RAG index."""

from alembic import op


revision = "0019_anchor_rag_quality"
down_revision = "0018_suggestion_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE FUNCTION source_anchor_rag_exclusion_reason(
          anchor_text TEXT,
          anchor_block_type TEXT,
          anchor_confidence DOUBLE PRECISION
        ) RETURNS TEXT
        LANGUAGE sql IMMUTABLE PARALLEL SAFE
        AS $$
          SELECT CASE
            WHEN btrim(anchor_text) = '' THEN 'blank_text'
            WHEN position(U&'\FFFD' IN anchor_text) > 0 THEN 'corrupt_characters'
            WHEN regexp_replace(anchor_text, E'[\\t\\n\\r]', '', 'g')
                 ~ '[[:cntrl:]]'
              THEN 'control_characters'
            WHEN anchor_block_type IN ('image_ocr', 'pdf_ocr')
             AND (anchor_confidence IS NULL OR anchor_confidence < 0.72)
              THEN 'low_ocr_confidence'
            WHEN anchor_block_type IN ('image_ocr', 'pdf_ocr')
             AND char_length(btrim(anchor_text)) < 3
              THEN 'short_ocr_fragment'
            WHEN anchor_block_type IN ('image_ocr', 'pdf_ocr')
             AND cardinality(regexp_split_to_array(btrim(anchor_text), '[[:space:]]+')) <= 6
             AND btrim(anchor_text) ~ '(^|[[:space:]])(해|하|되|된|할|될)[.!?]?$'
              THEN 'incomplete_ocr_fragment'
            ELSE NULL
          END
        $$;

        ALTER TABLE source_anchors
          ADD COLUMN rag_eligible BOOLEAN,
          ADD COLUMN rag_exclusion_reason TEXT;

        CREATE FUNCTION enforce_source_anchor_rag_quality()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          NEW.rag_exclusion_reason := source_anchor_rag_exclusion_reason(
            NEW.text, NEW.block_type, NEW.confidence
          );
          NEW.rag_eligible := NEW.rag_exclusion_reason IS NULL;
          RETURN NEW;
        END
        $$;

        CREATE TRIGGER source_anchor_rag_quality
          BEFORE INSERT OR UPDATE OF text, block_type, confidence
          ON source_anchors
          FOR EACH ROW EXECUTE FUNCTION enforce_source_anchor_rag_quality();

        UPDATE source_anchors
        SET rag_exclusion_reason = source_anchor_rag_exclusion_reason(
              text, block_type, confidence
            ),
            rag_eligible = source_anchor_rag_exclusion_reason(
              text, block_type, confidence
            ) IS NULL;

        ALTER TABLE source_anchors
          ALTER COLUMN rag_eligible SET NOT NULL,
          ALTER COLUMN rag_eligible SET DEFAULT TRUE,
          ADD CONSTRAINT source_anchor_rag_quality_consistent CHECK (
            (rag_eligible AND rag_exclusion_reason IS NULL)
            OR (NOT rag_eligible AND rag_exclusion_reason IS NOT NULL)
          );

        DROP INDEX source_anchors_text_fts_idx;
        CREATE INDEX source_anchors_text_fts_idx ON source_anchors
          USING GIN (to_tsvector('simple', text))
          WHERE rag_eligible;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX source_anchors_text_fts_idx;
        CREATE INDEX source_anchors_text_fts_idx ON source_anchors
          USING GIN (to_tsvector('simple', text));
        DROP TRIGGER source_anchor_rag_quality ON source_anchors;
        DROP FUNCTION enforce_source_anchor_rag_quality();
        ALTER TABLE source_anchors
          DROP CONSTRAINT source_anchor_rag_quality_consistent,
          DROP COLUMN rag_exclusion_reason,
          DROP COLUMN rag_eligible;
        DROP FUNCTION source_anchor_rag_exclusion_reason(TEXT, TEXT, DOUBLE PRECISION);
        """
    )
