"""Phase 0 process health probe and Phase 2 runner entry surface.

``FencedExtractionRunner`` owns the Phase 2 claim -> adapter -> fenced
completion protocol.  This CLI intentionally remains an idle/health process
until Phase 3 supplies the durable source loader and separately approved G0
container launcher; it must not promote the local IPC adapter into a runtime
sandbox by accident.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from typing import Final

from app.db import database_is_ready
from app.orchestrator_runner import FencedExtractionRunner


_IDLE_SECONDS: Final = 60.0

__all__ = ["FencedExtractionRunner", "main"]


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
