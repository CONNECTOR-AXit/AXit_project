"""Programmatic and CLI-safe Alembic entry point for tests and local runs."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.db import configured_database_url


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = _REPOSITORY_ROOT / "alembic.ini"
_ALEMBIC_SCRIPTS = _REPOSITORY_ROOT / "apps" / "api" / "alembic"
_API_IMPORT_ROOT = _REPOSITORY_ROOT / "apps" / "api"


def alembic_config(database_url: str) -> Config:
    """Build a cwd-independent config without writing credentials to disk."""

    config = Config(str(_ALEMBIC_INI))
    # Alembic resolves a relative ``script_location`` against the process
    # working directory.  API containers run from ``/workspace/apps/api``;
    # pin these repository locations so the one-shot migration service and
    # local test runner execute the exact same revision tree.
    config.set_main_option("script_location", str(_ALEMBIC_SCRIPTS))
    config.set_main_option("prepend_sys_path", str(_API_IMPORT_ROOT))
    config.attributes["database_url"] = database_url
    return config


def upgrade_database(database_url: str, revision: str = "head") -> None:
    """Upgrade one database to the requested Alembic revision."""

    command.upgrade(alembic_config(database_url), revision)


def downgrade_database(database_url: str, revision: str = "base") -> None:
    """Downgrade one database to the requested Alembic revision."""

    command.downgrade(alembic_config(database_url), revision)


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``upgrade`` or ``downgrade`` using ``DATABASE_URL``."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("upgrade", "downgrade"))
    parser.add_argument("--revision", default=None)
    arguments = parser.parse_args(argv)
    database_url = configured_database_url()
    if arguments.action == "upgrade":
        upgrade_database(database_url, arguments.revision or "head")
    else:
        downgrade_database(database_url, arguments.revision or "base")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
