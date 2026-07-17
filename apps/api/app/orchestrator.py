"""Disposable Phase 0 orchestrator process and database health probe.

The process intentionally performs no production job orchestration. Its only
purpose is to prove that API and orchestrator are separate processes sharing
the same Python package while both can reach PostgreSQL.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from typing import Final

from app.db import database_is_ready


_IDLE_SECONDS: Final = 60.0


def _healthcheck_requested(argv: Sequence[str] | None) -> bool:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="exit zero only when DATABASE_URL answers SELECT 1",
    )
    arguments = parser.parse_args(argv)
    return bool(arguments.healthcheck)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the idle proof process or its one-shot healthcheck."""

    if _healthcheck_requested(argv):
        return 0 if database_is_ready() else 1

    if not database_is_ready():
        return 1

    try:
        while True:
            time.sleep(_IDLE_SECONDS)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
