# ADR 0001: Use curated deterministic MockProvider fixtures during the provider experiment

- **Status:** Accepted (temporary experiment strategy)
- **Date:** 2026-07-17

## Context

The meeting pre-briefing RAG experiment needs repeatable provider-shaped outputs without an external provider, credentials, paid usage, or uploads of originals. The approved temporary override explicitly suspends xAI/Grok calls.

## Decision

Coding agents author reviewable, canonical JSON fixtures for `MockProvider`. Fixtures are development-time inputs only, are validated with Python's standard library, and record completed coding-agent cross-review, fixed schema and prompt versions, plus source/evidence hashes. The source pack uses immutable revision and typed anchor IDs; each anchor enumerates complete `atomic_quotes`, and accepted claims or summary support must select one of those spans exactly. Research and fact-check fixtures remain separate and must resolve normalized synthetic web-evidence records rather than embedding live-web fields.

The hashes have one definition each:

- `source_hash` is SHA-256 over canonical source-pack JSON excluding `metadata`.
- A web record's `evidence_hash` is SHA-256 over its canonical JSON excluding `metadata`.
- A research or accepted fact-check `evidence_hash` is SHA-256 over canonical JSON shaped exactly as `[{"evidence_hash":"sha256:...","web_evidence_id":"web-evidence-..."}]`, sorted by `web_evidence_id`.
- `snippet_hash` is SHA-256 over the canonical JSON string form of the synthetic statement.

Synthetic citations use reserved `https://fixtures.invalid/...` URLs. They exercise the production citation shape (`url`, `title`, `domain`, `accessed_at`, `snippet_hash`) without implying that a live web request occurred. The schemas use stable absolute identifiers below the reserved `https://schemas.fixtures.invalid/` namespace. The common schema's closed conditional family definitions document accepted summary items, normalized evidence, four-outcome research/fact-check records, and pre-research opinion exclusion; the standard-library validator remains the executable cross-document contract.

## Consequences

Fixtures provide a deterministic regression baseline, not evidence of Grok compatibility, production-model quality, or external truth. A future real adapter must normalize captured responses into the same internal schema and must not overwrite these fixtures automatically. Coding agents are authors and reviewers only—not runtime providers. No runtime provider dependency, API key, or network call is introduced by this decision.
