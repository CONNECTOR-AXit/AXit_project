# Frontend integration and gateway replacement proof

- Date: 2026-08-03
- Follow-up: 2026-08-10 owner-requested client-side Markdown export (no new
  server export API)
- Imported frontend: `CONNECTOR-AXit/AXit_project` commit
  `292ffedcb466b6f3c00976ee8e45f44086f82e9b`
- Public origin: `http://localhost:3000`
- Compose service: `web`
- Status: replacement proof passed; the disposable `apps/web` package was removed

## Implemented product mapping

The imported information architecture remains the visual source, while the
approved Meeting RAG domain remains the semantic source:

- a frontend project is a `TalkSession`;
- a room is the private collaboration and authorization container;
- project material is the current revision of each session submission;
- analysis starts when the host closes a session;
- processing is represented by the real aggregate state, not a fake percent;
- results keep participant-only summary separate from external research and
  fact-check output;
- generated output is read-only and participant citations resolve to the
  source viewer.

The frontend now uses the checked generated TypeScript DTOs from
`@axit/api-client` and a single same-origin runtime client. Unsafe requests
obtain a synchronizer CSRF token and keep credentials on the HttpOnly cookie
boundary.

## Backend additions required by the frontend

Four actor-scoped read projections were added without a migration or a new
`project` aggregate:

1. `GET /api/friend-requests`
2. `GET /api/rooms/{room_id}/members`
3. `GET /api/rooms/{room_id}/sessions`
4. `GET /api/sessions/{session_id}/submissions`

Room and session enumeration starts from the current active membership.
Nonmembers receive the existing hidden 404 behavior. Submission enumeration
returns only current revision metadata and author identity; it never exposes
raw text, storage keys, hashes, parser internals, or historical revisions.

## Removed misleading frontend behavior

The imported mock store and simulated query delays were deleted. The connected
surface does not advertise or simulate editor autosave, comments, versions,
billing, notifications, artificial analysis percentages, or realtime
collaboration. The separately gated Phase 4 file lane is now promoted: the
session workspace exposes a real document picker, multipart upload,
processing-state polling, and member-only original download. The current
merged-document surface additionally has a dependency-free client-side
Markdown export; it serializes the loaded document and does not add a server
export endpoint.

## Replacement transport evidence

The dependency-free Vite production gateway serves the built SPA and streams
`/api` to the internal FastAPI origin. It retains the existing public behavior:

- request-header allowlist and authoritative `X-AXit-Original-Host`;
- spoofed transport/identity header removal;
- hop-by-hop response-header removal;
- preservation of multiple `Set-Cookie` values;
- bounded 201 MiB multipart envelope protecting the 200 MiB input limit;
- static path traversal rejection and SPA fallback;
- safe 500/502 responses without upstream detail leakage.

Evidence:

- `node --test AXit_project-main_goal_frontend/server/*.test.mjs`: 26 passed
- `pytest tests/integration/test_phase0_transport.py -q`: 14 passed
- Compose services `api`, `orchestrator`, `postgres`, and `web`: healthy
- public `/health`: `{"service":"web","status":"ok"}`
- browser public-path smoke: register/login, room creation, TalkSession
  creation, and text submission succeeded through port 3000

On this Windows host, Compose Bake failed before building because Docker
Desktop placed the non-ASCII working path in an internal gRPC header. The same
Dockerfiles were built directly with `docker build`, tagged with the Compose
image names, and started with `docker compose up --no-build`. This is a local
Compose/Bake transport limitation, not an application build failure.

The supported Node range is intentionally pinned to the verified Node 22 line
(`>=22.17.0 <23`). Node 24.11 repeatedly terminated the Vite/Rolldown native
build after transformation on this Windows host; it is no longer advertised as
a supported local build runtime.

## Verification evidence

- Python unit/contract/integration/security/evaluation: 114 passed, including
  repeated four-way same-user login serialization with exactly one active session
- workspace API integration: 4 passed
- contract and workspace focused suite: 15 passed
- Ruff: passed
- mypy: passed
- generated OpenAPI/client freshness: passed
- root pnpm lint: passed without warnings
- root pnpm typecheck: passed
- pinned Node 22.17 root/frontend build: passed
- root pnpm test: gateway 18 passed; G0 browser viewer 5 passed; attestation 3 passed
- pinned Node 22.17.0 Docker frozen install and frontend production build: passed
- visual verdict, login at 1440x1000: 94/100
- visual verdict, authenticated session at 1440x1000: 91/100
- visual verdict, room invitation placement at 1440x1000: 93/100
- visual verdict, ready-revision optional exclusion at 1440x1000: 93/100
- executable Playwright public flow: register/login, room/session creation,
  submit/replace, non-ready mandatory exclusion, ready optional exclusion with
  exact close payload, close state, logout, and protected deep-link redirect passed

Screenshots and reproducible capture state are stored under
`.omx/artifacts/frontend-integration/` and
`.omx/state/frontend-integration/ralph-progress.json`.

`pnpm audit --prod --audit-level high` currently reports
`GHSA-qwww-vcr4-c8h2` through React Router 7.18.2. The reviewed advisory limits
the vulnerable path to unstable RSC APIs; this client is a browser SPA using
`createBrowserRouter` and contains no RSC action surface. The registry exposes
7.18.2 as the newest installable release in this environment while the advisory
names a future `>=8.3.0` patched line, so no compatible patched release can be
installed yet. The mechanical audit remains red under this documented
non-applicability exception and must be revisited when a patched release exists.

## Backend capabilities without a truthful frontend placement

No implemented user-facing Backend capability remains without a truthful
placement. Room admission is exposed to the room host beside the current member
list. Close-time revision review lists every current submission: non-ready
revisions are mandatorily excluded with an explicit reason, while ready revisions
remain included by default and may be intentionally excluded with a required
reason.

Infrastructure endpoints such as health and CSRF are consumed automatically
and are not user-facing features. Phase 4 file submission and member-only
original download are now placed in the session workspace: the active frontend sends
bounded multipart submissions and polls `uploaded/queued/extracting` into the
terminal `ready/failed` state. No implemented user-facing Backend capability
remains without a truthful placement.

File-promotion evidence covers real PDF, PNG, JPEG, HWP, and HWPX fixtures
reaching `ready` through short-lived G0 containers, exact original SHA-256
download round-trips, and a corrupt HWP reaching `failed` while its original
remains available to the room member. The public browser flow additionally
locks file selection, client validation, multipart upload, transient status,
attachment headers, and close-time exclusion behavior.

## Cleanup result and rollback

`apps/web`, its Next.js dependencies, workspace importer, and obsolete UI tests
were removed only after the replacement gateway passed the unchanged public
transport suite. The imported nested npm lock was also removed so the repo has
one pnpm lockfile. Reversible local backups live outside the repository under
the user's `.codex` backup directory; no runtime state, credentials, caches, or
build output is committed.
