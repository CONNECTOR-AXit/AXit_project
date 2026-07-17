# Architect Review — Meeting RAG RALPLAN v1

- 대상: `.omx/drafts/ralplan-meeting-rag-platform-v1.md`
- 모드: deliberate RALPLAN, iteration 1
- 역할: 독립 read-only Architect
- 판정: **REVISE**

## 요약

Option A의 방향, G0, provenance-first anchor, summary/research 구조 분리, mock-first 검증,
ADR/staffing은 강하다. 그러나 그린필드 구현자가 임의로 채우면 불변성·보안이 깨질 수 있는
transaction/fencing/trust-boundary 의미론이 남았고, extraction job이 queue보다 먼저 나오는
의존성 역전이 있다. 아래 항목을 반영하기 전에는 실행 가능한 합의안으로 승인할 수 없다.

## Must-fix

### M1 — Phase 의존성과 vertical slice

- Phase 4가 extraction job/worker 연결을 요구하지만 durable queue/runner는 Phase 5에서
  처음 구현된다(`.omx/drafts/ralplan-meeting-rag-platform-v1.md:316-337`).
- 최소 job schema/claim/lease runner를 계약 기반 직후로 당겨야 한다.
- G0 뒤 `text opinion -> close -> mock summary -> citation resolve` thin vertical slice를 먼저
  닫고, 그 뒤 PDF/HWP/research를 확장한다.

### M2 — close/snapshot 직렬화와 불변성

- submit/replace/close 모두 동일한 `talk_sessions` parent row를 `FOR UPDATE`하고 lock 획득
  후 `state == open`을 재검사한다.
- unresolved current revision은 host가 명시적으로 제외하기 전 close를 막고, exclusion
  decision을 snapshot audit data에 기록한다
  (`.omx/plans/prd-meeting-rag-platform.md:79-85`).
- session당 canonical snapshot/generation epoch와
  `(snapshot_id, kind, pipeline_version)` canonical result uniqueness를 DB로 보장한다.
- snapshot은 revision뿐 아니라 immutable extraction run/anchor schema version, topic,
  participant attribution을 pin하며 추출/anchor를 in-place overwrite하지 않는다
  (`.omx/specs/deep-interview-meeting-rag-platform.md:127-151`).

### M3 — lease fencing과 retry 의미

- 실행 모델을 **at-least-once execution + idempotent/fenced persistence**로 명시한다.
- claim은 DB clock 기반 `lease_token/lease_generation`, `lease_owner`, `lease_until`을 만든다.
- heartbeat/completion은 token과 running state의 CAS이며 stale token은 0-row update로
  거부한다.
- 결과 저장과 success transition은 한 transaction이다.
- retry는 같은 logical job row를 requeue하고 별도 attempt history를 남기는 의미로 고정한다.

### M4 — job orchestrator와 parser sandbox

- DB/blob/provider credential을 가진 orchestrator와 비신뢰 parser sandbox를 분리한다.
- sandbox는 staged read-only input만 받고 secret/DB/blob/provider access가 없으며 non-root,
  no-new-privileges, no egress, CPU/RAM/PID/time/output-size 제한을 가진다.
- orchestrator는 sandbox structured output을 schema/size 검증한 뒤 저장한다.
- Phase 1 G0에서 topology, 제한, timeout cleanup을 실제로 검증한다
  (`.omx/plans/prd-meeting-rag-platform.md:202-211`).

### M5 — same-origin session/CSRF 계약 확정

- host-only HttpOnly opaque session cookie, 로그인 rotation, DB에는 token hash만 저장한다.
- 운영은 Secure + SameSite=Lax를 사용한다.
- session-bound server-side synchronizer CSRF token을 발급하고 모든 unsafe method에서
  token과 exact Origin/Host를 검증한다.
- wildcard credentialed CORS를 금지하고 proxy는 Cookie/Set-Cookie를 정확히 중계하되
  user/room/role 헤더를 제거한다.
- forged Origin, missing token, expired/rotated session, cookie path를 integration/E2E로
  검증한다 (`.omx/plans/test-spec-meeting-rag-platform.md:150-164`).

### M6 — semantic grounding

