# ADR 0003: Freeze the provenance and fenced-queue durable core

- Status: accepted
- Date: 2026-07-18
- Phase: 2 — contract freeze + minimal durable core

> Scope update (2026-08-10): the offline-provider paragraph below records the
> Phase 2 decision at that time. The approved full Grok report amendment now
> governs production provider use without changing this ADR's provenance and
> fencing decisions.

## Context

The Phase 1 document-ingestion G0 gate is clean GO. The next dependency gate
requires a durable PostgreSQL model for immutable source provenance, a single
canonical close/snapshot transaction, and worker fencing before product routes
or provider behavior are implemented.

The temporary provider experiment is offline. Agent-authored source-grounded
fixtures remain development-time inputs to a future `MockProvider`; they are
not a network service and do not establish Grok compatibility.

## Decision

1. Use Alembic `1.18.5` with SQLAlchemy `2.0.51` only to run pinned PostgreSQL
   migrations. Runtime repositories use `psycopg` SQL directly; we deliberately
   do not introduce an ORM, Celery, Redis, a vector database, or a new runtime
   service.
2. Store source/revision/extraction/anchor provenance append-only. Runtime
   anchor IDs are server-issued UUIDs. G0 and provider-fixture aliases cannot
   be persisted or returned as citation IDs.
3. Make the approved extraction run a same-revision composite foreign key and
    require it before a `ready` revision can be snapshotted. A close transaction
    locks the parent session, derives the pinned anchor-schema version from its
    approved runs, records audit exclusions, pins one epoch-1 snapshot, creates
    canonical summary/research runs and logical jobs, then exposes `processing`
    atomically.
4. Use at-least-once work with idempotent logical job keys and lease fencing.
   PostgreSQL clock-based `FOR UPDATE SKIP LOCKED` claims increment the lease
   generation; heartbeat and completion require the exact generation/token and
   reject elapsed leases. Canonical result write and completion CAS share one
   transaction, so stale workers roll back completely.
5. Freeze Pydantic/FastAPI contracts into generated OpenAPI, JSON Schemas, and
   TypeScript types. The full PRD route inventory is currently contract-only
   (`501`) until Phase 3 supplies durable handlers. The Phase 0 test harness
    remains hidden from OpenAPI and isolated under `/api/__phase0`.
6. Use PostgreSQL constraint triggers for ancestry relations that cannot be
   represented by a simple foreign key: a snapshot revision/exclusion must
   belong to its session; a source-anchor citation or research claim must be
   pinned in its generation snapshot; summary documents cannot cite web
   evidence; and provenance parent links cannot be reparented.
7. Keep the Phase 2 extraction runner injection-only. It claims only extraction
   jobs, invokes a `SandboxAdapter` outside a database transaction, and fences
   its short completion transaction. Job payloads carry only revision ID,
   expected media type, and parser identity; they never carry raw bytes,
   storage keys, URLs, database settings, or credentials.

## Consequences

- Migrations are explicit (`python -m app.migrations upgrade`) and are never
  run by application import or the Phase 0 healthcheck.
- Source/anchor coordinates have typed wire schemas, while parser-side G0
  block types remain bounded strings so the proven PDF/HWP/OCR formats can be
  promoted without losing table/footnote detail.
- Generated files must be refreshed via `tools/generate_contracts.py`; the
  check mode is a blocking contract freshness test.
- The sandbox IPC harness is only a secretless bounded adapter. Promotion of
  the G0 container remains a separately controlled launcher decision. The
  local adapter performs best-effort process-tree cleanup and never returns
  parser-controlled failure payloads, but it is not a UID/network/cgroup/PID
  containment boundary; no Docker socket is mounted into API/orchestrator.
- Public web-evidence DTOs require an `http(s)` URL with a normalized hostname
  exactly matching `domain`; DB checks reject control characters and userinfo
  as a defensive floor. Resolver-time validation remains mandatory in Phase 3.
- The initially frozen anchor/citation DTOs are amended by ADR 0004 after a
  G0 round-trip check found that a lossy locator shape could not represent the
  proven HWP table/footnote payloads or provide a complete resolver deep link.

## Rejected alternatives

- **In-memory jobs or exactly-once execution:** cannot survive a worker crash
  or prove stale-token rejection.
- **A config-only extraction-run uniqueness constraint:** would block immutable
  retries with the same parser/configuration.
- **Fixture aliases as database anchor IDs:** would leak development fixture
  identity and violate opaque runtime provenance.
- **Adding business routes before the contract:** would make OpenAPI/client
  drift a later integration surprise.
