# Architect Review — Meeting RAG RALPLAN v2

- 대상: `.omx/drafts/ralplan-meeting-rag-platform-v2.md`
- 판정: **REVISE**
- 요약: v1의 M1–M7은 해결됐고 M8도 대부분 해결됐다. 아래 F1–F3만 실행 전에 닫아야 한다.

## M1–M8 audit

| 항목 | 판정 |
|---|---|
| M1 queue 순서 + vertical slice | RESOLVED — Phase 2 core 뒤 Phase 3/4 job |
| M2 snapshot/serialization | RESOLVED — parent lock, exclusion audit, extraction pin, canonical unique |
| M3 lease fencing/retry | RESOLVED — at-least-once, generation/token CAS, attempt history |
| M4 parser sandbox | RESOLVED — credentialed orchestrator와 secretless sandbox 분리 |
| M5 auth/CSRF/proxy | RESOLVED — synchronizer token, Origin/Host, cookie/proxy 계약 |
| M6 grounding | RESOLVED — quote span, bounded reduce, unsupported/prompt-injection gate |
| M7 anchor/resolver | RESOLVED — opaque ID, coordinates, repeat hash/click |
| M8 staffing/visual | PARTIAL — slot 수와 visual gate는 해결, agent-type 재사용 표현은 불가 |

## Must-fix

### F1 — total generation failure projection

현재는 둘 다 성공하면 `ready`, 하나만 성공하면 `needs_attention`만 명시돼 둘 다 실패한
조합이 영구 `processing`이 될 수 있다
(`.omx/drafts/ralplan-meeting-rag-platform-v2.md:201-209`).

- canonical run 중 하나라도 queued/running이면 `processing`.
- 둘 다 succeeded면 `ready`.
- active run이 0이고 둘 다 succeeded가 아니면 성공 문서 수와 무관하게 `needs_attention`.
- 모든 failed kind의 reason/retryable을 반환하고 하나라도 retryable이면 host retry action 제공.
- terminal-only failure면 retry 없이 운영/재계획 reason 제공.
- 이 조합을 unit table/E2E에 추가한다.

### F2 — Team agent type 재사용

한 `3:executor` launch 안에서 slot을 `test-engineer`/`security-reviewer`/`verifier` agent type으로
바꿀 수 없다. Team 안에서는 종료한 executor가 **자신이 구현하지 않은 lane**의 cross-lane
verification task를 맡는다. Team terminal 후 별도 native `test-engineer` ->
`security-reviewer` -> `verifier/architect` turn을 순차 실행한다. visual verdict JSON은
`.omx/state/{scope}/ralph-progress.json`에 저장한다.

### F3 — Option C branch

Option A proof 실패 후 ADR만 C로 바꾸면 downstream tree/client/Next phase/pnpm/staffing이
계속 A를 전제한다. 실패 시 Phase 2로 자동 진행하지 말고 **Option C plan-amendment gate**로
멈춘다. 목표 tree, schema/client source, UI phases, commands, staffing/launch를 C용으로
수정한 bounded amendment를 Architect/Verifier가 승인한 뒤 재개한다.

## 권고 hardening

1. CAS가 1 row가 아니면 completion transaction 전체를 exception/rollback한다.
2. Phase 0 proof는 폐기 가능한 transport harness이며 production auth correctness는 Phase 3에서
   다시 검증한다.
3. DB commit 실패 때 queue 기록도 불가능할 수 있으므로 correlation manifest + periodic orphan
   sweeper를 둔다.
4. newline/Unicode normalization profile을 extraction config hash에 포함한다.
5. Phase 4에 attachment/content-type/nosniff/CSP/sandboxed viewer test를 직접 연결한다.

## Antithesis / tension / synthesis

- **Antithesis**: Option C는 proxy/two-lockfile/client-generation을 제거하므로 proof가 성공해도
  팀 capacity가 부족하면 D1/P3에 더 맞을 수 있다.
- **Tension**: richer viewer/parallel web lane 대 single-toolchain delivery risk, readable
  abstractive summary 대 deterministic grounding, sandbox security 대 IPC complexity.
- **Synthesis**: Option A proof는 disposable transport harness로 제한하고, 실패하면 F3의
  bounded amendment를 거친다. Python core invariant는 UI branch와 독립적으로 유지한다.

## Principle audit

- P1 출처 우선: 충족.
- P2 출력 격리: 명시된 semantic 한계와 함께 충족.
- P3 최소 인프라: F3 branch가 닫히면 충족.
- P4 실패 가시성: F1 때문에 아직 불충분.
- P5 결정론적 검증: 충족.
