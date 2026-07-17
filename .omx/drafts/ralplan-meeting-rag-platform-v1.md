# RALPLAN-DR 통합 실행 계획 — 회의 사전 브리핑 RAG 플랫폼

- 상태: 합의 검토용 초안 v1
- 모드: deliberate consensus
- 범위: 첫 마일스톤 — 참여자 전달형 완성 + 대화형 공통 계약 기반
- 구현 상태: 미시작
- 기준 문서:
  - `.omx/context/meeting-rag-platform-20260716T080912Z.md`
  - `.omx/specs/deep-interview-meeting-rag-platform.md`
  - `.omx/plans/prd-meeting-rag-platform.md`
  - `.omx/plans/test-spec-meeting-rag-platform.md`
  - `.omx/plans/ralplan-checkpoint-meeting-rag-platform.md`

> 이 문서에서 `planned:`가 붙은 경로는 아직 존재하지 않는 구현 대상이다. 현재 저장소는 빈
> `README.md`와 계획 산출물만 있는 그린필드이며 구현·테스트는 시작되지 않았다
> (`.omx/context/meeting-rag-platform-20260716T080912Z.md:14-37`,
> `.omx/plans/ralplan-checkpoint-meeting-rag-platform.md:3-29`).

## 1. 요구사항 요약

### 1.1 제품 결과

1. 친구 관계를 맺은 사용자가 비공개 방과 전달형 토크 세션을 만들고 초대받은 참가자가
   텍스트 의견 또는 PDF/HWP/HWPX/PNG/JPEG 자료를 제출한다
   (`.omx/specs/deep-interview-meeting-rag-platform.md:40-72`).
2. 주최자가 제출을 마감하면 정확한 원본 리비전 집합을 불변 스냅샷으로 고정하고, 그
   스냅샷에서 요약본과 조사본을 비동기로 생성한다
   (`.omx/specs/deep-interview-meeting-rag-platform.md:84-96`,
   `.omx/plans/prd-meeting-rag-platform.md:67-85`).
3. 요약본은 참가자 원본만 사용하고, 모든 근거 항목이 형식별 원본 anchor를 가져야 한다.
   웹 지식·팩트체크·행동 제안은 요약본에 들어갈 수 없다
   (`.omx/specs/deep-interview-meeting-rag-platform.md:98-106`).
4. 조사본은 주제 웹 조사와 자동 선별한 검증 가능 주장 팩트체크를 분리해 제공한다.
   팩트체크는 참가자 원문과 웹 근거를 모두 인용한다
   (`.omx/specs/deep-interview-meeting-rag-platform.md:108-123`).
5. 인용은 파일명이 아니라 불변 `SourceRevision`과 형식별 `SourceAnchor`를 가리키며,
   resolver가 실제 원본/추출 미리보기 위치 또는 웹 URL로 해석한다
   (`.omx/specs/deep-interview-meeting-rag-platform.md:125-151`).
6. Grok은 최초 공급자지만 내부 어댑터 뒤에 두고, 원본 bytes/저장 URL이 아니라 필요한
   추출 조각만 전송한다. 키가 없는 환경에서는 결정론적 mock으로 전체 데모가 동작해야 한다
   (`.omx/specs/deep-interview-meeting-rag-platform.md:153-159`,
   `.omx/specs/deep-interview-meeting-rag-platform.md:201-205`).

### 1.2 명시적 범위 경계

- 포함: 로컬 인증, 친구 요청, 방/멤버십, 전달형 세션, 다중 형식 제출, 원본 보존,
  파싱/OCR, 불변 마감 스냅샷, 비동기 생성, 요약/조사 분리, 인용 viewer/resolver,
  향후 `chat_message` anchor 계약
  (`.omx/plans/prd-meeting-rag-platform.md:21-37`).
- 제외: 음성·영상/STT, 실시간 공동편집, 공개 링크/내보내기, 네이티브 앱, 과금,
  완성된 대화형 채팅, 상용 HA/규정 준수
  (`.omx/specs/deep-interview-meeting-rag-platform.md:74-82`).
- 별도 승인 필요: 실제 외부 배포, 유료 자원/자격증명, 원본 파일의 제3자 업로드,
  비목표 기능 추가, 요약·조사 경계 변경
  (`.omx/specs/deep-interview-meeting-rag-platform.md:212-228`).

## 2. RALPLAN-DR 결정 요약

### 2.1 원칙

1. **출처 우선**: 생성 편의보다 원본 불변성, anchor 해석 가능성, 인용 검증을 우선한다.
2. **출력 격리**: faithful summary와 외부 조사/팩트체크는 타입·도구·실행·저장 경계에서
   분리한다.
3. **해커톤 최소 인프라**: 데모 신뢰성을 지키는 범위에서 서비스와 운영 구성요소 수를
   최소화한다.
4. **실패 가시성**: 파싱/OCR/LLM 실패를 숨기거나 원본을 삭제하지 않고 단계별 상태와
   재시도 가능성을 표시한다.
5. **결정론적 검증**: 유료 키나 외부 네트워크 없이 핵심 사용자 여정과 인용 계약을
   반복 검증할 수 있어야 한다.

### 2.2 상위 결정 동인

