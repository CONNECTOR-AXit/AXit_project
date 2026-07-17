# Critic Review — Meeting RAG RALPLAN v2

- 대상: `.omx/drafts/ralplan-meeting-rag-platform-v2.md`
- Architect 입력: `.omx/reviews/architect-meeting-rag-platform-v2.md`
- 판정: **ITERATE**

## 결론

M1–M7과 M8 대부분은 해결됐다. 다만 F1 total-failure projection, F2 Team common-agentType,
F3 Option C stop/amend/review branch가 남아 실행자가 추측해야 한다.

## 필수 수정

1. **F1**: any queued/running -> `processing`; both succeeded -> `ready`; active가 0이고 둘 다
   succeeded가 아니면 성공 문서 수와 무관하게 `needs_attention`. 모든 failure reason/
   retryability를 반환하고 retryable이 하나라도 있으면 host action, 모두 terminal이면
   운영/재계획 reason을 준다. 조합 unit table과 양쪽 retryable/terminal/mixed E2E를 추가한다.
2. **F2**: `3:executor` 안에서는 agent type을 바꾸지 않는다. executor가 자신이 구현하지 않은
   lane을 cross-verify하고, Team terminal 뒤 별도 native `test-engineer` ->
   `security-reviewer` -> `verifier/architect` turn을 실행한다. visual verdict JSON은
   `.omx/state/{scope}/ralph-progress.json`에 저장한다.
3. **F3**: Option A proof 실패 시 Phase 2 전에 중단한다. target tree, schema source, UI phases,
   commands, staffing, launch hint, ADR/DAG를 포함한 bounded Option C amendment를 작성하고
   Architect+Verifier 승인 뒤에만 재개한다.

## 선택적 hardening

- CAS가 정확히 1 row가 아니면 completion transaction 전체를 rollback한다.
- Phase 0은 disposable transport proof이며 production auth는 Phase 3에서 반복한다.
- DB failure가 queue insertion도 막는 경우를 위해 correlation manifest + periodic orphan
  sweeper를 둔다.
- newline/Unicode normalization을 extraction config hash에 포함한다.
- Phase 4에 attachment/content-type/nosniff/CSP/sandboxed-viewer test를 연결한다.
