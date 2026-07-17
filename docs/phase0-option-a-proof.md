# Phase 0 Option A transport proof

- **Status:** **GO — every Phase 0 Option A gate is green**
- **Recorded:** 2026-07-18 (Asia/Seoul)
- **Scope:** disposable transport harness only
- **Decision source:** `.omx/plans/ralplan-meeting-rag-platform.md:78-96,251-264`
- **Production auth evidence:** no

## Fixed toolchain

| Surface | Version | Rationale |
|---|---:|---|
| Node.js | 22.17.0 | Pinned LTS line above Next.js' documented Node 20.9 minimum |
| pnpm | 11.4.0 | Pinned package manager recorded in `packageManager` |
| Next.js | 16.2.10 | Pinned thin-shell framework dependency |
| Python | 3.12.11 | Pinned API/orchestrator runtime |
| uv | 0.11.29 | Pinned resolver used to create the checked universal lock |
| PostgreSQL | 17.6-alpine3.22 | Versioned disposable Phase 0 database image |

The lockfiles, not floating registry state, define the complete dependency graph.
The selected Next.js release supports App Router Route Handlers; the proxy must pass
the request `ReadableStream` directly and must not call `formData()`,
`arrayBuffer()`, or `text()` on upload bodies.

pnpm lifecycle execution is deny-by-default. The workspace allows build scripts
only for the reviewed Next.js transitive native packages `sharp` and
`unrs-resolver`; every other dependency remains blocked from lifecycle execution.

## Dedicated web owner capacity

- **Owner lane:** `/root/phase0_repo_explore`, reassigned as the dedicated web
  executor for this ultra-goal; it completed the Phase 0 web implementation and
  its independent pinned-toolchain verification.
- **Reserved responsibility:** `apps/web/**`, the Phase 3/4 source viewer, citation
  deep-link/highlight behavior, and Playwright E2E through the final demo gate.
- **Capacity boundary:** this lane does not own API/domain/parser implementation.
  Root retains integration and handoff responsibility if a fresh session replaces
  the current executor.

The role reservation survives an individual agent session: root must assign any
fresh coding-agent session that resumes this role the same exclusive `apps/web/**`,
viewer, and browser-E2E scope. It may not be replaced by a runtime Grok provider.

## Executable gate

| Evidence | Required result | Result |
|---|---|---|
| `docker compose config --quiet` | exit 0 | **PASS** |
| pinned API/orchestrator/web image builds | exit 0 | **PASS** |
| `docker compose up -d --force-recreate --no-build ... --wait` | all healthy | **PASS — 4/4 healthy** |
| API/orchestrator host publication | none | **PASS — Compose-internal only; direct `127.0.0.1:8000` unavailable** |
| public-origin, cookie, CSRF, Host/Origin, upload, citation suite | exit 0 | **PASS — 14/14** |
| host-only cookie set/rotation/forwarding and stale rejection | smoke pass | **PASS** |
| valid CSRF; untrusted login, missing token, forged Origin/Host rejected | smoke pass | **PASS** |
| exact 20 MiB file payload streamed byte-for-byte; +1 rejected | smoke pass | **PASS — byte count and SHA-256 exact** |
| chunked multipart without a declared bound | rejected before proxying | **PASS — HTTP 411** |
| mock citation link resolver preserves URL and records invocation | smoke pass | **PASS — exact 307 `Location` plus invocation readback** |
| pinned Node lint, typecheck, Vitest, and Next production build | exit 0 | **PASS — 6/6 unit tests and build** |
| identical `ReadableStream` plus `duplex: "half"` reaches `fetch` | unit pass | **PASS** |
| `uv lock --check`, Ruff, and strict mypy | exit 0 | **PASS** |
| baseline provider validator and non-integration tests | exit 0 | **PASS — validator; 44 tests and 19 subtests** |

### Commands and raw result summary

```text
docker compose config --quiet
# exit 0

docker compose build web
# pinned Node 22.17.0 / pnpm 11.4.0
# ESLint PASS; tsc PASS; Vitest 6/6 PASS; Next build PASS

docker compose build api
docker compose build orchestrator
docker compose up -d --force-recreate --no-build api orchestrator web --wait
docker compose ps
# postgres/api/orchestrator/web healthy; only web publishes a host port

uv run pytest tests/integration/test_phase0_transport.py -v
# 14 passed

uv lock --check
uv run ruff check apps/api tests tools
uv run mypy apps/api
uv run pytest -m "not integration and not e2e" -q
# Ruff PASS; strict mypy PASS; 44 passed, 14 deselected, 19 subtests passed

uv run python tools/validate_provider_fixtures.py
# PASS: provider fixtures are canonical and valid
```

The configured **20 MiB limit is the uploaded file payload**, not multipart
framing. The thin proxy admits a declared envelope of at most 21 MiB so framing
fits, passes the original `ReadableStream` without buffering, and rejects
multipart requests with no `Content-Length`. FastAPI remains authoritative for
the exact file-byte limit. API `/tmp` is a bounded 64 MiB tmpfs.

## Boundary

The `__phase0` session store is process-local and disposable. It demonstrates
cookie, header, body-stream, and resolver transport through the public Next origin;
it does not replace Phase 3's PostgreSQL-backed opaque-session rotation, CSRF,
authorization, or concurrency tests.

All required rows are green, so the conditional Option A choice is retained and
Phase 1 G0 may start. A later regression in any proof reopens the Option C
amendment gate instead of silently changing architecture.

## Primary documentation checked

- [Next.js installation and Node requirement](https://nextjs.org/docs/app/getting-started/installation)
- [Next.js Route Handlers](https://nextjs.org/docs/app/getting-started/route-handlers)
- [uv project and lockfile workflow](https://docs.astral.sh/uv/guides/projects/)
- [pnpm releases](https://github.com/pnpm/pnpm/releases)
