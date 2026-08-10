"""Add forward-only activity, notification, comment, and settings persistence."""

from alembic import op

revision = "0012_notification_audit"
down_revision = "0011_auto_report_suggestions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
    ALTER TABLE talk_sessions ADD COLUMN state_version INTEGER NOT NULL DEFAULT 0,
      ADD COLUMN retry_ordinal INTEGER NOT NULL DEFAULT 0,
      ADD CONSTRAINT talk_sessions_state_version_nonnegative CHECK (state_version >= 0),
      ADD CONSTRAINT talk_sessions_retry_ordinal_nonnegative CHECK (retry_ordinal >= 0);

    CREATE TABLE user_profiles (
      user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
      job_title TEXT NULL, language TEXT NOT NULL DEFAULT 'ko',
      profile_version INTEGER NOT NULL DEFAULT 0, preferences_version INTEGER NOT NULL DEFAULT 0,
      profile_updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
      preferences_updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
      CHECK (job_title IS NULL OR char_length(job_title) BETWEEN 1 AND 200),
      CHECK (language IN ('ko','en','ja')), CHECK (profile_version >= 0), CHECK (preferences_version >= 0)
    );
    INSERT INTO user_profiles(user_id) SELECT id FROM users ON CONFLICT DO NOTHING;

    CREATE TABLE notification_preferences (
      user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
      kind TEXT NOT NULL, channel TEXT NOT NULL, enabled BOOLEAN NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(user_id, kind, channel),
      CHECK (kind IN ('analysis_completed','mention','comment')),
      CHECK (channel IN ('in_app','email_intent'))
    );
    INSERT INTO notification_preferences(user_id,kind,channel,enabled)
    SELECT u.id,k.kind,c.channel,(c.channel='in_app') FROM users u
    CROSS JOIN (VALUES ('analysis_completed'),('mention'),('comment')) k(kind)
    CROSS JOIN (VALUES ('in_app'),('email_intent')) c(channel);

    CREATE TABLE comments (
      id UUID PRIMARY KEY, session_id UUID NOT NULL REFERENCES talk_sessions(id) ON DELETE RESTRICT,
      author_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT, client_request_id UUID NOT NULL,
      request_fingerprint TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, body TEXT NOT NULL,
      anchor_kind TEXT NULL, anchor_id UUID NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, deleted_at TIMESTAMPTZ NULL,
      UNIQUE(author_id, client_request_id), CHECK (version >= 1),
      CHECK ((deleted_at IS NULL AND char_length(body) BETWEEN 1 AND 5000)
          OR (deleted_at IS NOT NULL AND body='')),
      CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
      CHECK ((anchor_kind IS NULL AND anchor_id IS NULL) OR (anchor_kind IN ('report','generated_segment') AND anchor_id IS NOT NULL))
    );
    CREATE INDEX comments_session_created_index ON comments(session_id, created_at DESC, id DESC);
    CREATE TABLE comment_mentions (
      comment_id UUID NOT NULL REFERENCES comments(id) ON DELETE RESTRICT,
      user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
      mentioned_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(comment_id,user_id)
    );

    CREATE TABLE notifications (
      id UUID PRIMARY KEY, recipient_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
      kind TEXT NOT NULL, actor_id UUID NULL REFERENCES users(id) ON DELETE RESTRICT,
      resource_type TEXT NOT NULL, resource_id UUID NOT NULL, action_kind TEXT NOT NULL,
      title TEXT NOT NULL, body TEXT NOT NULL, dedupe_key TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, read_at TIMESTAMPTZ NULL,
      UNIQUE(recipient_id,dedupe_key),
      CHECK (kind IN ('friend_request','room_member_added','analysis_completed','mention','comment')),
      CHECK (resource_type IN ('friend_request','room','session','comment')),
      CHECK (action_kind IN ('respond_friend_request','open_room','open_session','open_comment','none')),
      CHECK (action_kind='none'
          OR (resource_type='friend_request' AND action_kind='respond_friend_request')
          OR (resource_type='room' AND action_kind='open_room')
          OR (resource_type='session' AND action_kind='open_session')
          OR (resource_type='comment' AND action_kind='open_comment')),
      CHECK (char_length(title) BETWEEN 1 AND 120), CHECK (char_length(body) BETWEEN 1 AND 240),
      CHECK (char_length(dedupe_key) BETWEEN 1 AND 256)
    );
    CREATE INDEX notifications_recipient_page_index ON notifications(recipient_id,created_at DESC,id DESC);
    CREATE TABLE email_outbox (
      id UUID PRIMARY KEY, recipient_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
      notification_kind TEXT NOT NULL, dedupe_key TEXT NOT NULL, template_key TEXT NOT NULL,
      template_data JSONB NOT NULL, status TEXT NOT NULL DEFAULT 'queued_local',
      created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(recipient_id,dedupe_key),
      CHECK (notification_kind IN ('analysis_completed','mention','comment')),
      CHECK (char_length(dedupe_key) BETWEEN 1 AND 256), CHECK (char_length(template_key) BETWEEN 1 AND 128),
      CHECK (status='queued_local'), CHECK (jsonb_typeof(template_data)='object'),
      CHECK (octet_length(template_data::text) <= 2048)
    );

    CREATE TABLE audit_ledger_metadata (
      singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK(singleton),
      coverage_started_at TIMESTAMPTZ NOT NULL, schema_version INTEGER NOT NULL CHECK(schema_version=1)
    );
    INSERT INTO audit_ledger_metadata(singleton,coverage_started_at,schema_version) VALUES(TRUE,clock_timestamp(),1);
    CREATE TABLE audit_events (
      id UUID PRIMARY KEY, event_key TEXT NOT NULL UNIQUE,
      ledger_sequence BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE NOT NULL,
      event_type TEXT NOT NULL, actor_id UUID NULL REFERENCES users(id) ON DELETE RESTRICT,
      scope_type TEXT NOT NULL, audience_user_id UUID NULL REFERENCES users(id) ON DELETE RESTRICT,
      room_id UUID NULL REFERENCES rooms(id) ON DELETE RESTRICT,
      session_id UUID NULL REFERENCES talk_sessions(id) ON DELETE RESTRICT,
      entity_type TEXT NOT NULL, entity_id UUID NOT NULL, metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
      schema_version INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
      CHECK (char_length(event_key) BETWEEN 1 AND 256), CHECK (schema_version=1),
      CHECK (event_type IN ('account.registered','profile.updated','notification_preferences.updated',
        'friendship.requested','friendship.accepted','friendship.rejected','room.created','room.member_added',
        'session.created','session.closed','session.retry_requested','session.processing','session.ready',
        'session.needs_attention','submission.created','submission.revised','source_revision.ready',
        'source_revision.failed','suggestion.created','suggestion.accepted','suggestion.rejected',
        'comment.created','comment.updated','comment.deleted')),
      CHECK (char_length(entity_type) BETWEEN 1 AND 32),
      CHECK (jsonb_typeof(metadata_json)='object'), CHECK (octet_length(metadata_json::text)<=4096),
      CHECK ((scope_type='personal' AND audience_user_id IS NOT NULL AND room_id IS NULL AND session_id IS NULL)
          OR (scope_type='room' AND audience_user_id IS NULL AND room_id IS NOT NULL AND session_id IS NULL)
          OR (scope_type='session' AND audience_user_id IS NULL AND room_id IS NOT NULL AND session_id IS NOT NULL))
    );
    CREATE INDEX audit_events_sequence_index ON audit_events(ledger_sequence DESC);
    CREATE INDEX audit_events_personal_sequence_index ON audit_events(scope_type,audience_user_id,ledger_sequence DESC);
    CREATE INDEX audit_events_room_sequence_index ON audit_events(scope_type,room_id,ledger_sequence DESC);
    CREATE INDEX audit_events_session_sequence_index ON audit_events(scope_type,session_id,ledger_sequence DESC);

    CREATE FUNCTION axit_reject_audit_mutation() RETURNS trigger AS $$ BEGIN
      RAISE EXCEPTION 'audit ledger is append-only' USING ERRCODE='55000'; END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER audit_events_reject_update BEFORE UPDATE ON audit_events FOR EACH ROW EXECUTE FUNCTION axit_reject_audit_mutation();
    CREATE TRIGGER audit_events_reject_delete BEFORE DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION axit_reject_audit_mutation();
    CREATE FUNCTION axit_reject_comment_delete() RETURNS trigger AS $$ BEGIN
      RAISE EXCEPTION 'comments require a tombstone' USING ERRCODE='55000'; END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER comments_reject_delete BEFORE DELETE ON comments FOR EACH ROW EXECUTE FUNCTION axit_reject_comment_delete();
    CREATE FUNCTION axit_assert_activity_ancestry() RETURNS trigger AS $$ BEGIN
      IF NEW.scope_type='session' AND NOT EXISTS(SELECT 1 FROM talk_sessions s WHERE s.id=NEW.session_id AND s.room_id=NEW.room_id) THEN
        RAISE EXCEPTION 'audit session must belong to room' USING ERRCODE='23514';
      END IF; RETURN NEW; END; $$ LANGUAGE plpgsql;
    CREATE CONSTRAINT TRIGGER audit_events_session_ancestry AFTER INSERT ON audit_events
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION axit_assert_activity_ancestry();
    CREATE FUNCTION axit_assert_comment_anchor() RETURNS trigger AS $$ BEGIN
      IF NEW.anchor_kind='report' AND NOT EXISTS(SELECT 1 FROM generation_snapshots gs WHERE gs.id=NEW.anchor_id AND gs.session_id=NEW.session_id) THEN
        RAISE EXCEPTION 'comment report anchor is outside session' USING ERRCODE='23514';
      ELSIF NEW.anchor_kind='generated_segment' AND NOT EXISTS(
        SELECT 1 FROM generated_segments seg JOIN generated_documents d ON d.id=seg.document_id
        JOIN generation_runs r ON r.id=d.run_id JOIN generation_snapshots gs ON gs.id=r.snapshot_id
        WHERE seg.id=NEW.anchor_id AND gs.session_id=NEW.session_id) THEN
        RAISE EXCEPTION 'comment segment anchor is outside session' USING ERRCODE='23514';
      END IF; RETURN NEW; END; $$ LANGUAGE plpgsql;
    CREATE CONSTRAINT TRIGGER comments_anchor_ancestry AFTER INSERT OR UPDATE OF anchor_kind,anchor_id,session_id ON comments
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION axit_assert_comment_anchor();
    CREATE FUNCTION axit_assert_comment_mention_membership() RETURNS trigger AS $$ BEGIN
      IF EXISTS(SELECT 1 FROM comments c WHERE c.id=NEW.comment_id AND c.author_id=NEW.user_id) THEN
        RAISE EXCEPTION 'comment author cannot mention self' USING ERRCODE='23514';
      ELSIF (SELECT count(*) FROM comment_mentions cm WHERE cm.comment_id=NEW.comment_id) > 20 THEN
        RAISE EXCEPTION 'comment mention limit exceeded' USING ERRCODE='23514';
      ELSIF NOT EXISTS(
        SELECT 1 FROM comments c JOIN talk_sessions s ON s.id=c.session_id
        JOIN room_memberships m ON m.room_id=s.room_id AND m.user_id=NEW.user_id AND m.left_at IS NULL
        WHERE c.id=NEW.comment_id) THEN
        RAISE EXCEPTION 'mentioned user must be a current session member' USING ERRCODE='23514';
      END IF; RETURN NEW; END; $$ LANGUAGE plpgsql;
    CREATE CONSTRAINT TRIGGER comment_mentions_require_membership AFTER INSERT ON comment_mentions
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION axit_assert_comment_mention_membership();
    CREATE FUNCTION axit_reject_comment_mention_update() RETURNS trigger AS $$ BEGIN
      RAISE EXCEPTION 'comment mention identities are immutable' USING ERRCODE='55000'; END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER comment_mentions_reject_update BEFORE UPDATE ON comment_mentions
      FOR EACH ROW EXECUTE FUNCTION axit_reject_comment_mention_update();

    INSERT INTO notifications(id,recipient_id,kind,actor_id,resource_type,resource_id,action_kind,title,body,dedupe_key,created_at)
    SELECT (substr(md5('friend-request:'||f.id::text),1,8)||'-'||substr(md5('friend-request:'||f.id::text),9,4)||'-4'||substr(md5('friend-request:'||f.id::text),14,3)||'-a'||substr(md5('friend-request:'||f.id::text),18,3)||'-'||substr(md5('friend-request:'||f.id::text),21,12))::uuid,
      f.addressee_id,'friend_request',f.requester_id,'friend_request',f.id,'respond_friend_request',
      '새 친구 요청','새 친구 요청이 도착했습니다.','friendship:'||f.id::text||chr(58)||'requested',f.created_at
    FROM friendships f WHERE f.status='pending' ON CONFLICT(recipient_id,dedupe_key) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE audit_events; DROP FUNCTION axit_reject_audit_mutation(); DROP FUNCTION axit_assert_activity_ancestry();
    DROP TABLE audit_ledger_metadata; DROP TABLE email_outbox; DROP TABLE notifications;
    DROP TABLE comment_mentions; DROP FUNCTION axit_assert_comment_mention_membership();
    DROP FUNCTION axit_reject_comment_mention_update();
    DROP TABLE comments; DROP FUNCTION axit_reject_comment_delete(); DROP FUNCTION axit_assert_comment_anchor();
    DROP TABLE notification_preferences; DROP TABLE user_profiles;
    ALTER TABLE talk_sessions DROP CONSTRAINT talk_sessions_state_version_nonnegative,
      DROP CONSTRAINT talk_sessions_retry_ordinal_nonnegative, DROP COLUMN state_version, DROP COLUMN retry_ordinal;
    """)