1. **D1 — 데모 완주 가능성**: HWP/OCR 및 비동기 생성이 가장 큰 일정·통합 위험이다
   (`.omx/specs/deep-interview-meeting-rag-platform.md:161-169`).
2. **D2 — 감사 가능성**: citation resolver 100%, summary contamination 0건이 핵심
   품질 기준이다 (`.omx/plans/test-spec-meeting-rag-platform.md:137-147`).
3. **D3 — 개인정보·보안 경계**: 비공개 방, 비신뢰 업로드, 제3자 LLM 전송 최소화가
   아키텍처 전반의 신뢰 경계를 결정한다
   (`.omx/plans/prd-meeting-rag-platform.md:202-211`).

### 2.3 실행 가능한 선택지

#### 옵션 A — 경량 폴리글랏 모노레포: Next.js + FastAPI/worker + PostgreSQL

- 접근: TypeScript App Router UI, Python API/문서 처리 worker, PostgreSQL DB/작업 큐,
  로컬 볼륨 `BlobStore` 어댑터를 Docker Compose로 묶는다.
- 장점:
  - Python 문서/OCR 생태계와 타입화된 FastAPI/Pydantic 경계를 직접 활용한다.
  - API와 worker가 같은 도메인·인용·provider 코드를 공유하면서 프로세스는 분리된다.
  - PostgreSQL 하나로 영속 데이터와 해커톤 규모의 lease queue를 처리해 Redis를 생략한다.
  - Next.js가 결과 비교, 상태 polling, anchor viewer 같은 상호작용 UI에 적합하다.
- 단점:
  - Node/Python 두 도구 체인과 OpenAPI client 생성 동기화가 필요하다.
  - 로컬 동일 출처 proxy, 쿠키/CSRF, 공유 볼륨 설정을 명시적으로 검증해야 한다.

#### 옵션 B — 단일 TypeScript: Next.js UI/API + Node worker + PostgreSQL

- 접근: Route Handler 또는 별도 Node API와 Node worker로 전체를 구성한다.
- 장점:
  - 한 언어·한 패키지 관리자로 초기 개발 경험과 타입 공유가 단순하다.
  - UI와 API 계약 변경 속도가 빠르다.
- 단점:
  - HWP/HWPX, PyMuPDF 계열 PDF 좌표, 한국어 OCR을 Node에서 직접 처리하거나 Python
    sidecar를 다시 도입해야 해 “단일 언어” 이점이 핵심 위험 구간에서 사라진다.
  - 무거운 파서 격리와 Python 기반 골든 fixture 재현 비용이 커진다.

#### 옵션 C — 단일 Python: FastAPI + 서버 렌더링 UI + worker + PostgreSQL

- 접근: FastAPI/Jinja 계열 UI와 Python worker로 구성한다.
- 장점:
  - 문서 처리와 도메인 코드가 한 도구 체인에 있고 초기 서비스 수가 가장 적다.
  - OpenAPI client 생성 동기화가 필요 없다.
- 단점:
  - 다중 상태 화면, 업로드 진행, polling, citation highlight/viewer를 구현할 때 프론트
    상호작용 코드가 비정형적으로 커질 수 있다.
  - 후속 대화형 UI 기반과 프론트엔드 계약 검증이 약해진다.

#### 옵션 D — 운영형 분산 구성: Next.js + FastAPI + Celery/Redis + S3/MinIO + vector DB

- 접근: 작업 브로커, 객체 저장소, 벡터 검색을 첫날부터 독립 서비스로 둔다.
- 장점:
  - 수평 확장, 운영형 재시도, 대규모 검색으로 확장하기 쉽다.
  - 각 인프라가 익숙한 운영 경계를 제공한다.
- 단점:
  - 첫 마일스톤에 네 개 이상의 추가 장애 지점과 설정·관찰 비용을 만든다.
  - 현재 최대 20개 파일의 해커톤 범위와 맞지 않고 D1을 악화한다
    (`.omx/plans/prd-meeting-rag-platform.md:87-97`).

### 2.4 권고

**옵션 A를 채택한다.** 단, 옵션 C의 단순성을 보존하기 위해 FastAPI API와 worker가
하나의 Python 애플리케이션 패키지/이미지를 공유하고 실행 entrypoint만 분리한다. 옵션 D의
확장 경계는 `BlobStore`, `JobRepository`, `RetrievalProvider` 인터페이스로만 남기며 Redis,
MinIO, vector DB는 첫 마일스톤에 설치하지 않는다. PostgreSQL `SKIP LOCKED`는 queue형
다중 consumer의 lock 경합 회피 용도로만 사용하고 일반 조회 일관성 수단으로 사용하지 않는다.

## 3. 목표 아키텍처

### 3.1 계획 경로

```text
planned:/
  README.md
  AGENTS.md
  .env.example
  .gitignore
  package.json
  pnpm-workspace.yaml
  pyproject.toml
  uv.lock
  docker-compose.yml
  apps/
    web/
      next.config.ts
      src/app/
      src/features/auth/
      src/features/rooms/
      src/features/submissions/
      src/features/results/
      src/components/source-viewer/
    api/
      alembic/
      app/main.py
      app/api/
      app/domain/
      app/application/
      app/adapters/db/
      app/adapters/blob/
      app/adapters/parsers/
      app/adapters/llm/
      app/worker/
  packages/
    api-client/
    schemas/
  spikes/
    document-ingestion/
  tests/
    fixtures/
    contract/
    integration/
    security/
    e2e/
  docs/
    adr/
    demo-runbook.md
```

