# Deep Interview Context Snapshot — Meeting RAG Platform

## Task statement
Plan a meeting-minutes product with friend/invite-based rooms and two talk-session modes: participant submission and participant conversation.

## Desired outcome
An execution-ready specification and plan for a system that preserves original participant content, produces faithful LLM summaries with source citations, and creates a separate LLM research report containing topic research and participant-claim fact-checking with traceable citations.

## Stated solution
1. Participant submission mode (implementation priority): invitees submit files and/or written opinions about a meeting topic. Originals remain visible. The LLM creates a summary plus a distinct research report.
2. Participant conversation mode: invitees chat in a room; when the session ends, one submission triggers processing of the full conversation into a summary plus a distinct research report.
3. Summary citations must resolve to original source line references (or an equivalent canonical locator to be decided).
4. Topic research must cite web sources.
5. Fact-checking must cite both the participant statement being checked and the supporting/contradicting web evidence.
6. Topic research and fact-check results may appear only in the LLM research report and must never alter the faithful summary.

## Probable intent hypothesis
Help groups prepare for and conclude meetings while maintaining auditability: users can distinguish what participants actually submitted/said from externally researched or fact-checked material.

## Known facts / evidence
- The repository is greenfield: the root README is empty and no application code or product documentation exists.
- The participant submission mode is stated as the implementation priority.
- Both modes share room membership, session topic, source preservation, LLM processing, RAG-style citations, and a two-document output boundary.

## Constraints
- Preserve all participant originals for authorized room members.
- Keep summary content semantically isolated from web research and fact-check enrichment.
- Provide source-grounded citations for generated claims.
- Do not implement during Deep Interview; produce clarified artifacts and hand off to planning/execution.

## Unknowns / open questions
- MVP scope: submission mode only first, or both modes end-to-end in the same milestone.
- Target users and primary meeting scenario.
- Authentication, invitation, permissions, and room membership lifecycle.
- Supported input file types, size limits, OCR/audio needs, and canonical line-number behavior.
- Real-time chat expectations and session close/reopen semantics.
- LLM/search providers, deployment target, budget, latency, and privacy/data-retention constraints.
- Exact citation/RAG UX, provenance schema, and unsupported/contradictory evidence handling.
- Fact-check selection policy: all claims vs check-worthy claims vs user-selected claims.
- Summary format, research report format, language, export, and edit/approval flows.
- Acceptance criteria, non-goals, and decisions the implementation agent may make autonomously.

## Decision-boundary unknowns
- Whether architecture/provider/framework choices may be made without further confirmation.
- Which features are explicitly out of scope for the first implementation milestone.
- Whether external browsing and uploaded content may be sent to third-party APIs.

## Likely codebase touchpoints
Greenfield application structure: frontend, backend/API, database, object storage, authentication, realtime transport, document ingestion/chunking, LLM orchestration, web research/search integration, citation/provenance model, and test/evaluation harness.

## Relevant repo docs/rules/context inspected
- Repository root `README.md`: empty.
- No repository-local `AGENTS.md`, `CONTEXT.md`, `CONTEXT-MAP.md`, plans, specs, or prior context snapshots were present.
- Governing session AGENTS instructions and Deep Interview skill contract apply.

## Terminology / conflicts
- “RAG tag” is not yet a precise product contract. It may mean a clickable citation, a source-span provenance object, or retrieval metadata; this must be clarified.
- “line number” is well-defined for text but ambiguous for PDF, DOCX, slides, images/OCR, and chat messages.

## Prompt-safe initial-context summary status
not_needed — the user request is substantial but can be faithfully represented by this snapshot without a separate summary round.
