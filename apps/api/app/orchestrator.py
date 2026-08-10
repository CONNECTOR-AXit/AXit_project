"""Health probe plus fenced generation and automatic-suggestion workers.

``FencedExtractionRunner`` remains an injected Phase 2 harness: Phase 3 does
not promote its local IPC adapter to a production parser sandbox.  This CLI
polls fixture-backed generation jobs and deterministic report-comparison jobs.
Both persist effects through the durable queue's fencing CAS.
"""

from __future__ import annotations

import argparse
import os
import threading
import time
from collections.abc import Callable, Sequence
from typing import Final, Literal, Never, cast

from app.db import database_is_ready, open_connection
from app.automatic_report_suggestions import (
    AutomaticSuggestionRunner,
    FencedAutomaticSuggestionWorker,
)
from app.generation_provider import CallbackGenerationProvider, GenerationProvider, GroundedResearch
from app.generation_runner import GenerationRunner
from app.generation_worker import FencedGenerationWorker
from app.grok_provider import GrokProvider, XaiResponsesTransport
from app.grok_research_provider import GrokResearchProvider
from app.grok_report_provider import GrokReportProvider
from app.provider_errors import GenerationProviderFailure
from app.orchestrator_runner import FencedExtractionRunner


_DEFAULT_GROK_MODEL: Final = "grok-4.5"


_POLL_SECONDS: Final = 0.25
_GENERATION_LEASE_SECONDS: Final = 900
__all__ = [
    "FencedAutomaticSuggestionWorker",
    "FencedExtractionRunner",
    "FencedGenerationWorker",
    "main",
]


def _healthcheck_requested(argv: Sequence[str] | None) -> bool:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="exit zero only when DATABASE_URL answers SELECT 1",
    )
    arguments = parser.parse_args(argv)
    return bool(arguments.healthcheck)


def _generation_runner() -> GenerationRunner:
    """Build a fail-closed provider: production never falls back to fixtures.

    The owner-approved full report pipeline permits both live Grok summary and
    research generation. Missing credentials still fail closed instead of
    silently producing a MockProvider or offline report.
    """

    api_key = os.environ.get("XAI_API_KEY", "").strip()
    if not api_key:
        unavailable = CallbackGenerationProvider(
            provider="grok",
            model=_DEFAULT_GROK_MODEL,
            prompt_version="grok-fail-closed-v1",
            summary_generator=_grok_key_missing,
            research_generator=_grok_key_missing,
        )
        return GenerationRunner(provider=cast(GenerationProvider, unavailable))
    model = os.environ.get("GROK_MODEL", _DEFAULT_GROK_MODEL).strip() or _DEFAULT_GROK_MODEL
    transport = XaiResponsesTransport(
        api_key_supplier=lambda: api_key, enabled=True, timeout_seconds=180.0
    )
    grok_research = GrokResearchProvider(transport=transport, model=model)
    grok_summary = GrokProvider(transport=transport, model=model)
    hybrid = CallbackGenerationProvider(
        provider="grok",
        model=model,
        prompt_version=grok_research.prompt_version,
        summary_generator=grok_summary.generate_summary,
        research_generator=cast(
            Callable[..., GroundedResearch], grok_research.generate_research
        ),
    )
    return GenerationRunner(provider=cast(GenerationProvider, hybrid))


def _grok_key_missing(*args: object, **kwargs: object) -> Never:
    del args, kwargs
    raise GenerationProviderFailure("grok_api_key_missing", retryable=True)


class _UnavailableReportProvider:
    def generate(self, **kwargs: object) -> Never:
        del kwargs
        raise GenerationProviderFailure("grok_api_key_missing", retryable=True)


def _automatic_suggestion_runner() -> AutomaticSuggestionRunner:
    """Build the full report pipeline without any offline fallback."""

    api_key = os.environ.get("XAI_API_KEY", "").strip()
    if not api_key:
        return AutomaticSuggestionRunner(provider=_UnavailableReportProvider())
    model = os.environ.get("GROK_MODEL", _DEFAULT_GROK_MODEL).strip() or _DEFAULT_GROK_MODEL
    transport = XaiResponsesTransport(
        api_key_supplier=lambda: api_key, enabled=True, timeout_seconds=90.0
    )
    return AutomaticSuggestionRunner(
        provider=GrokReportProvider(transport=transport, model=model)
    )


def _run_generation_lane(kind: Literal["summary", "research"], owner: str) -> None:
    """Continuously process exactly one generation kind in its own lane."""

    worker = FencedGenerationWorker(
        connection_factory=open_connection, runner=_generation_runner()
    )
    while True:
        outcome = worker.run_once(
            owner=owner,
            kinds=(kind,),
            lease_seconds=_GENERATION_LEASE_SECONDS,
        )
        if not outcome.claimed:
            time.sleep(_POLL_SECONDS)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the local Phase 3 generation worker or its one-shot healthcheck."""

    if _healthcheck_requested(argv):
        return 0 if database_is_ready() else 1

    if not database_is_ready():
        return 1

    suggestion_worker = FencedAutomaticSuggestionWorker(
        connection_factory=open_connection,
        runner=_automatic_suggestion_runner(),
    )
    owner = f"orchestrator-{os.getpid()}"
    generation_threads = tuple(
        threading.Thread(
            target=_run_generation_lane,
            args=(kind, f"{owner}-{kind}"),
            name=f"generation-{kind}",
            daemon=True,
        )
        for kind in ("summary", "research")
    )
    for thread in generation_threads:
        thread.start()
    try:
        while True:
            # Draft, per-claim RAG finalization, and editor review are three
            # sequential live calls. Keep the fenced lease long enough for
            # their configured provider timeouts instead of allowing a valid
            # completion to become stale after the old 60-second default.
            suggestion_outcome = suggestion_worker.run_once(
                owner=owner,
                lease_seconds=_GENERATION_LEASE_SECONDS,
            )
            if not all(thread.is_alive() for thread in generation_threads):
                return 1
            if not suggestion_outcome.claimed:
                time.sleep(_POLL_SECONDS)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
