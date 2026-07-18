# ADR 0004: Align the frozen anchor and citation DTOs with proven traversal

- Status: accepted
- Date: 2026-07-18
- Phase: 2 — contract-freeze amendment

## Context

The initial Phase 2 `SourceAnchor` DTO used an API-specific inner locator
discriminator and renamed coordinate fields.  That shape could not represent
the canonical G0 payloads emitted by the proven parser/OCR sandbox, including
HWP/HWPX table and footnote paths.  A regression projection rejected all 52
captured G0 anchors.

The original result DTOs also exposed neither a citation ID on a summary
support nor the source revision ID when resolving a source citation.  A fresh
browser therefore could not follow a summary citation through the documented
resolver to the documented source-viewer URL.

## Decision

1. Keep `SourceAnchor.id` and `revision_id` as server-issued API envelope
   fields, but preserve the remaining canonical G0 identity losslessly:
   `schema_version`, outer `kind`, source/profile hashes, exact locator JSON,
   and text fingerprint.
2. Use G0's locator vocabulary exactly: `line/start/end`, array bboxes,
   `parser/parser_version`, and optional mutually-exclusive HWP `table` or
   `footnote` structural paths.  G0 parser block types remain separate from
   canonical anchor kinds.
3. Add `citation_id` to every `SummarySupport`, and require
   `source_revision_id` with a source-anchor `CitationTarget`.  This gives a
   client the documented resolver input and viewer path components without
   trusting client-provided coordinates.
4. Regenerate OpenAPI, JSON Schema, and TypeScript artifacts from the amended
   Pydantic source.  A contract regression projects every captured G0 anchor
   into `SourceAnchor` and compares the canonical fields byte-for-structure.

## Consequences

- Phase 3 can persist runtime UUID citations, resolve them after a fresh page
  load, and deep-link authorized members to a source revision and anchor.
- Workers must pass `SourceAnchor.canonical_payload()` through the G0
  canonicalizer before accepting a parser result or calculating its persisted
  canonical hash; normal Pydantic serialization is not the hash algorithm.
- No provider-fixture alias, raw original bytes, storage key, or parser
  failure payload enters these public DTOs.
- Future anchor-schema versions require an explicit compatibility decision;
  the current public contract accepts only the G0-proven version `1`.

## Rejected alternatives

- **Lossy API locator adapter:** would introduce a second coordinate identity
  and could silently erase HWP table/footnote traversal data.
- **Client-side remembered revision IDs:** works only in a single happy-path
  tab and does not make the resolver API sufficient after reload.
- **Undocumented anchor-ID resolver alias:** hides the citation relationship
  and risks one-to-many ambiguity when an anchor is cited by multiple
  segments.
