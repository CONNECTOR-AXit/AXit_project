# Architecture image gap extension

Status: user-authorized incremental extension (2026-08-04)

The original milestone deliberately excluded infrastructure whose value had not
been measured. The project owner subsequently requested implementation of the
remaining capabilities shown in `FINAL_GOAL.png`, one item at a time. This note
keeps that request separate from claims about the original approved milestone.

## Delivery order

1. TXT original upload and deterministic UTF-8 line anchors.
2. DOCX original upload and sandboxed paragraph/table extraction.
3. PostgreSQL FTS top-k retrieval and metadata pre-filtering.
4. Document comparison plus omission/duplication findings with citations.
5. Measured retrieval evaluation; only then decide whether embeddings/vector
   storage are justified.
6. Hierarchical summarization, semantic deduplication, response caching, and
   prompt token optimization, each behind deterministic evaluation fixtures.

Collaborative real-time editing remains an explicit non-goal. A later extension
may provide non-realtime, reviewable suggestions without changing that boundary.

## Increment 1 decision: TXT

- Store the exact original in the existing local blob store.
- Accept `.txt` as canonical `text/plain`; reject a binary NUL prefix.
- Decode UTF-8/UTF-8-BOM only. Invalid encoding becomes a typed terminal
  extraction failure rather than silent replacement.
- Normalize CRLF/CR to LF and emit one stable `text_line` anchor per non-empty
  physical line.
- Use the built-in decoder, so no dependency or third-party upload is added.

## Increment 2 decision: DOCX

- Keep DOCX parsing inside the existing network-disabled, non-root parser
  sandbox; the API and orchestrator never parse Office XML.
- Use Python's standard ZIP/XML readers after enforcing entry count,
  per-entry/total expansion, compression-ratio, XML-size, and DTD/entity gates.
- Emit stable `docx_paragraph` anchors for body paragraphs and table cells.
- Recognize Word `TOC*` and `Heading*` paragraph styles as `toc_entry` and
  `heading` blocks. No new runtime dependency is required.
- Extract bounded `docProps/core.xml` properties as cited `docx_metadata`
  blocks under the same ZIP, XML-size, and DTD/entity controls.

## Implemented capability matrix

- **Retrieval:** PostgreSQL `simple` FTS with session/current-approved-run
  scoping, Top-K ranking, MIME and author prefilters, and a GIN expression index.
- **Comparison:** bounded candidate generation plus fixed work/anchor budgets;
  duplicate, similar, and bilateral omission results retain both source links.
- **Semantic dedup:** network-free signed feature-hash embeddings combine word
  and character n-grams with a deliberately bounded meeting-domain concept
  ontology. This supports reviewed meeting paraphrases; it is not a general
  language embedding model and must grow only with deterministic evaluation
  fixtures.
- **Hierarchy/token control:** the active provider-neutral runner performs
  document-stage grounded summaries followed by deterministic cited synthesis.
  A global token estimate and document-stage call cap fail closed on overflow.
- **Provider boundary:** `GenerationProvider` and `CallbackGenerationProvider`
  separate runtime orchestration from Mock/Grok transports. All provider errors
  share a retry-aware typed base; live xAI remains disabled.
- **Integrated report/cache:** the frontend consumes `/report`; its private ETag
  is the canonical SHA-256 identity of the immutable summary/research document
  hash pair.
- **Collaboration:** suggestions are asynchronous and immutable, pinned to the
  exact snapshot/report hash, constrained to snapshot ancestry, and resolved
  only by the current host member.
