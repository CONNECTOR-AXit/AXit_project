# Provider Experiment Override — Coding Agents Substitute for Grok

- 상태: 사용자 승인 임시 실행 전략
- 적용 시점: 2026-07-17
- 기준 계획: `.omx/plans/ralplan-meeting-rag-platform.md`
- 외부 xAI/Grok 호출: 보류

## Decision

현재 실험에서는 새 Team 세션의 코딩 에이전트가 Grok이 맡을 summary, topic research,
check-worthy claim selection, fact-check output을 개발 시점에 작성·상호 검토한다. 결과는
결정론적 JSON fixture로 저장하고 애플리케이션의 `MockProvider`가 읽는다.

코딩 에이전트를 HTTP/runtime provider로 호출하지 않는다. 이 전략은 외부 키·쿼터 없이
파이프라인, schema, citation, UI, retry를 구현·검증하기 위한 임시 substitute다.

## Team fixture protocol

1. **Source pack owner**
   - 합성 meeting topic, participant submissions, immutable source revision/anchor IDs를 작성.
   - 정답에 필요한 exact supporting spans를 고정.
2. **Summary fixture owner**
   - source pack만 사용해 atomic quote-backed summary를 작성.
   - URL, fact-check verdict, 외부 보충 지식을 넣지 않음.
3. **Research/fact-check fixture owner**
   - 합성 web evidence pack만 사용해 topic research와 four-verdict fact-check를 작성.
   - participant claim anchor와 web evidence를 모두 연결.
4. **Cross-review**
   - 자신이 작성하지 않은 fixture의 schema, citation resolution, unsupported assertion,
     summary contamination, opinion filtering을 검증.
5. **Persistence**
   - 동일 입력은 byte-stable canonical JSON을 생성하도록 정렬·정규화.
   - fixture author/reviewer, 작성 시각, schema/prompt version, source hash를 metadata에 기록.

## Required fixture families

- grounded summary 정상 응답
- valid anchor + unsupported assertion 거부 응답
- hallucinated/foreign anchor 거부 응답
- source prompt-injection 거부 응답
- supported/refuted/mixed/unverifiable research 응답
- opinion/value-judgment claim 제외 응답
- provider timeout/malformed schema/retry 응답

## Acceptance

- 외부 network/API key 없이 mock provider 경로가 실행된다.
- 저장 summary item의 citation 누락 0건, web/verdict contamination 0건.
- fact-check item마다 participant anchor + 1개 이상 web evidence가 있다.
- 모든 fixture가 canonical source/evidence ID로 resolve된다.
- agent-authored fixture를 Grok 호환성 또는 truth benchmark로 표현하지 않는다.
- 실제 xAI smoke는 사용자가 별도로 되돌리기 전까지 skip/non-blocking이다.

## Reversion

향후 실제 Grok 실험을 재개할 때도 이 fixture suite는 regression baseline으로 유지한다.
xAI adapter는 captured real response를 같은 내부 schema로 정규화하며, mock fixture를
자동으로 덮어쓰지 않는다.