- 구조적으로 유효한 in-snapshot anchor를 붙인 unsupported assertion도 차단해야 한다.
- summary를 atomic quote-backed item으로 제한하고 cited excerpt/span을 보존한다.
- `valid anchor + unsupported assertion`와 source prompt-injection fixture를 G6 blocking
  groundedness gate에 추가한다
  (`.omx/specs/deep-interview-meeting-rag-platform.md:98-106`,
  `.omx/specs/deep-interview-meeting-rag-platform.md:186-191`).
- 자유 abstractive reduce를 허용하면 완전 보장을 주장하지 말고 고정 fixture/rubric의
  groundedness 평가 한계를 명시한다.

### M7 — anchor identity/resolver 의미

- citation은 server-issued opaque `source_anchor_id`만 사용한다.
- resolver가 membership과 snapshot/revision/extraction-run 소속을 DB에서 검증하며
  client-provided raw coordinate JSON을 신뢰하지 않는다.
- PDF page base/rotation/crop-box/origin, normalized image bbox, HWP parser version/path를
  schema에 고정한다.
- G0 GO에 반복 extraction의 canonical anchor hash 안정성과 click-to-highlight 성공을
  blocking 기준으로 넣는다.
- web link는 http/https만 허용하고 안전한 external-link 정책을 사용한다.

### M8 — staffing/task DAG

- 현재 runtime은 leader 포함 4 slots이므로 권고를 leader + 3 workers로 낮추고 완료된 slot을
  독립 verifier/security reviewer가 재사용한다.
- `contract freeze -> backend/ingestion/web 병렬 -> 구현 비참여 verifier` DAG로 바꾼다.
- visual iteration마다 `$visual-verdict` 증거와 최종 accessibility/viewport 검증을 요구한다.

## Strongest antithesis

Option C(FastAPI + server-rendered pages + 최소 JavaScript)는 CRUD/upload/polling/result
comparison/bbox highlight라는 현재 MVP와 호환되며, Next/FastAPI proxy, 두 lockfile,
generated client, cookie forwarding의 통합 실패면을 제거한다. 완성 chat UI가 비목표이므로
팀의 Next 역량과 UI 필요가 입증되지 않으면 Option C가 D1과 “해커톤 최소 인프라”에 더
일관적일 수 있다.

## Tradeoff tension

- Option A의 UX/병렬 staffing/후속 chat 준비성 대 Option C의 단일 toolchain/same-origin
  단순성은 동시에 최대화할 수 없다.
- parser sandbox는 보안을 높이지만 IPC·운영 복잡도를 추가한다. 비신뢰 native parser라는
  D3 때문에 제거할 수 없고 최소 계약으로 관리해야 한다.
- 자유 abstractive summary의 읽기 품질과 deterministic “원문 외 사실 0” 보장도 긴장한다.

## Synthesis

Option A를 **thin Next shell + contract-first Python core**로 제한한다. Phase 0에 login
cookie/CSRF/upload/mock citation proxy smoke를 time-box하고, G0 후 text-only vertical
slice를 먼저 닫는다. proxy/auth smoke 실패 또는 전담 Next owner 부재 시 schema/domain
대규모 구현 전에 Option C로 전환하는 ADR trigger를 둔다.

## Principle audit

- 원칙 1 출처 우선: extraction/anchor version pin과 opaque resolver가 없어 잠정 위반 위험.
- 원칙 2 출력 격리: 구조 분리는 강하지만 semantic grounding proof가 부족.
- 원칙 3 최소 인프라: Option A의 추가 toolchain을 early smoke/owner gate로 정당화해야 함.
- 원칙 4 실패 가시성: failed/unready source의 조용한 제외를 막으면 충족.
- 원칙 5 결정론적 검증: mock/fixture/10회 반복/optional smoke로 강하게 충족.

## Improvement suggestions

1. `packages/schemas`는 Pydantic/OpenAPI에서 생성되는 artifact로 단일 source of truth를 유지한다.
2. partial terminal state와 retryable projection을 명시해 세션이 `processing`에 영구 체류하지
   않게 한다.
3. local blob staging, DB commit 실패 orphan cleanup, demo retention 정책을 기록한다.
4. 실제 두 구현이 없는 `RetrievalProvider`는 삭제하고 vector 필요가 입증될 때 추출한다.
