"""Create the Phase 2 provenance, snapshot, and fenced queue core.

Revision ID: 0001_durable_core
Revises:
Create Date: 2026-07-18
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "0001_durable_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create append-only provenance rows and fenced job persistence."""

    op.execute(
        """
        CREATE TABLE users (
            id UUID PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (char_length(email) BETWEEN 3 AND 320),
            CHECK (char_length(display_name) BETWEEN 1 AND 200)
        );

        CREATE TABLE auth_sessions (
            id UUID PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            csrf_secret_hash TEXT NOT NULL,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            revoked_at TIMESTAMPTZ NULL
        );

        CREATE TABLE friendships (
            id UUID PRIMARY KEY,
            requester_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            addressee_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            status TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            responded_at TIMESTAMPTZ NULL,
            CHECK (requester_id <> addressee_id),
            CHECK (status IN ('pending', 'accepted', 'rejected'))
        );
        CREATE UNIQUE INDEX friendships_canonical_pair_unique
            ON friendships (LEAST(requester_id, addressee_id), GREATEST(requester_id, addressee_id));

        CREATE TABLE rooms (
            id UUID PRIMARY KEY,
            owner_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            name TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (char_length(name) BETWEEN 1 AND 240)
        );

        CREATE TABLE room_memberships (
            room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE RESTRICT,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            role TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            left_at TIMESTAMPTZ NULL,
            PRIMARY KEY (room_id, user_id),
            CHECK (role IN ('host', 'member'))
        );

        CREATE TABLE room_invitations (
            id UUID PRIMARY KEY,
            room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE RESTRICT,
            invitee_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            inviter_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            status TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            responded_at TIMESTAMPTZ NULL,
            UNIQUE (room_id, invitee_id),
            CHECK (status IN ('pending', 'accepted', 'rejected'))
        );

        CREATE TABLE talk_sessions (
            id UUID PRIMARY KEY,
            room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE RESTRICT,
            host_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            mode TEXT NOT NULL,
            topic TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            deadline TIMESTAMPTZ NULL,
            state TEXT NOT NULL,
            generation_epoch INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMPTZ NULL,
            CHECK (mode IN ('relay')),
            CHECK (state IN ('draft', 'open', 'closed', 'processing', 'ready', 'needs_attention')),
            CHECK (generation_epoch >= 0),
            CHECK (char_length(topic) BETWEEN 1 AND 500)
        );

        CREATE TABLE submissions (
            id UUID PRIMARY KEY,
            session_id UUID NOT NULL REFERENCES talk_sessions(id) ON DELETE RESTRICT,
            author_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            kind TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (kind IN ('text', 'file'))
        );
        CREATE INDEX submissions_session_id_index ON submissions (session_id);

        CREATE TABLE source_revisions (
            id UUID PRIMARY KEY,
            submission_id UUID NOT NULL REFERENCES submissions(id) ON DELETE RESTRICT,
            revision_no INTEGER NOT NULL,
            filename TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            byte_size BIGINT NOT NULL,
            sha256 TEXT NOT NULL,
            storage_key TEXT NULL UNIQUE,
            source_text TEXT NULL,
            processing_state TEXT NOT NULL,
            approved_extraction_run_id UUID NULL,
            is_current BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (revision_no >= 1),
            CHECK (byte_size >= 0 AND byte_size <= 20971520),
            CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            CHECK (processing_state IN ('uploaded', 'queued', 'extracting', 'ready', 'failed')),
            UNIQUE (submission_id, revision_no)
        );
        CREATE UNIQUE INDEX source_revisions_one_current_per_submission
            ON source_revisions (submission_id) WHERE is_current;
        CREATE INDEX source_revisions_current_by_submission
            ON source_revisions (submission_id) WHERE is_current;
        CREATE INDEX source_revisions_submission_id_index
            ON source_revisions (submission_id);

        CREATE TABLE extraction_runs (
            id UUID PRIMARY KEY,
            source_revision_id UUID NOT NULL REFERENCES source_revisions(id) ON DELETE RESTRICT,
            parser_name TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            newline_policy TEXT NOT NULL,
            unicode_normalization_profile TEXT NOT NULL,
            config_hash TEXT NOT NULL,
            anchor_schema_version TEXT NOT NULL,
            attempt_no INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL,
            error_code TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMPTZ NULL,
            CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
            CHECK (attempt_no >= 1),
            CHECK (config_hash ~ '^[0-9a-f]{64}$'),
            UNIQUE (
                source_revision_id,
                parser_name,
                parser_version,
                newline_policy,
                unicode_normalization_profile,
                config_hash,
                anchor_schema_version,
                attempt_no
            ),
            UNIQUE (id, source_revision_id)
        );

        ALTER TABLE source_revisions
            ADD CONSTRAINT source_revisions_approved_run_same_revision_fk
            FOREIGN KEY (approved_extraction_run_id, id)
            REFERENCES extraction_runs (id, source_revision_id)
            ON DELETE RESTRICT;
        ALTER TABLE source_revisions
            ADD CONSTRAINT source_revisions_ready_requires_approved_run
            CHECK (
                processing_state <> 'ready'
                OR approved_extraction_run_id IS NOT NULL
            );

        CREATE TABLE source_anchors (
            id UUID PRIMARY KEY,
            extraction_run_id UUID NOT NULL,
            source_revision_id UUID NOT NULL,
            ordinal INTEGER NOT NULL,
            block_type TEXT NOT NULL,
            text TEXT NOT NULL,
            confidence DOUBLE PRECISION NULL,
            anchor_json JSONB NOT NULL,
            canonical_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (ordinal >= 0),
            CHECK (char_length(block_type) BETWEEN 1 AND 64),
            CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
            CHECK (canonical_hash ~ '^[0-9a-f]{64}$'),
            FOREIGN KEY (extraction_run_id, source_revision_id)
                REFERENCES extraction_runs (id, source_revision_id) ON DELETE RESTRICT,
            UNIQUE (extraction_run_id, ordinal),
            UNIQUE (extraction_run_id, canonical_hash)
        );

        CREATE TABLE snapshot_exclusions (
            id UUID PRIMARY KEY,
            session_id UUID NOT NULL REFERENCES talk_sessions(id) ON DELETE RESTRICT,
            source_revision_id UUID NOT NULL REFERENCES source_revisions(id) ON DELETE RESTRICT,
            reason TEXT NOT NULL,
            actor_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (session_id, source_revision_id),
            CHECK (char_length(reason) BETWEEN 1 AND 1000)
        );

        CREATE TABLE generation_snapshots (
            id UUID PRIMARY KEY,
            session_id UUID NOT NULL REFERENCES talk_sessions(id) ON DELETE RESTRICT,
            generation_epoch INTEGER NOT NULL,
            created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            topic_copy TEXT NOT NULL,
            pipeline_version TEXT NOT NULL,
            anchor_schema_version TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (session_id, generation_epoch),
            CHECK (generation_epoch >= 1)
        );

        CREATE TABLE snapshot_revisions (
            snapshot_id UUID NOT NULL REFERENCES generation_snapshots(id) ON DELETE RESTRICT,
            source_revision_id UUID NOT NULL,
            extraction_run_id UUID NOT NULL,
            PRIMARY KEY (snapshot_id, source_revision_id),
            FOREIGN KEY (extraction_run_id, source_revision_id)
                REFERENCES extraction_runs (id, source_revision_id) ON DELETE RESTRICT
        );

        CREATE TABLE jobs (
            id UUID PRIMARY KEY,
            logical_key TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            snapshot_id UUID NULL REFERENCES generation_snapshots(id) ON DELETE RESTRICT,
            payload_json JSONB NOT NULL,
            state TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            lease_generation INTEGER NOT NULL DEFAULT 0,
            lease_token UUID NULL,
            lease_owner TEXT NULL,
            lease_until TIMESTAMPTZ NULL,
            heartbeat_at TIMESTAMPTZ NULL,
            error_code TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (kind IN ('extraction', 'summary', 'research')),
            CHECK (state IN ('pending', 'running', 'succeeded', 'failed_retryable', 'failed_terminal')),
            CHECK (attempts >= 0),
            CHECK (lease_generation >= 0),
            CONSTRAINT jobs_running_lease_shape CHECK (
                (state = 'running' AND lease_token IS NOT NULL AND lease_owner IS NOT NULL AND lease_until IS NOT NULL)
                OR
                (state <> 'running' AND lease_token IS NULL AND lease_owner IS NULL AND lease_until IS NULL)
            ),
            CONSTRAINT jobs_failure_requires_error_code CHECK (
                (state IN ('failed_retryable', 'failed_terminal')
                    AND error_code IS NOT NULL
                    AND char_length(error_code) BETWEEN 1 AND 128)
                OR
                (state NOT IN ('failed_retryable', 'failed_terminal')
                    AND error_code IS NULL)
            )
        );
        CREATE INDEX jobs_claim_index ON jobs (state, lease_until, created_at);

        CREATE TABLE job_attempts (
            id UUID PRIMARY KEY,
            job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
            lease_generation INTEGER NOT NULL,
            lease_token UUID NOT NULL,
            owner TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMPTZ NULL,
            status TEXT NOT NULL,
            error_code TEXT NULL,
            CHECK (lease_generation >= 1),
            CHECK (status IN ('running', 'succeeded', 'failed', 'expired', 'stale')),
            CONSTRAINT job_attempts_failure_requires_error_code CHECK (
                (status IN ('failed', 'expired', 'stale')
                    AND error_code IS NOT NULL
                    AND char_length(error_code) BETWEEN 1 AND 128)
                OR
                (status IN ('running', 'succeeded') AND error_code IS NULL)
            ),
            UNIQUE (job_id, lease_generation)
        );

        CREATE TABLE job_results (
            id UUID PRIMARY KEY,
            job_id UUID NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE RESTRICT,
            result_json JSONB NOT NULL,
            result_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (result_hash ~ '^[0-9a-f]{64}$')
        );

        CREATE TABLE generation_runs (
            id UUID PRIMARY KEY,
            snapshot_id UUID NOT NULL REFERENCES generation_snapshots(id) ON DELETE RESTRICT,
            kind TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            pipeline_version TEXT NOT NULL,
            state TEXT NOT NULL,
            error_code TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMPTZ NULL,
            CHECK (kind IN ('summary', 'research')),
            CHECK (state IN ('queued', 'running', 'succeeded', 'failed_retryable', 'failed_terminal')),
            UNIQUE (snapshot_id, kind, pipeline_version)
        );

        CREATE TABLE generated_documents (
            id UUID PRIMARY KEY,
            run_id UUID NOT NULL UNIQUE REFERENCES generation_runs(id) ON DELETE RESTRICT,
            kind TEXT NOT NULL,
            structured_content_json JSONB NOT NULL,
            content_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (kind IN ('summary', 'research')),
            CHECK (content_hash ~ '^[0-9a-f]{64}$')
        );

        CREATE TABLE generated_segments (
            id UUID PRIMARY KEY,
            document_id UUID NOT NULL REFERENCES generated_documents(id) ON DELETE RESTRICT,
            ordinal INTEGER NOT NULL,
            text TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (document_id, ordinal),
            CHECK (ordinal >= 0)
        );

        CREATE TABLE web_evidence (
            id UUID PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            domain TEXT NOT NULL,
            accessed_at TIMESTAMPTZ NOT NULL,
            snippet_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT web_evidence_safe_http_url CHECK (url ~ '^https?://[^/@[:space:]]+'),
            CONSTRAINT web_evidence_no_userinfo CHECK (url !~ '^https?://[^/]*@'),
            CONSTRAINT web_evidence_no_control_chars CHECK (url !~ E'[\\r\\n]'),
            CHECK (snippet_hash ~ '^[0-9a-f]{64}$')
        );

        CREATE TABLE citations (
            id UUID PRIMARY KEY,
            segment_id UUID NOT NULL REFERENCES generated_segments(id) ON DELETE RESTRICT,
            target_type TEXT NOT NULL,
            source_anchor_id UUID NULL REFERENCES source_anchors(id) ON DELETE RESTRICT,
            web_evidence_id UUID NULL REFERENCES web_evidence(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (target_type IN ('source_anchor', 'web_evidence')),
            CHECK (
                (target_type = 'source_anchor' AND source_anchor_id IS NOT NULL AND web_evidence_id IS NULL)
                OR
                (target_type = 'web_evidence' AND web_evidence_id IS NOT NULL AND source_anchor_id IS NULL)
            )
        );

        CREATE TABLE research_claims (
            id UUID PRIMARY KEY,
            run_id UUID NOT NULL REFERENCES generation_runs(id) ON DELETE RESTRICT,
            claim_text TEXT NOT NULL,
            source_anchor_id UUID NOT NULL REFERENCES source_anchors(id) ON DELETE RESTRICT,
            verdict TEXT NOT NULL,
            explanation TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (verdict IN ('supported', 'refuted', 'mixed', 'unverifiable'))
        );

        -- A composite foreign key proves that an approved run belongs to its
        -- revision, but it cannot prove that the run actually succeeded.
        -- Both directions are guarded as deferred constraint triggers so an
        -- extraction worker may atomically mark its run succeeded and then
        -- approve the revision in either statement order, while a committed
        -- ready revision can never point at a queued/running/failed run.
        CREATE FUNCTION axit_assert_source_revision_approved_run_succeeded()
        RETURNS trigger AS $$
        DECLARE
            approved_status TEXT;
        BEGIN
            IF NEW.approved_extraction_run_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT status INTO approved_status
            FROM extraction_runs
            WHERE id = NEW.approved_extraction_run_id
              AND source_revision_id = NEW.id;

            IF approved_status IS DISTINCT FROM 'succeeded' THEN
                RAISE EXCEPTION 'approved extraction run must have succeeded'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE CONSTRAINT TRIGGER source_revisions_approved_run_must_succeed
        AFTER INSERT OR UPDATE OF approved_extraction_run_id, processing_state ON source_revisions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION axit_assert_source_revision_approved_run_succeeded();

        CREATE FUNCTION axit_assert_approved_extraction_run_remains_succeeded()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.status IS DISTINCT FROM 'succeeded'
               AND EXISTS (
                   SELECT 1
                   FROM source_revisions
                   WHERE approved_extraction_run_id = NEW.id
               ) THEN
                RAISE EXCEPTION 'an approved extraction run must remain succeeded'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE CONSTRAINT TRIGGER extraction_runs_approved_run_must_remain_succeeded
        AFTER UPDATE OF status ON extraction_runs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION axit_assert_approved_extraction_run_remains_succeeded();

        -- PostgreSQL cannot express these ancestry joins with a conventional
        -- foreign key.  Constraint triggers keep private revision/anchor
        -- provenance inside the owning generation snapshot even when a future
        -- repository writer bypasses the service layer.
        CREATE FUNCTION axit_assert_snapshot_revision_session()
        RETURNS trigger AS $$
        DECLARE
            snapshot_session UUID;
            revision_session UUID;
        BEGIN
            SELECT snapshot.session_id INTO snapshot_session
            FROM generation_snapshots AS snapshot
            WHERE snapshot.id = NEW.snapshot_id;

            SELECT submission.session_id INTO revision_session
            FROM source_revisions AS revision
            JOIN submissions AS submission ON submission.id = revision.submission_id
            WHERE revision.id = NEW.source_revision_id;

            IF snapshot_session IS NULL
               OR revision_session IS NULL
               OR snapshot_session <> revision_session THEN
                RAISE EXCEPTION 'snapshot revision must belong to the snapshot session'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE CONSTRAINT TRIGGER snapshot_revisions_session_ownership
        AFTER INSERT OR UPDATE ON snapshot_revisions
        DEFERRABLE INITIALLY IMMEDIATE
        FOR EACH ROW EXECUTE FUNCTION axit_assert_snapshot_revision_session();

        CREATE FUNCTION axit_assert_snapshot_exclusion_session()
        RETURNS trigger AS $$
        DECLARE
            revision_session UUID;
        BEGIN
            SELECT submission.session_id INTO revision_session
            FROM source_revisions AS revision
            JOIN submissions AS submission ON submission.id = revision.submission_id
            WHERE revision.id = NEW.source_revision_id;

            IF revision_session IS NULL OR revision_session <> NEW.session_id THEN
                RAISE EXCEPTION 'snapshot exclusion revision must belong to its session'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE CONSTRAINT TRIGGER snapshot_exclusions_session_ownership
        AFTER INSERT OR UPDATE ON snapshot_exclusions
        DEFERRABLE INITIALLY IMMEDIATE
        FOR EACH ROW EXECUTE FUNCTION axit_assert_snapshot_exclusion_session();

        CREATE FUNCTION axit_assert_generated_document_kind()
        RETURNS trigger AS $$
        DECLARE
            run_kind TEXT;
        BEGIN
            SELECT kind INTO run_kind
            FROM generation_runs
            WHERE id = NEW.run_id;

            IF run_kind IS NULL OR run_kind <> NEW.kind THEN
                RAISE EXCEPTION 'generated document kind must match its generation run'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE CONSTRAINT TRIGGER generated_documents_kind_matches_run
        AFTER INSERT OR UPDATE ON generated_documents
        DEFERRABLE INITIALLY IMMEDIATE
        FOR EACH ROW EXECUTE FUNCTION axit_assert_generated_document_kind();

        CREATE FUNCTION axit_assert_citation_snapshot_provenance()
        RETURNS trigger AS $$
        DECLARE
            document_kind TEXT;
        BEGIN
            SELECT document.kind INTO document_kind
            FROM generated_segments AS segment
            JOIN generated_documents AS document ON document.id = segment.document_id
            WHERE segment.id = NEW.segment_id;

            IF document_kind IS NULL THEN
                RAISE EXCEPTION 'citation segment must belong to a generated document'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.target_type = 'web_evidence' THEN
                IF document_kind = 'summary' THEN
                    RAISE EXCEPTION 'summary documents cannot cite web evidence'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM generated_segments AS segment
                JOIN generated_documents AS document ON document.id = segment.document_id
                JOIN generation_runs AS run ON run.id = document.run_id
                JOIN snapshot_revisions AS snapshot_revision
                  ON snapshot_revision.snapshot_id = run.snapshot_id
                JOIN source_anchors AS anchor
                  ON anchor.id = NEW.source_anchor_id
                 AND anchor.source_revision_id = snapshot_revision.source_revision_id
                 AND anchor.extraction_run_id = snapshot_revision.extraction_run_id
                WHERE segment.id = NEW.segment_id
            ) THEN
                RAISE EXCEPTION 'source-anchor citation must belong to the segment snapshot'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE CONSTRAINT TRIGGER citations_snapshot_provenance
        AFTER INSERT OR UPDATE ON citations
        DEFERRABLE INITIALLY IMMEDIATE
        FOR EACH ROW EXECUTE FUNCTION axit_assert_citation_snapshot_provenance();

        CREATE FUNCTION axit_assert_research_claim_snapshot_provenance()
        RETURNS trigger AS $$
        DECLARE
            run_kind TEXT;
        BEGIN
            SELECT kind INTO run_kind
            FROM generation_runs
            WHERE id = NEW.run_id;

            IF run_kind IS DISTINCT FROM 'research' THEN
                RAISE EXCEPTION 'research claims must belong to research generation runs'
                    USING ERRCODE = '23514';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM generation_runs AS run
                JOIN snapshot_revisions AS snapshot_revision
                  ON snapshot_revision.snapshot_id = run.snapshot_id
                JOIN source_anchors AS anchor
                  ON anchor.id = NEW.source_anchor_id
                 AND anchor.source_revision_id = snapshot_revision.source_revision_id
                 AND anchor.extraction_run_id = snapshot_revision.extraction_run_id
                WHERE run.id = NEW.run_id
            ) THEN
                RAISE EXCEPTION 'research claim anchor must belong to the run snapshot'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE CONSTRAINT TRIGGER research_claims_snapshot_provenance
        AFTER INSERT OR UPDATE ON research_claims
        DEFERRABLE INITIALLY IMMEDIATE
        FOR EACH ROW EXECUTE FUNCTION axit_assert_research_claim_snapshot_provenance();

        CREATE FUNCTION axit_reject_provenance_link_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% provenance parent links are immutable', TG_TABLE_NAME
                USING ERRCODE = '23514';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER submissions_session_link_immutable
        BEFORE UPDATE OF session_id ON submissions
        FOR EACH ROW EXECUTE FUNCTION axit_reject_provenance_link_update();
        CREATE TRIGGER source_revisions_submission_link_immutable
        BEFORE UPDATE OF submission_id ON source_revisions
        FOR EACH ROW EXECUTE FUNCTION axit_reject_provenance_link_update();
        CREATE TRIGGER extraction_runs_revision_link_immutable
        BEFORE UPDATE OF source_revision_id ON extraction_runs
        FOR EACH ROW EXECUTE FUNCTION axit_reject_provenance_link_update();
        CREATE TRIGGER source_anchors_run_link_immutable
        BEFORE UPDATE OF extraction_run_id, source_revision_id ON source_anchors
        FOR EACH ROW EXECUTE FUNCTION axit_reject_provenance_link_update();
        CREATE TRIGGER generation_snapshots_session_link_immutable
        BEFORE UPDATE OF session_id ON generation_snapshots
        FOR EACH ROW EXECUTE FUNCTION axit_reject_provenance_link_update();
        CREATE TRIGGER snapshot_revisions_links_immutable
        BEFORE UPDATE OF snapshot_id, source_revision_id, extraction_run_id ON snapshot_revisions
        FOR EACH ROW EXECUTE FUNCTION axit_reject_provenance_link_update();
        CREATE TRIGGER snapshot_exclusions_links_immutable
        BEFORE UPDATE OF session_id, source_revision_id ON snapshot_exclusions
        FOR EACH ROW EXECUTE FUNCTION axit_reject_provenance_link_update();
        CREATE TRIGGER generation_runs_snapshot_link_immutable
        BEFORE UPDATE OF snapshot_id ON generation_runs
        FOR EACH ROW EXECUTE FUNCTION axit_reject_provenance_link_update();
        CREATE TRIGGER generated_documents_run_link_immutable
        BEFORE UPDATE OF run_id ON generated_documents
        FOR EACH ROW EXECUTE FUNCTION axit_reject_provenance_link_update();
        CREATE TRIGGER generated_segments_document_link_immutable
        BEFORE UPDATE OF document_id ON generated_segments
        FOR EACH ROW EXECUTE FUNCTION axit_reject_provenance_link_update();
        """
    )


