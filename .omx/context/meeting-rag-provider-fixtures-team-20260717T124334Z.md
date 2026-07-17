# Team Context Snapshot — Provider Fixture Authoring

## Task statement

Run three new OMX Team coding-agent sessions to author the deterministic
provider fixtures that temporarily substitute for Grok outputs.

## Scope correction

This Team run is provider-fixture authoring only. It does not evaluate or
implement the Phase 0 transport proof or Phase 1 HWP/OCR G0. The greenfield
absence of an application/toolchain is expected and is not a NO-GO result for
this run.

## Authoritative inputs

- `.omx/plans/provider-experiment-override-meeting-rag-platform.md`
- `.omx/plans/ralplan-meeting-rag-platform.md`
- `.omx/plans/prd-meeting-rag-platform.md`
- `.omx/plans/test-spec-meeting-rag-platform.md`
- `AGENTS.md`

## Desired artifacts

1. `provider_fixtures/source/` plus a canonical schema, validator, unit tests,
   metadata rules, and provider ADR.
2. `provider_fixtures/summary/` containing grounded, unsupported-assertion,
   foreign-anchor, prompt-injection, timeout, malformed-schema, and retry
   fixture families.
3. `provider_fixtures/web_evidence/`, `provider_fixtures/research/`, and
   `provider_fixtures/factcheck/` covering supported, refuted, mixed,
   unverifiable, and opinion-excluded outcomes.

## Fixed identities

Workers coordinate on these stable identifiers without editing each other's
file areas:

- source pack: `meeting-pack-001`
- revisions: `revision-agenda-001`, `revision-alice-001`,
  `revision-bob-001`
- participant anchors: `anchor-agenda-001`, `anchor-alice-001`,
  `anchor-alice-002`, `anchor-bob-001`, `anchor-bob-opinion-001`
- web evidence: `web-evidence-001` through `web-evidence-006`
- schema version: `provider-fixture.v1`
- prompt version: `mock-provider.prompt.v1`

## Worker ownership

- worker 1: `provider_fixtures/schema/`, `provider_fixtures/source/`,
  `tools/validate_provider_fixtures.py`, `tests/test_provider_fixtures.py`,
  and `docs/adr/0001-agent-curated-mock-provider-fixtures.md`.
- worker 2: `provider_fixtures/summary/` only.
- worker 3: `provider_fixtures/web_evidence/`,
  `provider_fixtures/research/`, and `provider_fixtures/factcheck/` only.

No worker may edit another worker's owned paths. Root integration runs the
validator after all commits merge, then sends any defects to a fresh
cross-review session rather than weakening validation.

## Hard constraints

- Never call xAI or Grok and never require `XAI_API_KEY`.
- Coding agents are development-time fixture authors, not runtime providers.
- Summary items use participant anchors only and contain no URL, verdict, or
  externally supplied fact.
- Research/fact-check fixtures use a separate synthetic web-evidence pack.
- Every fact-check item resolves both a participant anchor and at least one web
  evidence ID.
- Opinion/value-judgment claims are explicitly excluded.
- IDs resolve exactly; unknown/foreign anchors are represented only as
  expected rejection fixtures.
- Canonical JSON is UTF-8, key-sorted, newline-terminated, and byte-stable.
- Metadata records author/reviewer role, created-at, schema/prompt versions,
  and source/evidence hashes without claiming live Grok quality.
- Use Python standard library only; do not add a dependency or contact the
  network.

## Completion condition

All three worker tasks complete with Lore-formatted commits. After Team merge,
the root validator and unit tests pass, all required fixture families exist,
and a fresh coding-agent review finds no citation, isolation, schema, or
determinism defect.