- 위 경로는 구현자가 생성할 목표이며 현재 존재 주장으로 해석하지 않는다.
- `apps/api`의 domain/application 코드는 API와 독립 worker가 공유하되, web 요청 프로세스가
  OCR/파싱/LLM을 직접 실행하지 않는다. 무거운 작업은 별도 프로세스/queue가 적합하다는
  FastAPI 공식 caveat와도 일치한다.

### 3.2 구성요소와 책임

| 구성요소 | 책임 | 금지 경계 |
|---|---|---|
| `apps/web` | 로그인, 친구/방/세션, 제출, 처리 상태, 요약/조사, source viewer | DB/blob 직접 접근, 비밀키 보유 |
| FastAPI API | 인증/인가, 상태 전이, 업로드 수신, snapshot/job 생성, 결과 조회 | 요청 안에서 파서/OCR/LLM 실행 |
| Python worker | job lease/heartbeat, parser/OCR, summary/research pipeline | 사용자 cookie 신뢰, 무검증 결과 저장 |
| PostgreSQL | 도메인 데이터, snapshot, anchors, jobs, 결과, web evidence | 원본 파일 bytes 저장 |
| Local `BlobStore` | 무작위 storage key의 원본 저장/stream | web root 노출, 원본명 경로 사용 |
| Provider adapter | mock/xAI 요청·응답 정규화 | 원본 URL/bytes 전송, summary의 web tool |

### 3.3 요청·인증 경계

1. 브라우저는 Next.js 동일 출처의 `/api/*` proxy를 통해 FastAPI를 호출한다.
2. FastAPI가 opaque session cookie, CSRF token, membership/host 정책의 유일한 권위가 된다.
3. 모든 방 리소스는 존재 여부를 노출하기 전에 membership을 검사한다
   (`.omx/plans/prd-meeting-rag-platform.md:43-52`).
4. OpenAPI가 wire contract의 기준이며 `packages/api-client`는 생성물이다
   (`.omx/plans/prd-meeting-rag-platform.md:171-200`).
5. proxy는 신뢰 경계가 아니며 전달된 user/room 헤더를 인증 근거로 사용하지 않는다.

### 3.4 원본·anchor 흐름

1. API가 allowlist/크기/magic 검증 후 임시 파일을 안전한 storage key로 원자 이동하고
   `SourceRevision`의 sha256과 메타데이터를 저장한다.
2. worker가 parser adapter를 선택한다.
   - PDF: text block/page/bbox 추출, 텍스트가 부족한 페이지만 OCR fallback.
   - PNG/JPEG: OCR text/confidence/정규화 bbox.
   - HWPX: ZIP/XML 안전 제한 후 section/paragraph/table-cell 경로.
   - HWP: G0에서 승인된 parser/변환 경로만 사용.
3. 결과는 정규화된 `ExtractedBlock`과 discriminated `SourceAnchor`로 저장한다
   (`.omx/plans/prd-meeting-rag-platform.md:117-137`).
4. HWP/HWPX는 완전한 브라우저 렌더링을 약속하지 않는다. 안전한 구조화 추출 미리보기에서
   section/paragraph/table-cell을 강조하고 원본 다운로드를 병행한다. 이 동작이 요구된
   “동등한 canonical locator” 계약이다.

### 3.5 마감·작업·재시도

1. `open -> closed` 트랜잭션이 현재 ready 리비전을 lock하고 `GenerationSnapshot` 및
   `snapshot_revisions`를 만든다.
2. `snapshot_id + pipeline_version + kind`로 summary/research job의 idempotency key를 만든다.
3. worker는 `FOR UPDATE SKIP LOCKED`로 job을 lease하고 heartbeat를 갱신한다.
4. lease 만료 job만 재획득할 수 있고 성공 결과가 있으면 no-op 한다.
5. summary와 research는 독립 상태를 가지며 둘 다 성공하면 세션이 `ready`가 된다.
6. research 재시도는 summary row/hash를 바꿀 수 없다
   (`.omx/plans/test-spec-meeting-rag-platform.md:41-47`,
   `.omx/plans/test-spec-meeting-rag-platform.md:67-77`).

### 3.6 생성 격리

- `SummaryRequest` 타입에는 snapshot의 extracted block/anchor 외 입력과 tool 설정 필드가
  존재하지 않는다.
- `ResearchRequest`만 web search tool 정책을 가질 수 있다.
- summary와 research는 별도 prompt version, `generation_run`, structured schema, validator,
  repository method를 사용한다.
- 저장 전 validator가 anchor 존재/소속/citation 개수/금지 URL·verdict를 검사한다
  (`.omx/plans/prd-meeting-rag-platform.md:99-115`).
- xAI structured output은 wire 형식 보조 수단일 뿐 신뢰 경계가 아니다. 내부 Pydantic 검증과
  citation resolver 검증이 실패하면 결과를 공개하지 않는다.
- mock adapter는 동일 내부 schema를 반환하며 외부 키 없이 E2E 기준 경로가 된다.

