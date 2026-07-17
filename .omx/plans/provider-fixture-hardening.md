# Provider Fixture Hardening Plan

## Trigger

Independent contract and adversarial reviews returned `CHANGES_REQUIRED` after the
Team-authored fixture baseline passed its original five tests. The baseline is kept,
but its validation boundary must be strengthened before it can serve as the
development-time `MockProvider` contract.

## Invariants

- No xAI/Grok call, credential, network dependency, or runtime coding-agent dependency.
- Preserve fixed source, revision, anchor, evidence, schema, and prompt IDs.
- Keep summary content isolated from web evidence and fact-check verdicts.
- Treat every web source as explicitly synthetic and use reserved `.invalid` URLs.
- Do not claim Grok compatibility, model quality, or external truth.

## Small, ordered change set

1. **Normalize fixture semantics**
   - Add explicit source-anchor classifications.
   - Make fact-check claims faithful paraphrases of their participant anchors.
   - Mark the opinion fixture as excluded before evidence lookup.
   - Add normalized synthetic web citation fields (`url`, `domain`,
     `accessed_at`, `snippet_hash`).
   - Replace `pending-cross-review` with the completed coding-agent reviewer role.

2. **Define and enforce hashes**
   - `source_hash` is the canonical source-pack payload hash, excluding metadata.
   - A web-evidence document's `evidence_hash` is its canonical payload hash,
     excluding metadata.
   - Research and accepted fact-check `evidence_hash` values hash the sorted list
     of referenced evidence IDs and their validated evidence hashes.

3. **Make validation graph-based**
   - Load the actual source/evidence documents before validating references.
   - Enforce the exact required fixture inventory and unique IDs.
   - Resolve revision/anchor/evidence references, exact quotes, source hashes,
     evidence hashes, summary citations, rejection/retry shapes, four-verdict
     enums, and opinion/instruction filtering.

4. **Lock review findings with regression tests**
   - Add mutation tests for missing families, orphan references, hash tampering,
     quote drift, uncited/contaminated summaries, injection anchors, invalid
     verdicts, incomplete cross-review, and opinion-filter bypasses.
   - Close source, evidence, and all seven summary envelopes at every nested
     object boundary; pin the canonical schemas and reject malformed Unicode
     without crashing.
   - Require ordered atomic quotes to cover each anchor completely so arbitrary
     substrings cannot become accepted claims.

5. **Verify and normalize history**
   - Run compile, validator, unit, static/no-network, and diff checks.
   - Preserve a safety ref, replace Team wrapper commits with the already
     Lore-compliant content chain, then record hardening in one Lore commit.
   - Obtain a final independent read-only review before reporting completion.
