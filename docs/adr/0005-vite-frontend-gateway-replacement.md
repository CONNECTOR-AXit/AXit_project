# ADR 0005: replace the disposable Next shell with the owner-provided Vite frontend

- Status: accepted by project-owner chat instruction
- Date: 2026-08-03
- Supersedes: the framework-specific portion of Phase 0 Option A
- Preserves: the Option A same-origin transport and security behavior

## Context

The project owner supplied `https://github.com/CONNECTOR-AXit/AXit_project` and
directed that its `Frontend` application become the frontend source of truth.
The imported baseline is commit
`292ffedcb466b6f3c00976ee8e45f44086f82e9b` from `origin/main`.
The existing `apps/web` package was created as a disposable transport and thin
vertical-slice harness.  It cannot remain as a competing user interface.

`apps/web` also owns a proof-critical streaming `/api` proxy.  Removing it
without a replacement would expose the API, break HttpOnly-cookie same-origin
semantics, and invalidate the 20 MiB upload and header-spoofing proof.

## Decision

1. Keep the owner-provided React/Vite information architecture and visual
   components in `Frontend`.
2. Add a dependency-free Node production gateway beside that application.  It
   serves the Vite build, retains the public port `3000`, and proxies `/api`
   streams to the internal FastAPI origin with the existing allowlist,
   multipart-envelope, cookie, and hop-by-hop-header rules.
3. Preserve `tests/integration/test_phase0_transport.py` behavior and port the
   old proxy unit tests before deleting `apps/web`.
4. Use the Meeting RAG contract as the backend semantic source of truth while
   adapting it to the frontend's existing pages.  UI affordances that imply
   explicit non-goals (export, real-time collaboration, completed chat) are
   removed rather than backed by new APIs.
5. The historical `docs/phase0-option-a-proof.md` remains unchanged.  A new
   migration proof will record the Vite gateway results.

## Rejected alternatives

- Keep both user interfaces: rejected because it creates two product sources
  of truth and violates the owner's removal instruction.
- Use only Vite's development proxy: rejected because it is not the deployed
  same-origin boundary and does not preserve the production transport proof.
- Publish FastAPI directly and enable CORS: rejected because browser-readable
  credentials and a broader cross-origin trust surface conflict with the
  approved cookie/CSRF design.
- Implement frontend export and real-time editing APIs: rejected because they
  are explicit first-milestone non-goals.

## Consequences

- `Frontend` becomes a root pnpm workspace package and Docker build target.
- The public service remains named `web` in Compose for black-box compatibility.
- The API and orchestrator remain internal-only.
- Removing `apps/web` is gated by equivalent unit, build, and transport proof.
- Backend capabilities with no truthful placement are reported after the
  integration pass instead of being hidden in unrelated UI.