## 4. 의존 순서에 따른 구현 단계

### Phase 0 — 저장소·도구 체인 최소 기반

**대상**: planned `AGENTS.md`, `README.md`, `.gitignore`, `.env.example`, root manifests,
`docker-compose.yml`.

1. Git 저장소를 초기화하고 Lore 형식 commit 규칙을 로컬 `AGENTS.md`에 보존한다.
2. Node/Python/PostgreSQL 버전을 floating tag 없이 고정하고 lockfile을 생성한다.
3. web/api/worker/postgres healthcheck만 있는 최소 Compose를 만든다.
4. lint/typecheck/test 명령이 빈 smoke test에서도 실행되는지 확인한다.

**완료 증거**: Compose config 성공, 각 프로세스 healthcheck, root quality 명령 exit 0.

### Phase 1 — G0 HWP/OCR 차단 spike

**대상**: planned `spikes/document-ingestion/**`, `tests/fixtures/{pdf,hwp,hwpx,images,malicious}/**`,
`docs/adr/0001-document-ingestion.md`.

1. 배포 가능한 골든 HWP/HWPX/PDF/PNG/JPEG fixture를 만든다.
2. Linux worker 컨테이너에서 PDF bbox, OCR bbox/confidence, HWP/HWPX section/paragraph/table
   path를 추출한다.
3. 암호화/손상/zip bomb/XXE/timeout/memory-limit fixture를 실행한다.
4. 각 후보 parser/OCR의 라이선스, 모델 크기, cold start, 한글 정확도, 좌표 안정성을 기록한다.
5. `AnchorSchema` round-trip과 viewer가 소비할 JSON 예시를 고정한다.

**GO 조건**:
- 모든 필수 형식에 stable locator가 생성된다.
- clean Korean OCR 정규화 문자 일치율이 90% 이상이다.
- 악성 fixture가 제한 내에서 거부되고 worker가 살아남는다.
- 채택 라이브러리의 라이선스와 컨테이너 실행이 배포 가능한 것으로 기록된다.

**NO-GO 조건**: 하나라도 실패하면 Phase 2 이후를 시작하지 않고 HWP 지원/변환/데모 fixture
전략을 다시 합의한다 (`.omx/plans/test-spec-meeting-rag-platform.md:15-27`).

### Phase 2 — 도메인·DB·계약 뼈대

**대상**: planned `apps/api/app/{domain,application,adapters/db}/**`, `apps/api/alembic/**`,
`packages/schemas/**`, `packages/api-client/**`.

1. user/friend/room/session/submission/revision/block/anchor/snapshot/job/run/document/citation/evidence
   모델과 제약을 migration으로 만든다
   (`.omx/plans/prd-meeting-rag-platform.md:139-169`).
2. 상태 전이와 membership/host 정책을 순수 domain service로 구현한다.
3. `SourceAnchor`, `SummaryResult`, `ResearchResult`, `CitationTarget`,
   `ConversationMessage` JSON schema를 고정한다.
4. OpenAPI snapshot과 생성 TypeScript client freshness 검사를 연결한다.

**완료 증거**: migration up/down/up, schema fixture round-trip, 상태/권한 단위 행렬 통과.

### Phase 3 — 인증·친구·방·전달형 세션

**대상**: planned `apps/api/app/api/{auth,friends,rooms,sessions}.py`,
`apps/web/src/features/{auth,rooms}/**`.

1. Argon2id password, hash 저장 opaque session, 로그인 token rotation, logout/expiry를 구현한다.
2. CSRF double-submit 또는 동등한 server-validated token 계약을 모든 mutation에 적용한다.
3. 친구 요청/수락/거절, 방 생성/초대/멤버십, 전달형 세션 생성/열람을 구현한다.
4. 비구성원 IDOR과 host-only 상태 전이를 API integration test로 고정한다.

**완료 증거**: Alice/Bob/Eve 권한 fixture와 cookie/CSRF 보안 테스트 통과.

### Phase 4 — 제출·원본·추출 파이프라인

**대상**: planned `apps/api/app/api/submissions.py`,
`apps/api/app/adapters/{blob,parsers}/**`, `apps/api/app/worker/**`,
`apps/web/src/features/submissions/**`.

1. 텍스트/파일 제출과 마감 전 revision 교체를 구현한다.
2. size/count/page/pixel/MIME/magic/filename/zip/XML 제한을 구현한다.
3. G0에서 승인된 parser를 adapter로 승격하고 extraction job에 연결한다.
4. 원본 다운로드, 안전한 추출 미리보기, 실패/낮은 OCR confidence UI를 구현한다.

**완료 증거**: 필수·악성 fixture, path traversal, parser timeout, 원본 보존 테스트 통과.

### Phase 5 — 마감 스냅샷·PostgreSQL worker queue

**대상**: planned `apps/api/app/application/close_session.py`,
`apps/api/app/adapters/db/jobs.py`, `apps/api/app/worker/runner.py`.

1. close/submission 경쟁을 단일 트랜잭션과 row lock으로 해결한다.
2. snapshot revision과 topic/pipeline version을 불변 복사한다.
3. lease/heartbeat/attempt/error/idempotency를 가진 DB queue를 구현한다.
4. 두 worker 경쟁, lease 만료, 중복 close/retry를 검증한다.

