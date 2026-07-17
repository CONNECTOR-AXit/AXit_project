# Test Specification — 회의 사전 브리핑 RAG 플랫폼

- 상태: Ralplan consensus 승인 (`.omx/plans/ralplan-meeting-rag-platform.md`)
- 대상 PRD: `.omx/plans/prd-meeting-rag-platform.md`
- 요구 기준: `.omx/specs/deep-interview-meeting-rag-platform.md:171-210`

## 1. 검증 원칙

1. 모든 생성 인용은 구조적으로 resolve되어야 한다.
2. 요약과 조사의 격리는 프롬프트 관례가 아니라 타입·도구·저장 경계·테스트로 증명한다.
3. 외부 Grok 호출 없이 대부분의 테스트가 결정론적으로 실행되어야 한다.
4. 업로드 파서는 비신뢰 입력으로 취급한다.
5. 마감 스냅샷과 재시도는 동시성 테스트로 증명한다.

## 2. 품질 게이트

| Gate | 조건 |
|---|---|
| G0 HWP/OCR spike | 골든 HWP/HWPX/PDF/PNG/JPG에서 텍스트와 anchor를 추출하고 라이선스/런타임 제약을 기록 |
| G1 정적 품질 | web lint/typecheck, api lint/typecheck, migration 검증 통과 |
| G2 단위 | 도메인·parser·citation·provider 단위 테스트 통과 |
| G3 통합 | PostgreSQL, blob store, job worker, mock provider 통합 테스트 통과 |
| G4 보안 | 권한/CSRF/업로드 악성 fixture/secret leakage 테스트 통과 |
| G5 E2E | 핵심 여정과 실패/재시도 Playwright 시나리오 통과 |
| G6 평가 | citation resolution 100%, summary contamination 0, 필수 fixture 기준 충족 |

G0가 실패하면 일반 구현을 진행하지 않고 HWP 지원 전략을 다시 계획한다.

## 3. 테스트 계층

### 3.1 Unit

#### 상태와 권한

- 세션 상태 전이 허용/거부 행렬
- 주최자만 close/retry 가능
- 비구성원/탈퇴 구성원 리소스 접근 거부
- 친구가 아닌 사용자의 방 초대 거부
- 마감 후 제출/교체 거부

#### 스냅샷과 작업

- 마감 시 현재 리비전만 snapshot join에 포함
- 같은 idempotency key의 job 중복 생성 방지
- worker lease 만료 후 안전한 재획득
- 성공 결과가 있는 job 재실행 시 no-op
- research 재시도가 summary row를 변경하지 않음

#### Parser/anchor

- PDF text block -> page/block/bbox
- scanned PDF -> page/image bbox + OCR confidence
- PNG/JPEG -> normalized bbox
- HWP/HWPX -> section/paragraph/table-cell path
- anchor JSON schema round-trip
- 잘못된 좌표/다른 revision anchor 거부

#### LLM/provider

- summary request DTO에 web tool과 원본 bytes/URL이 없음
- research request만 web search tool을 가짐
- unknown/hallucinated anchor ID output 거부
- citation 없는 summary item 거부
- fact-check verdict enum 외 값 거부
- 의견/가치판단 fixture가 claim 후보에서 제외

### 3.2 Integration

- Alembic up/down/up 및 빈 DB bootstrap
- 회원/친구/방 unique·FK·권한 제약
- 로컬 blob 저장/stream/download, path traversal 차단
- PostgreSQL `FOR UPDATE SKIP LOCKED` 기반 worker 경쟁: job 하나를 worker 하나만 실행
- close 트랜잭션과 동시 제출 경쟁: 제출 또는 snapshot 중 하나만 일관되게 승리
- parser worker subprocess timeout/메모리 제한
- mock Grok response -> normalized documents/citations
- source revision rename 후에도 citation resolve
- web evidence URL/title/accessed_at/snippet_hash 저장

### 3.3 Contract

- FastAPI OpenAPI schema snapshot
- 생성된 TypeScript client가 CI에서 최신인지 검증
- `SummaryResult`, `ResearchResult`, `CitationTarget` JSON schema fixture
- 향후 `ConversationMessage`와 `chat_message` anchor contract

### 3.4 E2E

#### E2E-01 핵심 성공

1. Alice 로그인, Bob 친구 수락, 방 초대.
2. 전달형 세션 생성.
3. PDF/HWP/PNG/JPG와 텍스트 의견 제출.
4. 모든 원본이 방 구성원에게 보임.
5. 마감, processing, ready.
6. 요약 인용이 각 원본 위치로 이동.
7. 조사 URL과 팩트체크 원문+웹 인용 확인.

#### E2E-02 권한

- Eve가 room/session/source/result URL을 직접 호출하면 404 또는 403.
- Bob이 Alice 제출을 교체하거나 세션을 마감하면 거부.
- 로그아웃/만료 세션 mutation 거부.

#### E2E-03 실패 복구

