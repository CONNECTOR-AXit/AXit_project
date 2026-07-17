# AXit Meeting RAG — Agent Contract

## Mission

Implement the approved meeting pre-briefing RAG plan:

- `.omx/plans/ralplan-meeting-rag-platform.md`
- `.omx/plans/prd-meeting-rag-platform.md`
- `.omx/plans/test-spec-meeting-rag-platform.md`
- `.omx/plans/provider-experiment-override-meeting-rag-platform.md`

Proceed autonomously on safe, reversible work. Do not ask whether to continue when the next gate is clear.

## Current execution boundary

1. Preserve the dependency order and blocking gates in the approved plan.
2. Phase 0 Option A proof failure or missing web-owner capacity stops execution for an Option C amendment.
3. Phase 1 HWP/OCR/sandbox G0 failure stops general implementation and triggers replanning.
4. Do not deploy externally, use paid resources, store user credentials, or upload originals to third parties.
5. Do not implement completed chat/realtime, export, native apps, billing, or other explicit non-goals.

## Temporary Grok substitution

- Do **not** call xAI/Grok during the current experiment.
- New-session coding agents may curate source-grounded summary, research, and fact-check outputs.
- Persist those outputs as deterministic, reviewable fixtures consumed by a `MockProvider`.
- Agent sessions are development-time fixture authors/reviewers, never a runtime service dependency.
- Do not describe agent-authored fixtures as evidence of Grok compatibility or production model quality.
- Every summary item needs exact participant support; every research/fact-check item needs the citations
  required by the approved schema. Summary/research isolation remains mandatory.

## Working agreements

- Lock behavior with regression tests before cleanup/refactor edits.
- Prefer deletion/reuse over new abstractions.
- Do not add dependencies unless the approved phase requires them and the choice is recorded.
- Keep shared schema, migrations, and generated OpenAPI client under single-lane ownership.
- Run applicable lint, typecheck, unit, integration, security, E2E, and evaluation gates.
- Never weaken or delete tests to pass a gate.
- Record visual-verdict JSON at `.omx/state/{scope}/ralph-progress.json` before each subsequent visual edit.

## Team ownership

- Team workers keep the fixed `executor` agent type.
- Each worker writes only its assigned lane and reports shared-file conflicts before editing.
- A worker cross-verifies only a lane it did not implement.
- Team shutdown requires pending/in-progress/failed task counts of zero.
- After Team terminal, independent `test-engineer`, `security-reviewer`, and `verifier/architect`
  reviews remain required.

## Lore commit protocol

Every commit uses an intent-first subject and, when relevant, trailers:

```text
<why this change is needed>

<context and rationale>

Constraint: <external constraint>
Rejected: <alternative> | <reason>
Confidence: <low|medium|high>
Scope-risk: <narrow|moderate|broad>
Tested: <verification>
Not-tested: <known gap>
```

Do not commit secrets, `.env`, generated runtime state, logs, local blobs, caches, or build output.