**완료 증거**: concurrency integration test에서 정확히 한 snapshot/논리 결과만 생성된다.

### Phase 6 — summary/research provider와 검증

**대상**: planned `apps/api/app/adapters/llm/**`,
`apps/api/app/application/{generate_summary,generate_research}.py`,
`tests/fixtures/llm/**`.

1. mock provider를 먼저 구현하고 4개 팩트체크 verdict fixture를 고정한다.
2. summary map/reduce가 anchor ID를 보존하도록 구현한다.
3. research question/claim selection/web evidence normalization을 구현한다.
4. xAI adapter는 키가 있을 때만 활성화하고 summary에는 web tool을 제공하지 않는다.
5. 저장 전 structured output, anchor, snapshot ownership, citation, contamination을 검증한다.

**완료 증거**: hallucinated anchor 거부, citation 없는 item 거부, 의견 claim 제외,
summary hash 불변, mock E2E 통과.

### Phase 7 — 결과·citation resolver·viewer UX

**대상**: planned `apps/api/app/api/results.py`,
`apps/web/src/features/results/**`, `apps/web/src/components/source-viewer/**`.

1. 원본/요약/조사 세 계층을 시각적으로 분리한다.
2. citation resolver가 membership을 재검사하고 source anchor 또는 web evidence를 반환한다.
3. PDF/image bbox와 HWP/HWPX 구조화 locator를 강조한다.
4. 부분 완료/실패/재시도 상태와 low-confidence 경고를 표시한다.
5. `ConversationMessage`와 `chat_message` anchor는 contract test만 제공하고 채팅 UI는 만들지 않는다.

**완료 증거**: 모든 골든 citation deep link와 권한 거부 Playwright 시나리오 통과.

### Phase 8 — 보안·평가·데모 고정

**대상**: planned `tests/{security,e2e}/**`, `docs/demo-runbook.md`.

1. G1–G6 전체 gate를 순서대로 실행한다.
2. seed 계정과 다중 형식 demo fixture로 핵심 여정을 문서화한다.
3. 로그 redaction, correlation ID, stage duration/attempt/citation failure metric을 검증한다.
4. mock 경로 10회 반복과 optional non-blocking xAI smoke를 분리한다.

**완료 증거**: `.omx/plans/test-spec-meeting-rag-platform.md:15-205`의 모든 blocking gate가
통과하고 demo runbook을 새 환경에서 재현한다.

## 5. 테스트 가능한 승인 기준

| ID | 기준 | 검증 |
|---|---|---|
| AC-01 | 친구가 아닌 사용자는 방 초대 후보가 아니다 | API integration |
| AC-02 | 비구성원의 room/session/source/result 직접 접근은 403/404다 | security + E2E |
| AC-03 | host만 close/retry할 수 있고 마감 후 제출/교체는 거부된다 | unit + integration |
| AC-04 | text/PDF/HWP/HWPX/PNG/JPEG 원본을 저장·재열람한다 | integration + E2E |
| AC-05 | 필수 형식마다 승인된 native anchor가 생성·round-trip된다 | G0 + unit |
| AC-06 | clean Korean OCR fixture 문자 일치율은 90% 이상이다 | evaluation |
| AC-07 | 실패/저신뢰 원본은 삭제되지 않고 상태·이유를 표시한다 | integration + E2E |
| AC-08 | close/submission 경쟁에서 일관된 한 상태만 승리한다 | concurrency integration |
| AC-09 | 동일 idempotency key 재시도는 새 논리 결과를 만들지 않는다 | integration |
| AC-10 | 저장된 citation resolver 성공률은 100%다 | evaluation |
| AC-11 | 다른 snapshot/revision을 가리키는 citation은 0건이다 | unit + integration |
| AC-12 | summary item은 모두 1개 이상 원본 citation을 가진다 | schema + evaluation |
| AC-13 | summary payload의 web URL/fact-check verdict 혼입은 0건이다 | contamination fixture |
| AC-14 | research 문장은 web evidence를, fact-check는 원문+web evidence를 가진다 | contract + E2E |
| AC-15 | opinion/value judgment fixture는 claim 후보에서 제외된다 | unit |
| AC-16 | research 실행/재시도 전후 summary DB payload/hash는 같다 | integration + E2E |
| AC-17 | xAI request DTO에 original bytes/URL/storage key가 없다 | unit + captured smoke |
| AC-18 | `XAI_API_KEY` 없이 mock 전체 여정이 성공한다 | blocking E2E |
| AC-19 | mock E2E 10회 반복 실패는 0회다 | stability run |
| AC-20 | `chat_message` anchor와 message contract가 존재하되 chat UI/실시간 전송은 없다 | contract + scope audit |

이 기준은 기존 승인 항목을 실행 단위로 정규화한 것이다
(`.omx/specs/deep-interview-meeting-rag-platform.md:171-210`).

## 6. 위험과 완화

