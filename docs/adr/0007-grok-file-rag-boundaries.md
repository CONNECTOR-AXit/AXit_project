# ADR 0007: Bound Grok file-level RAG storage, citations, and local mapping

- Status: accepted
- Date: 2026-08-10
- Scope: the owner-approved full Grok report pipeline for the current user

## Context

The production report pipeline may send normalized text anchors to xAI, perform
external web fact checking, and persist generated stages. It must still keep
uploaded binaries local, preserve file-level provenance, make every citation
resolvable to a member-visible local source, and fail closed when Grok is not
available. Earlier fixture and one-call-smoke documents contain broader
historical prohibitions that predate this approval.

## Decision

### Storage boundary

1. Original bytes remain behind `source_revisions.storage_key` in local blob
   storage. Provider payloads never contain the storage key, local path,
   filename, user identity, credentials, project description, or original
   binary.
2. The durable RAG identity is
   `submission -> source_revision -> approved extraction_run -> source_anchor`.
   A generation snapshot pins the exact revision and extraction run before any
   provider call.
3. Only normalized, quality-approved anchor text and opaque server UUIDs may
   leave the server. Requests use `store: false`; the transport rejects an
   oversized serialized request before reading credentials or opening a
   network connection.
4. Summary, research/web evidence, draft/final report, and editor suggestions
   remain distinct durable artifacts. Provider/model/prompt version, snapshot,
   hashes, evidence URL/access time/snippet hash, and typed failure state remain
   server-side provenance.

### File-level retrieval and citation boundary

1. Retrieval is local and snapshot-scoped. Low-confidence OCR, corrupt/control
   text, incomplete OCR fragments, and prompt-injection-like source text are
   rejected before provider transport.
2. Context selection retains at least one eligible anchor from every included
   file before filling the remaining bounded budget. Per-document summaries are
   independent; only the document-analysis stage may run in parallel.
3. Draft blocks have no trusted citations. For every draft claim, the server
   performs a fresh bounded local RAG lookup. The final response may cite only
   the anchor allowlist retrieved for that claim. Foreign anchor IDs, rewritten
   support, foreign target blocks, and cross-snapshot provenance fail closed.
4. Persisted citations point to server-issued source-anchor or web-evidence
   UUIDs. PostgreSQL constraints and resolver joins enforce generated document,
   snapshot, extraction-run, session, and active-membership ancestry.

### Local mapping boundary

1. A source citation resolves as
   `citation -> source_anchor -> source_revision -> submission -> session -> room membership`.
   The public response returns only the anchor UUID, revision UUID, and exact
   quote. It never returns `storage_key`, filesystem paths, or blob URLs.
2. The frontend maps the returned revision UUID to its already authorized
   project document model. Detailed viewing uses the membership-gated local
   viewer; original download remains attachment-only with `nosniff` and a fresh
   authorization check while streaming.
3. Missing, stale, corrupt, and unauthorized targets share the same unavailable
   response so citation resolution cannot become an IDOR oracle.

## Approval precedence and conflict check

- `provider-experiment-full-report-pipeline-amendment.md` is the controlling
  authorization for this pipeline as of 2026-08-10.
- The 2026-07-23 live-xAI amendment remains limited to its completed synthetic
  smoke call.
- The 2026-08-08 description-assist amendment remains limited to user-typed
  project title/description input.
- ADR 0001 and ADR 0003 retain their fixture/provenance decisions as historical
  phase records, but their old blanket offline-provider wording does not
  override the later explicit report-pipeline approval.
- No other paid-resource, xAI, external-deploy, user, project, or feature scope
  is authorized by this ADR.

## Consequences

- Provider outages and validation failures are visible, typed failures; there
  is no MockProvider or offline report substitution in production.
- Quality-excluded anchors remain locally viewable but cannot establish report
  facts or enter the local FTS/provider context.
- File coverage, source-quality counts, and citation deep links are reviewable
  without exposing local storage topology or raw files to xAI.
