"""Minimal PostgreSQL readiness probe for the disposable Phase 0 processes."""

from __future__ import annotations

import os
from typing import Final

import psycopg


DATABASE_URL_ENV: Final = "DATABASE_URL"


def database_is_ready() -> bool:
    """Return whether the configured database answers an exact ``SELECT 1``."""

    database_url = os.environ.get(DATABASE_URL_ENV)
    if not database_url:
        return False

    try:
        with psycopg.connect(database_url, connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                row = cursor.fetchone()
    except psycopg.Error:
        return False

    return row == (1,)