| 위험 | 조기 신호 | 예방/완화 | 중단 조건 |
|---|---|---|---|
| HWP/HWPX 좌표 또는 라이선스 실패 | table/footnote locator 불안정, Linux 미지원 | Phase 1 G0, 골든 fixture, 후보별 ADR | G0 NO-GO |
| OCR 정확도/자원 초과 | 90% 미만, timeout/OOM | page-level fallback, 해상도/pixel 제한, confidence 노출 | 필수 fixture 실패 |
| summary에 외부 정보 혼입 | URL/verdict/근거 없는 문장 | 별도 DTO/tool/run/repository + 저장 전 validator | contamination 1건 |
| 깨진/권한 우회 citation | resolver 실패 또는 타 방 anchor | immutable revision, snapshot ownership, resolver membership | resolver <100% |
| close/retry race | 중복 snapshot/result | DB lock, unique idempotency, concurrency test | 중복 1건 |
| xAI API/쿼터/형식 변경 | smoke 실패, schema mismatch | mock blocking 경로, adapter, 내부 validation | mock 실패 시 release 중단 |
| 해커톤 범위 팽창 | 채팅/내보내기/관리자 요청 유입 | scope audit와 change-control | 별도 승인 전 착수 금지 |

## 7. Deliberate pre-mortem

### 실패 시나리오 1 — “데모 전날 HWP 자료가 열리지만 인용이 엉뚱한 문단으로 이동한다”

- 원인: parser가 추출 순서만 저장하고 section/table 구조를 안정 ID로 고정하지 않았다.
- 조기 신호: 동일 파일 재처리 시 anchor JSON/hash가 바뀌거나 표/각주 fixture가 누락된다.
- 예방: G0에서 재실행 안정성, table-cell path, fixture snapshot을 승인 조건으로 둔다.
- 복구: 일반 구현을 멈추고 HWP adapter를 교체하거나 요구를 다시 합의한다. 임의 줄 번호로
  대체하거나 잘못된 citation을 공개하지 않는다.

### 실패 시나리오 2 — “요약본이 참가자의 틀린 주장을 외부 지식으로 조용히 정정한다”

- 원인: summary와 research가 prompt만 다르고 tool/context/저장 경계를 공유했다.
- 조기 신호: summary fixture에 URL, verdict, 외부 고유명사 또는 citation 없는 보충 문장이 나타난다.
- 예방: 별도 request 타입, no-tool summary provider, 독립 run/repository, contamination validator.
- 복구: 해당 결과를 `failed_validation`으로 격리하고 공개하지 않으며 같은 snapshot에서
  prompt/validator 버전을 올려 재실행한다.

### 실패 시나리오 3 — “마감 버튼 중복 클릭과 worker 재시작으로 결과가 두 벌 생긴다”

- 원인: snapshot/job/result uniqueness와 lease 상태 전이가 애플리케이션 관례에만 의존했다.
- 조기 신호: concurrency test에서 worker 둘이 같은 job을 처리하거나 retry가 새 run을 만든다.
- 예방: transaction lock, DB unique key, lease/heartbeat, 성공 no-op, 반복 race test.
- 복구: 새 결과 생성을 중단하고 canonical run을 unique constraint로 확정한 뒤 orphan을 감사
  기록과 함께 정리한다.

## 8. Expanded Test Plan

### Unit

- 상태 전이/권한 행렬, idempotency key, lease expiry.
- parser adapter와 모든 anchor variant schema round-trip.
- summary/research DTO의 도구 정책과 비밀/원본 필드 부재.
- hallucinated anchor, citation 없음, verdict enum 오류, opinion claim 필터.
- payload/log redactor와 filename/storage-key 정규화.

### Integration

- 실제 PostgreSQL migration up/down/up, unique/FK/transaction lock.
- 공유 local blob volume의 stream/download/path traversal.
- API와 독립 worker process, 두 worker `SKIP LOCKED`, lease reclaim.
- close와 동시 submission race, retry와 summary hash 불변.
- parser subprocess/container timeout·memory·network 제한.
- mock provider에서 normalized document/citation persistence까지.

### Contract

- FastAPI OpenAPI snapshot과 generated TypeScript client freshness.
- `SummaryResult`, `ResearchResult`, `CitationTarget`, 모든 `SourceAnchor` fixture.
- `ConversationMessage`/`chat_message`의 후속 호환 계약.
- xAI adapter response를 내부 schema로 정규화하는 recorded fixture.

### E2E

- Alice/Bob 친구·초대·다중 제출·마감·ready·인용 deep link.
- Eve IDOR, Bob의 타인 revision 교체/close 거부, CSRF/expired session.
- 손상 HWP 제외 전 close 차단, timeout 후 same-snapshot retry.
- 의도적으로 틀린 participant claim이 summary에서는 원문 관점으로 남고 research에서만
  fact-check되는 출력 격리.
- mock 경로 10회 반복; 외부 xAI smoke는 키가 있을 때만 비차단으로 실행.

### Observability

- 구조화 로그 필수 필드: correlation ID, job/snapshot/stage, duration, attempt, error code.
- 금지 필드: password, cookie/token, API key, original/extracted raw content.
- 집계 가능 카운터: jobs by state, parser failure type, generation duration,
  citation validation failure, provider token usage.
- 실패 UI가 retryable/non-retryable 이유를 노출하는지 E2E로 확인한다
  (`.omx/plans/test-spec-meeting-rag-platform.md:166-185`).

## 9. 검증 순서와 명령 계약

