"""PostgreSQL acceptance skeleton for the notification/audit/settings schema.

The unconditional migration-presence test is the initial RED gate.  Database
tests remain collectable and skip only when the standard isolated PostgreSQL
URL is unavailable.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.migrations import downgrade_database, upgrade_database


pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps" / "api" / "alembic" / "versions" / "0012_notification_audit_settings.py"


def test_notification_audit_settings_migration_exists() -> None:
    assert MIGRATION.is_file(), (
        "G001 RED: 0012_notification_audit_settings.py is absent; schema work has not started"
    )


def test_friend_request_backfill_suffix_is_not_a_sqlalchemy_bind_parameter() -> None:
    spec = spec_from_file_location("notification_audit_settings_0012", MIGRATION)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    migration.op = Operations(context)
    migration.upgrade()

    compiled_sql = output.getvalue()
    assert "%(requested)s" not in compiled_sql
    assert "'friendship:'||f.id::text||chr(58)||'requested'" in compiled_sql


@contextmanager
def _temporary_database() -> Iterator[str]:
    configured_url = os.environ.get("AXIT_TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("AXIT_TEST_DATABASE_URL is required for isolated PostgreSQL integration")
    connection_info = conninfo_to_dict(configured_url)
    database_name = "axit_notification_audit_" + uuid4().hex
    maintenance_info = dict(connection_info)
    maintenance_info["dbname"] = "postgres"
    target_info = dict(connection_info)
    target_info["dbname"] = database_name
    target_url = make_conninfo(**target_info)
    with psycopg.connect(**maintenance_info, autocommit=True) as maintenance:
        maintenance.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        try:
            yield target_url
        finally:
            maintenance.execute(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            maintenance.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
            )


@pytest.fixture
def migrated_database_url() -> Iterator[str]:
    with _temporary_database() as database_url:
        upgrade_database(database_url)
        yield database_url


@pytest.mark.parametrize(
    "table_name",
    [
        "user_profiles",
        "notification_preferences",
        "comments",
        "comment_mentions",
        "notifications",
        "email_outbox",
        "audit_ledger_metadata",
        "audit_events",
    ],
)
def test_migration_creates_each_approved_durable_table(
    migrated_database_url: str,
    table_name: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        exists = connection.execute(
            "SELECT to_regclass(%s)", (f"public.{table_name}",)
        ).fetchone()
    assert exists is not None and exists[0] == table_name


def test_audit_ledger_uses_identity_sequence_and_rejects_update_delete(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        identity = connection.execute(
            """
            SELECT identity_generation, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'audit_events'
              AND column_name = 'ledger_sequence'
            """
        ).fetchone()
        trigger_names = {
            row[0]
            for row in connection.execute(
                """
                SELECT trigger_name
                FROM information_schema.triggers
                WHERE event_object_schema = 'public'
                  AND event_object_table = 'audit_events'
                  AND event_manipulation IN ('UPDATE', 'DELETE')
                """
            ).fetchall()
        }
    assert identity is not None
    assert identity[0] in {"ALWAYS", "BY DEFAULT"}
    assert identity[1] == "NO"
    assert trigger_names, "audit UPDATE/DELETE rejection trigger is absent"


def test_compound_ordering_is_backed_by_ledger_sequence_not_created_at(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        indexes = {
            row[0]: row[1]
            for row in connection.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = 'audit_events'
                """
            ).fetchall()
        }
    assert indexes
    assert any("ledger_sequence DESC" in definition for definition in indexes.values())
    assert not any(
        "created_at DESC" in definition and "ledger_sequence" not in definition
        for definition in indexes.values()
    )


def test_concurrent_replays_converge_through_database_unique_constraints(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(migrated_database_url) as connection:
        index_definitions = [
            row[0]
            for row in connection.execute(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename IN ('comments', 'notifications', 'email_outbox', 'audit_events')
                  AND indexdef LIKE 'CREATE UNIQUE INDEX%'
                """
            ).fetchall()
        ]
    definitions = "\n".join(index_definitions)
    assert "author_id, client_request_id" in definitions
    assert definitions.count("recipient_id, dedupe_key") >= 2
    assert "event_key" in definitions
    assert "ledger_sequence" in definitions


def test_guarded_disposable_database_can_downgrade_and_reupgrade() -> None:
    with _temporary_database() as database_url:
        assert os.environ.get("AXIT_ALLOW_DESTRUCTIVE_MIGRATION_TEST") == "1", (
            "AXIT_ALLOW_DESTRUCTIVE_MIGRATION_TEST=1 is required before running "
            "the disposable downgrade/re-up proof"
        )

        upgrade_database(database_url)
        downgrade_database(database_url, "0011_auto_report_suggestions")
        with psycopg.connect(database_url) as connection:
            downgraded_revision = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
            audit_events = connection.execute(
                "SELECT to_regclass('public.audit_events')"
            ).fetchone()

        assert downgraded_revision == ("0011_auto_report_suggestions",)
        assert audit_events == (None,)

        upgrade_database(database_url)
        with psycopg.connect(database_url) as connection:
            reupgraded_revision = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
            audit_events = connection.execute(
                "SELECT to_regclass('public.audit_events')"
            ).fetchone()

        assert reupgraded_revision == ("0012_notification_audit",)
        assert audit_events == ("audit_events",)
