# Critic Review — Meeting RAG RALPLAN v1

- 대상: `.omx/drafts/ralplan-meeting-rag-platform-v1.md`
- Architect 입력: `.omx/reviews/architect-meeting-rag-platform-v1.md`
- 모드: deliberate RALPLAN, iteration 1
- 판정: **ITERATE**

## 근거

방향, 대안, G0, mock-first 검증, ADR 형식은 강하지만 Architect M1–M8이 모두 미반영이다.
현재 v1을 실행하면 queue 순서, snapshot 불변성, lease fencing, parser 격리, CSRF,
semantic grounding, anchor identity, staffing에서 구현자가 위험한 결정을 추측해야 한다.

## 대표 구현 시뮬레이션

1. **파일 제출·추출**: Phase 4가 extraction job을 요구하지만 queue/runner는 Phase 5에
   있어 완료 순서가 역전된다(`.omx/drafts/ralplan-meeting-rag-platform-v1.md:316-337`).
2. **동시 submit/close와 worker 재시작**: parent lock, exclusion audit, extraction version
   pin, lease-generation CAS가 없어 snapshot 오염 또는 stale completion을 막는 구현을
   추측해야 한다(`.omx/drafts/ralplan-meeting-rag-platform-v1.md:229-239`).
3. **요약/citation**: 유효한 anchor를 붙인 unsupported assertion이 현재 validator를
   통과할 수 있다(`.omx/drafts/ralplan-meeting-rag-platform-v1.md:241-251`).
4. **Next proxy 인증**: CSRF 방식을 선택지로 남겨 cookie forwarding, Origin/Host,
   credentialed CORS 의미가 미정이다(`.omx/drafts/ralplan-meeting-rag-platform-v1.md:304-314`).

## RALPLAN gate

| Gate | 판정 |
|---|---|
| 원칙–선택지 일관성 | 부분 실패 — Option C antithesis를 해소할 early smoke/전환 조건 부재 |
| 대안 깊이 | 통과 — B/C가 실제 대안이며 D도 장기 대안으로 공정하게 제시됨 |
| 위험·검증 엄밀성 | 실패 — CSRF/parser compromise/stale lease/semantic grounding 누락 |
| 3개 pre-mortem | 형식 통과, 고위험 parser/auth 시나리오 대표성 부족 |
| Unit/Integration/E2E/Observability | 형식 통과, M2–M7의 blocking fixture 누락 |
| ADR | 형식 통과, revised invariant와 Option C trigger 누락 |
| Staffing/Team | 실패 — 현재 leader 포함 4-slot에서 leader + 4 workers는 초과 |

## 필수 수정

1. 최소 durable queue를 계약 직후로 옮기고 G0 후 text-only end-to-end vertical slice를 먼저
   닫는다.
2. parent-row serialization, exclusion audit, extraction/anchor version pin, canonical
   uniqueness를 고정한다.
3. at-least-once + fenced persistence, DB-clock lease token/generation CAS, attempt history를
   고정한다.
4. credential 보유 orchestrator와 secretless/networkless/resource-bounded parser sandbox를
   분리한다.
5. server-side synchronizer CSRF + exact Origin/Host + proxy/cookie 계약을 하나로 확정한다.
6. quote-backed atomic summary, cited span, valid-anchor unsupported-assertion 및 source
   prompt-injection fixture를 blocking G6에 추가한다.
7. server-issued opaque anchor ID, 좌표 규약, 반복 anchor hash/click gate를 추가한다.
8. leader + 3 workers와 slot 재사용 DAG로 낮추고 `$visual-verdict`, accessibility, viewport
   검증을 추가한다.
9. Option A의 time-boxed proxy/auth smoke와 실패/owner 부재 시 Option C 전환 trigger를 ADR에
   넣는다.
10. partial terminal state/retry projection을 정의한다.

## 선택적 개선

- `packages/schemas`를 Pydantic/OpenAPI 생성물로 고정한다.
- 첫 구현이 없는 `RetrievalProvider`는 제거한다.
- upload staging/DB 실패 orphan cleanup과 demo retention을 기록한다.
- v2는 v1보다 압축하되 필수 의미론을 삭제하지 않는다.
