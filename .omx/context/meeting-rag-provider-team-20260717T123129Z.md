# Team Context Snapshot — Coding Agents Substitute for Grok

## Task statement

Continue the approved meeting-RAG plan by starting an OMX Team now. For the
provider experiment only, new Codex coding-agent sessions substitute for the
work that Grok would otherwise produce.

## Desired outcome

Deliver Phase 0 through Phase 2 evidence with three fixed executor lanes:

1. repository/toolchain bootstrap and the disposable Option A transport proof;
2. blocking HWP/HWPX/PDF/OCR parser-sandbox G0 evidence;
3. agent-curated deterministic source/evidence packs, MockProvider fixtures,
   validators, and the provider decision record.

The run is terminal only with zero failed tasks and recorded verification.

## Authoritative inputs

- `.omx/plans/ralplan-meeting-rag-platform.md`
- `.omx/plans/prd-meeting-rag-platform.md`
- `.omx/plans/test-spec-meeting-rag-platform.md`
- `.omx/plans/provider-experiment-override-meeting-rag-platform.md`
- `AGENTS.md`

## Known facts and evidence

- RALPLAN iteration 3 received Architect `SOUND` and Critic `APPROVE`.
- The repository has a clean Git/Lore baseline.
- WSL Ubuntu provides tmux, Node through NVM, OMX, and an authenticated Codex
  CLI.
- A prior Team launch created no implementation changes because its worker
  sessions were not authenticated. Its pending runtime/worktrees were
  explicitly shut down and removed before this retry.
- The approved plan conditionally retains Option A only when the Phase 0
  cookie, CSRF, upload streaming, and generated-client proof succeeds.
- G0 is blocking. A NO-GO must stop downstream product implementation rather
  than silently weakening HWP/OCR or sandbox requirements.

## Provider override

- Do not call xAI or Grok.
- Do not require `XAI_API_KEY`.
- Coding agents author and cross-review deterministic canonical JSON fixtures
  during development; the application reads them through `MockProvider`.
- Coding agents are not an HTTP/runtime provider dependency.
- Summary fixtures may use only canonical participant-source packs.
- Research/fact-check fixtures may use only the separate synthetic web-evidence
  packs and must retain participant-anchor plus web-evidence provenance.
- Do not claim Grok compatibility, live-model quality, or truth-benchmark
  status from these fixtures.

## Constraints

- Preserve exact citations, immutable source identities, and summary/research
  storage and tool isolation.
- Preserve Phase 0 and G0 stop gates.
- Keep each worker on the fixed `executor` agent type.
- One lane owns shared schemas/toolchain files; other lanes must coordinate
  before modifying them.
- Each lane records changed files, Lore-formatted commits, commands, raw
  verification results, and a cross-lane review.
- No new dependency may be selected without recording its role, license,
  version/lock evidence, and why an existing tool is insufficient.

## Open questions handled by gates

- If Option A proof fails, stop and produce the required Option C amendment;
  do not improvise a partial fallback.
- If HWP/OCR locator stability, extraction quality, licensing, or sandbox
  containment is a NO-GO, record the evidence and stop downstream work.
- Actual xAI adapter smoke testing stays skipped/non-blocking until the user
  explicitly restores live-provider experiments.

## Likely codebase touchpoints

- root toolchain, lockfiles, Docker/Compose, and CI/static-quality commands;
- `apps/web` disposable transport harness;
- `services/api`, `services/worker`, and parser-sandbox spike;
- provider schemas, canonical fixtures, citation validators, tests, ADRs, and
  gate evidence under repository documentation.

## Staffing

- leader: gate enforcement, shared-file integration, lifecycle monitoring;
- worker 1 (`executor`, high): repository/toolchain and Option A transport proof;
- worker 2 (`executor`, high): HWP/OCR/parser-sandbox G0;
- worker 3 (`executor`, high): source packs, MockProvider fixtures, validators,
  and provider ADR, followed by cross-lane verification.