```bash
# G0 — 선택된 spike 명령은 docs/adr/0001-document-ingestion.md에 고정
uv run pytest spikes/document-ingestion

# G1/G2
pnpm lint
pnpm typecheck
pnpm test
uv run ruff check .
uv run mypy apps/api
uv run pytest -m "not integration and not e2e"

# G3/G4
docker compose config
docker compose up -d --build
uv run pytest -m "integration or security"

# G5/G6
pnpm playwright test
uv run pytest -m evaluation
```

검증은 G0 → 정적 → unit/contract → integration → security → E2E/evaluation 순서이며 앞 gate가
실패하면 뒤 gate를 release 근거로 사용하지 않는다. 실제 외부 xAI smoke는
`XAI_API_KEY`가 명시된 환경에서만 별도 실행한다
(`.omx/plans/test-spec-meeting-rag-platform.md:187-205`).

## 10. ADR

### Decision

Next.js App Router web과 하나의 공유 Python 패키지에서 분리 실행되는 FastAPI API/worker,
PostgreSQL DB/lease queue, local-volume `BlobStore`, mock/xAI provider adapter를 가진 경량
폴리글랏 모노레포를 채택한다. provenance-first anchor와 summary/research의 구조적 격리를
핵심 아키텍처 불변식으로 둔다.

### Drivers

1. 해커톤 기간 안의 HWP/OCR/비동기 파이프라인 완주 가능성.
2. 100% resolvable citation과 0건 summary contamination.
3. 비공개 원본과 제3자 전송 최소화라는 보안 경계.

### Alternatives considered

- 단일 TypeScript Next.js/Node 구성.
- 단일 Python FastAPI/서버 렌더링 구성.
- Redis/Celery/S3/vector DB를 포함한 운영형 분산 구성.

### Why chosen

Python 문서 처리와 현대적 상호작용 UI를 각 생태계가 강한 경계에 배치하면서도, PostgreSQL과
공유 Python 패키지로 추가 인프라·중복을 억제한다. G0가 핵심 형식 위험을 먼저 제거하며,
mock provider가 외부 API를 release blocker에서 분리한다.

### Consequences

- Node/Python 두 lockfile과 OpenAPI 생성 client freshness를 CI가 관리해야 한다.
- API와 worker는 같은 코드 이미지를 공유하지만 반드시 별도 프로세스로 운영한다.
- PostgreSQL queue는 현재 규모의 의도적 선택이며 장기 고처리량 보장은 하지 않는다.
- HWP/HWPX viewer는 native 앱 렌더링이 아니라 구조화된 canonical locator 미리보기다.
- vector retrieval은 자료 규모/검색 품질 근거가 생길 때만 후속 ADR로 도입한다.

### Follow-ups

1. G0 결과로 parser/OCR 라이브러리와 정확한 라이선스를 `ADR-0001`에 확정한다.
2. 첫 E2E 후 PostgreSQL queue latency와 worker memory를 기록한다.
3. 실제 xAI smoke 후 모델명/응답 schema/tool 비용을 provider ADR에 pin한다.
4. 대화형 구현 전 `chat_message` snapshot/종료 의미를 별도 PRD로 합의한다.
5. 외부 배포 전 object storage, malware scanning, retention/deletion, 운영 auth를 재설계한다.

## 11. 사용 가능한 agent type roster

현재 설치된 역할 카탈로그에서 사용할 수 있는 agent type은 다음과 같다.

- 탐색/요구/계획: `explore`, `analyst`, `planner`, `product-manager`, `researcher`
- 설계/비평: `architect`, `critic`, `api-reviewer`, `dependency-expert`
- 구현: `executor`, `team-executor`, `designer`, `build-fixer`, `debugger`
- 테스트/검증: `test-engineer`, `verifier`, `qa-tester`, `security-reviewer`,
  `performance-reviewer`, `quality-reviewer`, `quality-strategist`, `code-reviewer`
- 품질/전달: `style-reviewer`, `code-simplifier`, `writer`, `git-master`
- 제품/UX: `ux-researcher`, `information-architect`, `product-analyst`, `vision`

역할이 없는 임의 agent type을 만들지 않는다. Team runtime은 한 번의 launch에서 공통
`agentType`을 쓰므로 세부 전문성은 leader가 task assignment로 부여한다.

## 12. 실행 후속 staffing

### 12.1 `$ralph` 순차 지속 실행 권고

- 주 소유자: `executor` 1명, reasoning **high** — Phase 0/G0부터 dependency gate를 유지.
- 병렬 구현 보조: `executor` 최대 3명, reasoning **high** — backend domain/ingestion,
  web/viewer, provider/output isolation.
- 회귀 증거: `test-engineer` 1명, reasoning **high** — 테스트를 기능보다 먼저 또는 함께 고정.
- 보안 pass: `security-reviewer` 1명, reasoning **high** — auth/IDOR/upload/parser/provider 경계.
- 최종 sign-off: 구현에 참여하지 않은 `architect` 또는 `verifier` 1명, reasoning **high**.
- 시각 UI가 생긴 뒤 `designer`/`ux-researcher`를 **medium**으로 한정 투입한다.

Ralph는 G0가 NO-GO면 구현을 계속하지 않고 재계획 상태로 전환해야 한다. 최종 단계에는
changed-files deslop, 전체 회귀 재검증, Architect sign-off가 포함된다.

