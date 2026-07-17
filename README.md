# AXit Meeting RAG

Provenance-first meeting pre-briefing platform implemented in the dependency order
approved in `.omx/plans/ralplan-meeting-rag-platform.md`.

## Current gate

Phase 0's disposable Option A transport proof is green. The thin Next.js proxy,
FastAPI authority boundary, separate orchestrator, PostgreSQL health,
cookie/CSRF forwarding, bounded streaming 20 MiB upload, and citation-link
resolution are locked by 14 public-origin integration cases. The executable
evidence is recorded in `docs/phase0-option-a-proof.md`.

The active implementation gate is now Phase 1 G0: document-ingestion,
OCR-quality, and secretless sandbox feasibility. General product implementation
does not start unless that blocking spike passes.

The current provider experiment is offline. Coding agents curate deterministic
fixtures consumed later by `MockProvider`; they are not runtime providers and the
fixtures are not evidence of Grok compatibility or external truth.

## Toolchain

- Node.js `22.17.0` (`.nvmrc`)
- pnpm `11.4.0` (`packageManager`)
- Python `3.12.11` (`.python-version`)
- uv `0.11.29` for the checked `uv.lock`
- Docker Compose with versioned base images

## Phase 0 commands

```text
corepack pnpm install --frozen-lockfile
uv sync --locked
docker compose config
docker compose up -d --build
uv run pytest -m phase0
```

Production authentication, business state, and document ingestion are deliberately
outside this disposable transport harness.