def downgrade() -> None:
    """Remove the Phase 2 schema in dependency-safe reverse order."""

    op.execute(
        """
        DROP TABLE research_claims;
        DROP TABLE citations;
        DROP TABLE web_evidence;
        DROP TABLE generated_segments;
        DROP TABLE generated_documents;
        DROP TABLE generation_runs;
        DROP TABLE job_results;
        DROP TABLE job_attempts;
        DROP TABLE jobs;
        DROP TABLE snapshot_revisions;
        DROP TABLE generation_snapshots;
        DROP TABLE snapshot_exclusions;
        DROP TABLE source_anchors;
        ALTER TABLE source_revisions
            DROP CONSTRAINT source_revisions_approved_run_same_revision_fk;
        DROP TABLE extraction_runs;
        DROP INDEX source_revisions_current_by_submission;
        DROP INDEX source_revisions_one_current_per_submission;
        DROP INDEX source_revisions_submission_id_index;
        DROP TABLE source_revisions;
        DROP TABLE submissions;
        DROP TABLE talk_sessions;
        DROP TABLE room_invitations;
        DROP TABLE room_memberships;
        DROP TABLE rooms;
        DROP INDEX friendships_canonical_pair_unique;
        DROP TABLE friendships;
        DROP TABLE auth_sessions;
        DROP TABLE users;
        DROP FUNCTION axit_assert_approved_extraction_run_remains_succeeded();
        DROP FUNCTION axit_assert_source_revision_approved_run_succeeded();
        DROP FUNCTION axit_reject_provenance_link_update();
        DROP FUNCTION axit_assert_research_claim_snapshot_provenance();
        DROP FUNCTION axit_assert_citation_snapshot_provenance();
        DROP FUNCTION axit_assert_generated_document_kind();
        DROP FUNCTION axit_assert_snapshot_exclusion_session();
        DROP FUNCTION axit_assert_snapshot_revision_session();
        """
    )