- 손상 HWP가 `failed`로 보이고 원본 다운로드는 가능.
- host가 실패 원본을 제외하기 전 close는 차단.
- mock Grok timeout 후 same snapshot retry로 ready.
- 중복 close/retry 클릭이 결과 중복을 만들지 않음.

#### E2E-04 출력 격리

- 참가자 원문에 의도적으로 틀린 사실을 넣는다.
- 요약은 그 발언을 참가자 의견으로만 요약하고 정정하지 않는다.
- 조사본은 별도 fact-check에서만 `refuted`와 웹 근거를 표시한다.
- summary DB payload/hash는 research 전후 동일하다.

## 4. 골든 fixture

| Fixture | 목적 |
|---|---|
| `pdf/text-korean.pdf` | 텍스트 block/page/bbox |
| `pdf/scanned-korean.pdf` | OCR fallback과 page bbox |
| `hwp/simple.hwp` | HWP section/paragraph |
| `hwp/table-footnote.hwp` | 표/각주와 실패 경계 |
| `hwpx/simple.hwpx` | ZIP/XML 안전 파싱 |
| `images/korean-clean.png` | 한국어 OCR |
| `images/rotated-low-confidence.jpg` | confidence warning |
| `malicious/zip-bomb.hwpx` | 압축 비율 차단 |
| `malicious/xxe.hwpx` | XML 외부 엔터티 차단 |
| `llm/summary-grounded.json` | 정상 인용 |
| `llm/summary-hallucinated-anchor.json` | anchor 거부 |
| `llm/research-four-verdicts.json` | 4개 팩트체크 상태 |

실제 저작권 문서를 fixture로 커밋하지 않고 직접 생성하거나 배포 가능한 샘플만 사용한다.

## 5. 정량 기준

- 모든 저장된 citation의 resolver 성공률: 100%
- 다른 revision/session을 가리키는 citation 허용: 0건
- 요약 item 중 citation 없는 항목: 0건
- summary fixture에서 web URL/팩트체크 verdict 혼입: 0건
- 깨끗한 한국어 OCR fixture의 정규화 문자 일치율: 90% 이상
- E2E mock 경로 flaky 재실행 10회 중 실패: 0회
- secret/raw content 로그 탐지: 0건
- 작은 데모 fixture(5개 파일, 20페이지 이하)의 mock 전체 처리: 로컬 기준 120초 이내를 경고 기준으로 관찰

OCR 정확도와 시간 기준은 CI 하드웨어 편차가 크므로 G0에서 기준 장비를 기록하고, 기능 게이트와 성능 경고를 구분한다.

## 6. 보안 테스트

- 세션 fixation: 로그인 때 token 회전
- 쿠키: HttpOnly/SameSite, 운영 설정의 Secure
- CSRF 없는 mutation 거부
- filename `../`, NUL, leading dot/hyphen 정규화
- extension/MIME mismatch 거부
- polyglot/손상 이미지 디코딩 실패
- 업로드가 web root에 생성되지 않음
- 원본 다운로드의 membership 검사
- parser container/process 네트워크 차단
- oversized file/page/pixel/zip ratio 제한
- XML DTD/entity 차단
- Grok payload에 storage_key/original_url/file_bytes 부재
- 로그/에러 응답에 원문, stack secret, API key 부재

## 7. Expanded Test Plan

### Unit

도메인 상태, 권한 정책, parser adapter, anchor schema, citation validator, payload redactor, provider normalizer를 순수 단위로 검증한다.

### Integration

실제 PostgreSQL과 로컬 blob store, 별도 worker process, parser binary/model을 사용한다. Grok은 녹화된 구조화 fixture를 사용한다.

### E2E

Playwright로 브라우저 사용자 여정, 파일 업로드, 작업 polling, viewer 딥링크, 권한 거부, 재시도를 검증한다.

### Observability

- 모든 job에 correlation ID, snapshot ID, stage, duration, attempt를 남긴다.
- 원문 없는 구조화 로그를 테스트한다.
- `jobs_by_state`, `parser_failures_by_type`, `generation_duration`, `citation_validation_failures` 카운터를 집계 가능하게 기록한다.
- failed job UI는 재시도 가능/불가능 이유를 표시한다.

## 8. 외부 Grok smoke test

`XAI_API_KEY`가 명시적으로 제공된 환경에서만 수동/비차단으로 실행한다.

1. 작은 추출 텍스트 조각으로 summary structured output 확인.
2. web search가 URL citation metadata를 반환하는지 확인.
3. 요청 body에 원본 파일/URL이 없는지 capture.
4. provider response를 내부 schema로 정규화.

키가 없거나 quota가 없으면 skip하고 mock E2E를 통과 기준으로 사용한다.

## 9. 검증 명령 계약

```bash
pnpm lint
pnpm typecheck
pnpm test
uv run ruff check .
uv run mypy apps/api
uv run pytest
docker compose config
pnpm playwright test
```

최종 검증은 unit -> integration -> security -> E2E -> optional Grok smoke 순으로 실행한다.
