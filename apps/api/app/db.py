"""PostgreSQL connection helpers shared by the API and orchestrator.

The Phase 0 readiness probe remains intentionally small, but Phase 2 needs a
single, explicit connection boundary for migrations and durable queue work.
No caller should log a database URL: it can contain a password in local
development too.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row


DATABASE_URL_ENV: Final = "DATABASE_URL"


def configured_database_url() -> str:
    """Return the configured PostgreSQL URL or fail before any DB work."""

    database_url = os.environ.get(DATABASE_URL_ENV)
    if not database_url:
        raise RuntimeError(f"{DATABASE_URL_ENV} must be configured")
    return database_url


@contextmanager
def open_connection(
    database_url: str | None = None,
) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """Open a transaction-capable dictionary-row PostgreSQL connection."""

    resolved_url = database_url or configured_database_url()
    with psycopg.connect(resolved_url, row_factory=dict_row) as connection:
        yield connection


def database_is_ready() -> bool:
    """Return whether the configured database answers an exact ``SELECT 1``."""

    try:
        database_url = configured_database_url()
    except RuntimeError:
        return False

    try:
        with psycopg.connect(database_url, connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                row = cursor.fetchone()
    except psycopg.Error:
        return False

    return row == (1,)