### 12.2 `$team` 병렬 실행 권고

**권고 규모**: leader + `4:executor` workers.

1. Lane A, reasoning high: repository/domain/DB/auth/API.
2. Lane B, reasoning high: G0 승인 후 ingestion/parser/worker/blob.
3. Lane C, reasoning medium-high: web flow/result/viewer/generated client.
4. Lane D, reasoning high: tests/security/evaluation/observability; 기능 lane의 자체 승인 금지.

Phase 0의 Git 초기화와 baseline Lore commit, Phase 1 G0 GO 판정은 leader가 먼저 보장한다.
그 뒤 Phase 2–4의 독립 작업을 병렬화하고 Phase 5–8은 계약/DB 선행 조건을 확인하며 합친다.
공유 migration/OpenAPI/schema 파일은 한 시점에 한 lane만 소유한다.

### 12.3 Launch hints

승인 계획이 `.omx/plans/ralplan-meeting-rag-platform.md`로 확정된 뒤에만 실행한다.

```bash
# 지속 단일-owner 경로
$ralph ".omx/plans/ralplan-meeting-rag-platform.md를 Phase 0부터 gate 순서대로 구현하고 검증"

# tmux Team 경로 — Git baseline과 G0 GO 이후
omx team 4:executor "Execute .omx/plans/ralplan-meeting-rag-platform.md from Phase 2; preserve G0 decision, assign one independent verification lane, and stop only after G1-G6 evidence"

# 동일한 skill 표면
$team 4:executor "Execute .omx/plans/ralplan-meeting-rag-platform.md from Phase 2 with delivery, security, and independent verification lanes"
```

Team 실행 전 `tmux`, `$TMUX`, `omx`, Git baseline을 preflight하고, 실행 중
`omx team status <team-name>` 또는 `omx team await ...`로 terminal 상태까지 감시한다.

## 13. Team verification path

1. **시작 증거**: team name, tmux pane, worker ACK, task ownership을 기록한다.
2. **각 phase 증거**: 담당 lane은 변경 파일, Lore commit, 실행 명령, 원문 결과를 leader에게
   전달한다.
3. **독립 verification lane**: 구현 lane과 다른 worker가 migration, contract, security,
   E2E/evaluation을 실행하고 실패를 task로 되돌린다.
4. **통합 gate**: leader는 pending/in-progress/failed가 0인지, G0–G6 증거가 모두 있는지,
   summary hash/contamination/citation 정량 기준을 확인한다.
5. **Team 종료**: terminal 상태 전에 `omx team shutdown`을 호출하지 않는다.
6. **후속 Ralph 조건**: Team 종료 후 flaky failure, 미해결 보안 finding, 데모 재현 실패가
   하나라도 남으면 별도 `$ralph` 단일-owner fix/verification loop를 시작한다.
7. **최종 proof**: fresh lint/typecheck/unit/integration/security/E2E/evaluation과 독립
   Architect/Verifier 승인이 없으면 완료로 선언하지 않는다.

## 14. 실행 guardrails

- 이 합의 계획 단계에서는 애플리케이션 코드, 의존성, 외부 서비스, Git 저장소를 생성하지 않는다.
- 계획 승인 후에도 G0 실패 시 scope를 조용히 축소하지 말고 재합의한다.
- 유료 xAI 호출, 실제 배포, credential 저장은 별도 승인 없이는 수행하지 않는다.
- 기존 PRD/test-spec의 출력 격리와 비목표를 바꾸는 구현 편의 변경을 금지한다.
- 테스트를 삭제·완화해 gate를 통과시키지 않는다.
- 외부 공식 문서와 라이브러리 버전은 실제 설치 직전 다시 확인하고 lockfile/ADR에 pin한다.

## 15. 공식 기술 근거

- xAI Web Search: <https://docs.x.ai/developers/tools/web-search>
- xAI Citations: <https://docs.x.ai/developers/tools/citations>
- xAI Structured Outputs: <https://docs.x.ai/developers/model-capabilities/text/structured-outputs>
- FastAPI Background Tasks caveat: <https://fastapi.tiangolo.com/tutorial/background-tasks/>
- PostgreSQL `SKIP LOCKED`: <https://www.postgresql.org/docs/current/sql-select.html>
- Next.js App Router: <https://nextjs.org/docs/app>
- PyMuPDF text blocks/bbox: <https://pymupdf.readthedocs.io/en/latest/app1.html>
- PaddleOCR: <https://www.paddleocr.ai/main/en/index.html>
- Hancom 공개 HWP/OWPML 형식: <https://www.hancom.com/support/downloadCenter/hwpOwpml>

## 16. 초안 변경 기록

- 이전 PRD와 deliberate test-spec을 하나의 dependency-ordered 실행 계획으로 통합했다.
- RALPLAN-DR 원칙, 동인, 네 가지 대안과 선택 근거를 추가했다.
- G0를 일반 구현 전 blocking phase로 명시하고 HWP viewer 의미를 canonical locator로 좁혔다.
- same-origin auth proxy, DB queue, summary/research 격리, planned path를 구체화했다.
- ADR, 전체 agent roster, Ralph/Team staffing, launch hint, Team verification 경로를 추가했다.
