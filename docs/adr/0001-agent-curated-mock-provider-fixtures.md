# ADR 0001: Use curated deterministic MockProvider fixtures during the provider experiment

- **Status:** Accepted (temporary experiment strategy)
- **Date:** 2026-07-17

## Context

The meeting pre-briefing RAG experiment needs repeatable provider-shaped outputs without an external provider, credentials, paid usage, or uploads of originals. The approved temporary override explicitly suspends xAI/Grok calls.

## Decision

Coding agents author reviewable, canonical JSON fixtures for `MockProvider`. Fixtures are development-time inputs only, are validated with Python's standard library, and record author/reviewer roles, fixed schema and prompt versions, plus source/evidence hashes. The source pack uses immutable revision and anchor IDs; summary fixtures may cite only exact participant anchors. Research and fact-check fixtures remain separate and must resolve synthetic web-evidence IDs.

## Consequences

Fixtures provide a deterministic regression baseline, not evidence of Grok compatibility, production-model quality, or external truth. A future real adapter must normalize captured responses into the same internal schema and must not overwrite these fixtures automatically. No runtime provider dependency, API key, or network call is introduced by this decision.
