# RALPLAN-DR 승인 실행 계획 — 회의 사전 브리핑 RAG 플랫폼

- 상태: **Critic APPROVE — consensus iteration 3**
- 모드: deliberate consensus
- 구현: 미시작
- 범위: 참여자 전달형 완성 + 대화형 공통 계약 기반
- 입력: `.omx/specs/deep-interview-meeting-rag-platform.md`,
  `.omx/plans/prd-meeting-rag-platform.md`,
  `.omx/plans/test-spec-meeting-rag-platform.md`
- 이전 검토: `.omx/reviews/architect-meeting-rag-platform-v1.md`,
  `.omx/reviews/critic-meeting-rag-platform-v1.md`,
  `.omx/reviews/architect-meeting-rag-platform-v2.md`,
  `.omx/reviews/critic-meeting-rag-platform-v2.md`

`planned:` 경로는 아직 존재하지 않는 구현 대상이다. 현재 저장소에는 빈 `README.md`와
`.omx` 산출물만 있고 Git·코드·실행 가능한 테스트가 없다
(`.omx/context/meeting-rag-platform-20260716T080912Z.md:14-37`,
`.omx/plans/ralplan-checkpoint-meeting-rag-platform.md:3-29`).

## 1. 결과·범위 계약

1. 친구/초대 기반 비공개 방에서 참가자가 텍스트 또는 PDF/HWP/HWPX/PNG/JPEG를 제출하고,
   구성원은 원본과 처리 상태를 본다
   (`.omx/specs/deep-interview-meeting-rag-platform.md:40-72`).
2. submit/replace/close가 동일 세션 aggregate에서 직렬화되며, host의 마감은 정확한
   source revision·extraction run·anchor schema를 불변 snapshot으로 고정한다.
3. 요약본은 snapshot 원본만 사용하고 atomic item마다 exact supporting span과 server-issued
   anchor를 가진다. 웹 정보, 팩트체크 판정, 행동 제안은 금지한다
   (`.omx/specs/deep-interview-meeting-rag-platform.md:98-106`).
4. 별도 조사본만 topic web research와 check-worthy participant claim fact-check를 수행하며
   participant anchor와 web evidence를 함께 보존한다
   (`.omx/specs/deep-interview-meeting-rag-platform.md:108-123`).
5. citation resolver는 membership과 snapshot/revision/extraction-run 소속을 서버에서
   재검증한 뒤 원본 위치 또는 안전한 web URL을 반환한다
   (`.omx/specs/deep-interview-meeting-rag-platform.md:125-151`).
6. xAI/Grok은 교체 가능한 provider이며 필요한 추출 조각만 받는다. 키가 없어도 동일 내부
   schema의 mock으로 blocking E2E가 성공해야 한다
   (`.omx/specs/deep-interview-meeting-rag-platform.md:153-159`,
   `.omx/specs/deep-interview-meeting-rag-platform.md:201-205`).
7. 음성·영상, 공개 링크/내보내기, 공동편집, 네이티브 앱, 과금, 완성 chat UI/실시간 전송,
   운영형 HA/규정 준수는 제외한다
   (`.omx/specs/deep-interview-meeting-rag-platform.md:74-82`).
8. 외부 배포·유료 자원·credential 저장·원본 제3자 업로드·출력 경계 변경은 별도 승인 없이는
   실행하지 않는다 (`.omx/specs/deep-interview-meeting-rag-platform.md:212-228`).

## 2. RALPLAN-DR

### 2.1 원칙

1. **출처 우선**: 원본/추출/anchor/result를 append-only version으로 연결한다.
2. **출력 격리**: summary와 research를 타입·도구·run·validator·저장 경계에서 분리한다.
3. **해커톤 최소 인프라**: blocking 품질에 필요하지 않은 서비스·추상화를 추가하지 않는다.
4. **실패 가시성**: 제외·실패·부분 완료·재시도 가능성을 감사 가능하게 노출한다.
5. **결정론적 검증**: 외부 키 없이 보안·동시성·grounding·citation을 반복 재현한다.

### 2.2 상위 동인

1. **D1 데모 완주**: HWP/OCR, proxy/auth, 비동기 작업 위험을 가장 이른 gate에서 폭로한다.
2. **D2 감사 가능성**: citation resolution 100%, 타 snapshot anchor 0건, summary
   contamination 0건을 지킨다
   (`.omx/plans/test-spec-meeting-rag-platform.md:137-147`).
3. **D3 신뢰 경계**: private-room authz, untrusted parser, stale worker, 최소 외부 전송을
   구조적으로 통제한다 (`.omx/plans/prd-meeting-rag-platform.md:202-211`).

### 2.3 대안

| 대안 | 장점 | 비용/위험 |
|---|---|---|
| **A. Next.js thin shell + FastAPI/Python core/worker + PostgreSQL** | Python 문서 처리, 상호작용 viewer, web/backend 병렬화 | 두 toolchain, proxy/cookie, generated client |
| **B. Next.js/Node 단일 언어 + Node worker** | 한 언어와 빠른 UI/API 타입 공유 | HWP/PDF/OCR에서 Python sidecar가 재등장하거나 기능 위험 증가 |
| **C. FastAPI + server-rendered UI + 최소 JS** | same-origin·한 toolchain, proxy/client generation 제거, 데모 위험 최소 | 복잡한 viewer/polling UX와 후속 chat 기반이 약함 |
| **D. Redis/Celery + S3/MinIO + vector DB 포함** | 운영 확장 경계 | 현재 20-file demo에 과도한 장애·설정 면적 |

**Option C steelman**: 현재 MVP는 CRUD/upload/polling/result comparison/highlight이고 완성
chat UI는 비목표다. 팀에 Next owner가 없거나 same-origin proxy smoke가 실패하면 C가
원칙 3과 D1에 더 일관적이다.

### 2.4 결정과 전환 trigger

Option A를 조건부 채택한다. Phase 0에서 다음 proof를 모두 통과하고 전담 web owner가
지정되어야 유지한다.

- host-only session cookie set/rotation/forwarding
- valid CSRF mutation 성공 및 missing token/forged Origin 거부
- 설정 상한 20 MiB multipart streaming proxy
- mock citation link의 URL 유지와 resolver 호출

하나라도 실패하거나 전담 owner가 viewer/E2E까지 책임질 capacity가 없으면 Phase 2 전에
**Option C plan-amendment gate**로 멈춘다. `.omx/drafts/option-c-amendment-meeting-rag-platform.md`
에 target tree, schema/client source of truth, UI Phase 3/4, 조건부 검증 명령, staffing/launch
hint, ADR/DAG 변경을 기록하고 독립 Architect와 Verifier가 승인한 뒤에만 재개한다. 실패를
ADR 한 줄로 자동 우회하거나 Option A용 plan을 그대로 실행하지 않는다.

Option A를 유지해도 Next는 authz/business state를 소유하지 않는 thin shell이다. 실제 두
구현이 없는 `RetrievalProvider`는 만들지 않고 PostgreSQL FTS를 직접 사용한 뒤 vector 필요가
측정될 때 ADR로 추출한다.

## 3. 확정 불변식

### 3.1 Same-origin session/CSRF

1. FastAPI가 authn/authz의 유일한 권위이며 Next proxy에서 온 identity/room/role 헤더를
   모두 제거한다.
2. session cookie는 host-only, HttpOnly, `Path=/`, `SameSite=Lax`; 운영 HTTPS에서
   `Secure`다. DB에는 opaque token hash만 저장하고 로그인 때 session ID와 CSRF secret을
   모두 rotation한다.
3. pre-auth register/login은 exact `Origin == public_origin`과 trusted Host를 요구한다.
   인증 후 `GET /api/csrf`가 session-bound synchronizer token을 반환하고 모든 unsafe method가
   `X-CSRF-Token`, exact Origin, trusted Host를 함께 검증한다.
4. browser-facing credentialed CORS는 비활성화하고 wildcard origin을 허용하지 않는다.
   trusted proxy/forwarded-host 목록은 고정한다.
5. proxy가 `Cookie`/`Set-Cookie`/multipart streaming을 정확히 중계하는지 Phase 0과 E2E에서
   검증한다. user-controlled forwarded identity header는 backend 진입 전 제거한다.

### 3.2 Upload/blob 원자성

1. API는 크기/count/MIME/magic/filename을 검증하며 web root 밖 staging 경로에 stream한다.
2. sha256 완료 뒤 random storage key로 원자 rename하고 DB revision을 commit한다.
3. DB commit 실패 staging/final orphan은 filesystem correlation manifest에 남긴다. DB queue
   기록도 실패할 수 있으므로 시작 시와 주기적으로 실행되는 sweeper가 manifest와 실제 blob
   key를 모두 열거해 DB와 대조한다. final rename 뒤 manifest write 전 crash도 탐지하고
   24시간이 지난 orphan을 제거한다.
4. current source revision은 append-only다. replace는 새 revision을 만들고 이전 row/anchor를
   덮어쓰지 않는다.
5. demo retention은 자동 삭제 없음으로 고정하되 orphan staging은 24시간 이내 정리한다.
   사용자 삭제/법적 retention은 운영 배포 전 별도 ADR이다.

### 3.3 Extraction/anchor identity

1. `extraction_runs`는 `source_revision_id`, parser name/version, newline policy, Unicode
   normalization profile, config hash, `anchor_schema_version`, status를 가진 append-only row다.
2. `source_anchors.id`는 server-issued opaque UUID다. citation/viewer가 client raw coordinate
   JSON을 신뢰하지 않는다.
3. 좌표 canonicalization:
   - `text_line`: 1-based line, Unicode code-point start/end.
   - `pdf_block`: 0-based page, page rotation/crop 적용 후 top-left origin의 `[0,1]` bbox.
   - `image_bbox`: EXIF orientation 적용 후 top-left origin의 `[0,1]` bbox.
   - `hwp_paragraph`: parser/version + section/paragraph/table-row/cell path + text fingerprint.
   - `chat_message`: immutable message UUID/author/timestamp contract only.
4. canonical JSON은 key sort/number normalization 후 hash한다. 같은 fixture+parser/config의
   반복 extraction은 같은 anchor hash와 click-to-highlight 결과를 내야 G0 GO다.
5. resolver는 `citation_id -> source_anchor_id -> extraction_run -> revision -> snapshot`을
   DB에서 따라가고 membership을 먼저 검사한다. web evidence는 `http/https`만 허용하며
   UI는 `noopener noreferrer` 외부 링크를 사용한다.

### 3.4 Submit/replace/close 직렬화

모든 submit/replace/close transaction은 다음 순서를 지킨다.

1. `talk_sessions` parent row를 `SELECT ... FOR UPDATE`한다.
2. lock 뒤 `state == open`과 actor policy를 다시 검사한다.
3. submit/replace는 새 revision과 extraction job을 만들고 commit한다.
4. close는 모든 current revision을 읽고, `ready`가 아니면서 request에 명시적으로 제외되지
   않은 revision이 있으면 실패한다
   (`.omx/plans/prd-meeting-rag-platform.md:79-85`).
5. host exclusion은 revision/reason/actor/time을 `snapshot_exclusions` audit row로 보존한다.
6. snapshot은 topic, participant attribution, 포함 revision, 승인 extraction run,
   anchor schema, pipeline version을 pin한다.
7. `(session_id, generation_epoch)` unique로 첫 milestone epoch 1의 canonical snapshot 하나를
   보장한다. 중복 close는 같은 snapshot/status를 반환한다.
8. snapshot + summary/research logical jobs + `state=closed/processing` 전이는 한 transaction이다.
9. `(snapshot_id, kind, pipeline_version)`에 canonical run/result unique를 둔다.

### 3.5 Durable queue와 fencing

실행 보장은 **at-least-once execution + idempotent/fenced persistence**다.

1. `jobs.logical_key`는 unique이고 retry는 같은 logical job row를 requeue한다.
   `job_attempts`가 owner/token/start/end/error를 append-only 기록한다.
2. 짧은 claim transaction은 DB clock으로 pending 또는 expired-running job을 lock하고
   `lease_generation += 1`, random `lease_token`, owner, `lease_until`을 저장한 뒤 commit한다.
3. 외부 parser/provider 작업은 DB transaction 밖에서 수행한다.
4. heartbeat와 completion은
   `WHERE id=? AND lease_generation=? AND lease_token=? AND state='running'` CAS다.
   completion CAS가 정확히 1 row가 아니면 exception을 발생시켜 result write를 포함한
   completion transaction 전체를 rollback한다.
5. canonical result insert/upsert와 정확히-1-row CAS success transition은 한 transaction이다.
6. 외부 side effect는 logical key/attempt correlation을 사용하고, stale temporary output은
   cleanup한다. “exactly once 외부 실행”을 주장하지 않는다.

### 3.6 Job orchestrator/parser sandbox

- orchestrator만 DB/blob/provider credential과 네트워크를 가진다.
- parser sandbox는 orchestrator가 만든 staged read-only input과 bounded output dir만 받는다.
- sandbox에는 DB/blob/provider/session secret이 없고 non-root, no-new-privileges, no egress,
  CPU/RAM/PID/wall-time/output-size 제한을 건다.
- orchestrator는 exit/status/output schema/size/anchor coordinate를 재검증한 뒤 저장한다.
- timeout/crash/oversized output은 staging cleanup과 typed failure code를 남긴다.
- G0는 이 topology에서 zip bomb, XXE, corrupt file, timeout, network probe, secret probe를
  실행한다. 전체 orchestrator를 network-off로 만들지 않는다.

### 3.7 Summary/research grounding

1. `SummaryRequest`는 snapshot의 quoted extracted spans와 anchor ID만 가지며 tool 설정
   필드가 없다. source text는 instruction과 분리된 untrusted data로 delimit한다.
2. map은 atomic `SummarySupport{anchor_id, exact_quote, start, end}`를 선택하고
   `SummaryItem{text, supports[]}`를 만든다. reduce는 grouping/dedup/participant attribution만
   수행하며 새 unsupported fact를 추가하지 않는다.
3. validator는 exact quote가 해당 extraction run의 span과 일치하고 모든 item이 하나 이상
   support를 가지며 타 snapshot anchor/URL/verdict/tool output이 없는지 검사한다.
4. 구조 검증만으로 semantic entailment를 완전 증명한다고 주장하지 않는다. G6는
   `valid anchor + unsupported assertion`과 paraphrase rubric을 blocking fixture로 평가한다.
5. source prompt-injection fixture는 summary tool 추가, research query policy 변경, private
   unrelated text 유출을 시도하며 모두 실패해야 한다.
6. `ResearchRequest`만 web search를 허용한다. check-worthy normalized claim과 필요한 supporting
   span만 검색 컨텍스트로 보내며 web citation을 내부 evidence schema로 정규화한다.
7. summary/research는 별도 prompt/run/schema/validator/repository이고 research retry 전후
   summary payload/hash는 같아야 한다
   (`.omx/plans/test-spec-meeting-rag-platform.md:58-65`,
   `.omx/plans/test-spec-meeting-rag-platform.md:111-116`).

### 3.8 결과 aggregate 상태

- `talk_sessions`: `draft -> open -> closed -> processing -> ready | needs_attention`.
- `generation_runs`: `queued | running | succeeded | failed_retryable | failed_terminal`.
- atomic snapshot transaction이 만들어야 할 canonical summary/research run이 누락된 경우도
  `needs_attention`과 `invariant_error_missing_run` reason으로 투영한다.
- canonical run 중 하나라도 `queued|running`이면 `processing`.
- summary/research가 둘 다 `succeeded`면 `ready`.
- active run이 0이고 둘 다 succeeded가 아니면 성공 문서가 0개 또는 1개인지와 무관하게
  `needs_attention`이다. 모든 failed kind의 reason/retryable을 반환하고 하나라도 retryable이면
  host retry action을 제공한다. 모두 terminal이면 retry 없이 운영/재계획 reason을 제공한다.
- retry는 `needs_attention -> processing`; canonical successful kind는 재실행하지 않는다.
- 이 조합표는 unit test로 전수 검증하고 both-retryable, both-terminal, mixed failure를 E2E로
  검증해 `processing` 영구 체류를 금지한다.

## 4. 목표 구조와 source of truth

```text
planned:/
  AGENTS.md  README.md  .env.example  package.json  pnpm-workspace.yaml
  pyproject.toml  uv.lock  docker-compose.yml
  apps/web/src/{app,features,components/source-viewer}/
  apps/api/app/{api,domain,application,adapters,worker}/
  apps/api/alembic/
  packages/api-client/        # OpenAPI에서 생성, 수동 편집 금지
  packages/schemas/           # Pydantic JSON Schema 생성물, 수동 편집 금지
  spikes/document-ingestion/
  tests/{fixtures,contract,integration,security,e2e,evaluation}/
  docs/{adr,demo-runbook.md}
```

- Pydantic domain/wire models가 backend schema의 source of truth다.
- FastAPI OpenAPI에서 TypeScript client를 생성하고 freshness test가 drift를 막는다.
- API와 orchestrator는 같은 Python package/image를 공유하지만 별도 entrypoint/process다.
- PostgreSQL은 domain, snapshot, queue, result를 저장하고 원본 bytes는 local `BlobStore`
  volume에 둔다. Redis/Celery/MinIO/vector DB는 첫 milestone에 없다.

## 5. Dependency-ordered 실행 DAG

### Phase 0 — repo/toolchain + Option A proof

**planned**: root manifests, Compose healthchecks, proxy/auth/upload/citation smoke.

1. Git과 Lore 규칙을 초기화하고 floating tag 없는 toolchain/lockfile을 만든다.
2. web/api/orchestrator/postgres 최소 process를 기동한다.
3. 2.4의 cookie/CSRF/20 MiB proxy/mock citation proof를 **폐기 가능한 transport harness**의
   자동 integration test로 만든다. 이는 production auth correctness 증거가 아니며 Phase 3의
   DB-backed session rotation/CSRF 테스트를 대체하지 않는다.
4. 전담 web owner의 viewer/E2E capacity를 기록한다. 실패/부재 시 Option C plan-amendment
   gate에서 멈추고 승인된 amendment 없이는 진행하지 않는다.

**gate**: Compose config/health와 네 smoke가 모두 exit 0.

### Phase 1 — blocking G0 parser/OCR/sandbox

**planned**: `spikes/document-ingestion/**`, golden/malicious fixtures, `docs/adr/0001-*`.

1. PDF text/scanned, HWP/HWPX paragraph/table, PNG/JPEG OCR를 sandbox topology에서 실행한다.
2. clean Korean OCR 90%+, parser license/runtime/cold-start/resource를 기록한다.
3. corrupt/encrypted/zip-bomb/XXE/network/secret/timeout/output-size 공격을 제한 내 거부한다.
4. 같은 fixture를 반복해 canonical anchor hash와 browser click-to-highlight를 검증한다.

**NO-GO**: 필수 형식 locator, sandbox containment, license, OCR, 반복 anchor 중 하나라도
실패하면 Phase 2를 시작하지 않고 재합의한다
(`.omx/plans/test-spec-meeting-rag-platform.md:15-27`).

### Phase 2 — contract freeze + minimal durable core

**planned**: Alembic, domain models/policies, Pydantic/OpenAPI, generated client, jobs/attempts,
orchestrator runner, sandbox IPC harness.

1. PRD 데이터 모델에 `extraction_runs`, exclusions, generation epoch, attempts/fencing fields를
   추가한다 (`.omx/plans/prd-meeting-rag-platform.md:139-169`).
2. 상태/권한/close/queue invariant를 순수 service와 DB constraint로 구현한다.
3. migration up/down/up, schema fixture, two-worker claim/stale-token unit+integration을 통과한다.
4. OpenAPI/client/schema를 freeze하고 이후 shared contract 파일은 한 lane만 소유한다.

**gate**: migration/contract/queue/fencing/sandbox harness test exit 0.

### Phase 3 — text-only thin vertical slice

**planned**: local auth, friends/room/session, text submission, close/snapshot, mock summary,
citation resolver, minimal Next pages.

1. Alice/Bob/Eve auth/friend/invite/private-room 흐름을 구현한다.
2. text opinion submit -> extraction anchor -> close -> durable mock summary job -> resolver를
   브라우저 E2E로 완주한다.
3. DB-backed session rotation/CSRF, IDOR, concurrent submit-close, stale worker, duplicate
   close를 blocking test로 실행한다.
4. `valid anchor + unsupported assertion`과 source prompt-injection을 G6 fixture로 고정한다.

**gate**: 외부 키 없이 vertical E2E와 보안/동시성/grounding 기준 통과.

### Phase 4 — format·UI 확장

Phase 2 contract와 Phase 3 vertical gate 뒤 다음 세 lane을 병렬화할 수 있다.

- **Backend/ingestion**: 파일 revision, blob staging/orphan cleanup, G0 parser 승격,
  extraction job, failure/confidence.
- **Web/viewer**: 제출 상태, safe preview, PDF/image/HWP highlight, aggregate failure status.
- **첫 완료 executor 또는 leader의 cross-lane verification**: 자신이 구현하지 않은 lane의
  malicious fixture, coordinate schema, resolver membership, accessibility를 검증한다.

**gate**: text/PDF/HWP/HWPX/PNG/JPEG 원본 재열람, stable anchor, failure visibility,
unauthorized access 0건. 원본 응답은 attachment/content-type/`nosniff`, preview는 sandboxed
viewer/CSP를 검증한다.

### Phase 5 — research/fact-check + result isolation

1. mock provider의 four-verdict fixture와 opinion filter를 먼저 구현한다.
2. topic research와 claim fact-check를 별도 sub-run으로 실행하고 evidence URL/title/domain/
   accessed-at/snippet-hash를 저장한다.
3. optional xAI adapter는 research에만 web tool을 제공하고 captured payload redaction을
   검증한다.
4. research failure/retry가 summary row/hash를 바꾸지 않는지 검증한다.

**gate**: mock E2E, dual citation, four verdict, output isolation, keyless operation.

### Phase 6 — hardening·visual·demo

1. G1–G6를 정적 -> unit/contract -> integration -> security -> E2E/evaluation 순으로 실행한다.
2. 모든 visual iteration은 다음 편집 전에 `$visual-verdict`를 실행하고 JSON을
   `.omx/state/{scope}/ralph-progress.json`에 기록한다. 최종 keyboard, focus, contrast,
   360/768/1440px viewport를 검증한다.
3. structured log/correlation/metrics와 raw content/secret leakage 0건을 검증한다.
4. mock E2E 10회 실패 0건, 작은 demo fixture 전체 처리 120초 이내 경고 기준을 기록한다
   (`.omx/plans/test-spec-meeting-rag-platform.md:137-147`).
5. seed/demo runbook을 새 환경에서 재현한다.

## 6. Acceptance criteria

| ID | Blocking criterion |
|---|---|
| AC-01 | friend가 아닌 사용자는 초대 후보가 아니고 비구성원 직접 접근은 모두 403/404다 |
| AC-02 | host만 close/retry하며 마감 뒤 submit/replace는 거부된다 |
| AC-03 | text/PDF/HWP/HWPX/PNG/JPEG 원본·처리 상태·safe preview를 재열람한다 |
| AC-04 | 모든 필수 형식의 canonical anchor hash가 반복 extraction에서 안정적이다 |
| AC-05 | clean Korean OCR fixture 정확도는 90% 이상이다 |
| AC-06 | failed/unready revision은 host exclusion audit 없이 snapshot에서 빠질 수 없다 |
| AC-07 | concurrent submit/replace/close에서 canonical epoch-1 snapshot 하나만 생긴다 |
| AC-08 | stale lease token completion은 0-row CAS로 거부되고 canonical result가 변하지 않는다 |
| AC-09 | 저장 citation resolver 성공 100%, 타 snapshot/revision citation 0건이다 |
| AC-10 | 모든 summary item은 exact support span이 있고 citation 없는 item은 0건이다 |
| AC-11 | valid-anchor unsupported assertion/prompt-injection fixture가 release gate를 실패시킨다 |
| AC-12 | summary의 web URL/verdict/tool output contamination은 0건이다 |
| AC-13 | research item은 web evidence, fact-check는 participant+web evidence를 가진다 |
| AC-14 | opinion/value judgment는 check-worthy claim에서 제외된다 |
| AC-15 | research 전후/재시도 전후 summary payload/hash가 동일하다 |
| AC-16 | xAI payload에 original bytes/URL/storage key/불필요 private text가 없다 |
| AC-17 | `XAI_API_KEY` 없이 full mock E2E가 성공하고 10회 반복 실패가 0건이다 |
| AC-18 | parser sandbox의 network/secret/resource escape fixture가 모두 차단된다 |
| AC-19 | missing CSRF/forged Origin/rotated session/proxy cookie 오류가 모두 거부된다 |
| AC-20 | active run이 0이고 둘 다 성공하지 않은 모든 조합은 `needs_attention`이며 reason/retryability를 보이고 영구 processing이 없다 |
| AC-21 | `chat_message` contract만 존재하고 chat UI/realtime implementation은 없다 |

기존 승인 기준 원장은 `.omx/specs/deep-interview-meeting-rag-platform.md:171-210`이다.

## 7. 위험·완화

| 위험 | 조기 신호 | Blocking 완화 |
|---|---|---|
| Option A 통합 과부하 | cookie/upload proxy smoke 실패, owner capacity 부재 | Phase 0에서 중단 후 Option C amendment+독립 승인 |
| HWP/OCR 실패 | locator drift, <90%, license 불명 | G0 NO-GO/재합의 |
| parser compromise | egress/secret/resource probe 성공 | secretless sandbox gate |
| CSRF/IDOR | forged Origin 또는 타 방 resolver 성공 | exact Origin/token/membership E2E |
| snapshot/lease race | duplicate snapshot/result, stale CAS 성공 | parent lock, unique, fencing tests |
| semantic hallucination | valid anchor와 무관한 사실 통과 | quote-backed span + G6 fixture |
| xAI 변경/쿼터 | smoke/schema mismatch | mock blocking, adapter, internal validation |
| generation total failure | active run 0인데 processing 유지 | exhaustive projection table + total-failure E2E |
| 범위 팽창 | chat/export/admin task 유입 | non-goal audit와 change approval |

## 8. Deliberate pre-mortem

1. **HWP locator가 데모 파일에서 재실행마다 바뀜**  
   신호: anchor hash/click drift. 예방: G0 반복 hash+highlight. 대응: Phase 2 중단 후 parser/
   canonicalization 재합의; 가짜 line number로 축소 금지.
2. **악성 HWP가 orchestrator credential을 읽거나 worker를 OOM시킴**  
   신호: network/secret probe, output 폭증. 예방: staged read-only secretless sandbox와 resource
   cap. 대응: 해당 revision 격리, typed failure, sandbox ADR 수정 전 재처리 금지.
3. **유효 citation을 단 unsupported summary가 공개됨**  
   신호: valid-anchor unsupported fixture/rubric 실패. 예방: atomic exact span, bounded reduce,
   G6 blocking. 대응: 결과 `failed_validation`, 공개 금지, 같은 canonical run 재queue.
4. **중복 close/lease reclaim 또는 forged mutation이 private/중복 결과를 만듦**  
   신호: canonical unique/CAS/Origin test 실패. 예방: parent lock, synchronizer CSRF, fencing.
   대응: generation 중지, canonical row 보존, orphan cleanup, 보안/동시성 재검증.

## 9. Expanded test plan

### Unit/contract

- 상태/권한의 exhaustive aggregate projection, idempotency, lease generation/CAS rollback.
- 모든 anchor coordinate/canonical hash/exact quote round-trip.
- Pydantic -> OpenAPI -> generated client freshness.
- summary/research DTO tool policy와 payload redactor.
- valid/invalid grounding, opinion filter, four verdict.

### Integration

- Alembic up/down/up, DB unique/FK/parent lock.
- concurrent submit-close, duplicate close, two-worker claim, expired reclaim, stale completion.
- blob staging/atomic move/orphan cleanup/path traversal.
- orchestrator-sandbox IPC, timeout/output limit/network/secret probes.
- session rotation/synchronizer token/exact Origin/Host/proxy cookies/20 MiB upload.
- mock provider -> canonical results/citations와 research retry summary hash.

### E2E/evaluation

- Alice/Bob/Eve 전체 vertical + 필수 formats + citation highlight.
- failed source exclusion, one/both retryable·terminal·mixed result/retry, duplicate-click recovery.
- wrong participant claim은 summary에서 원문 관점으로 남고 research에서만 fact-check.
- valid-anchor unsupported assertion, source prompt-injection, citation cross-snapshot.
- mock E2E 10회, citation 100%, contamination 0, OCR 90%+.

### Observability

- correlation/job/snapshot/stage/duration/attempt/lease generation/error code.
- jobs/parser failures/generation latency/citation validation counters.
- password/cookie/token/key/raw original/extracted text 로그 0건.
- UI retryable/non-retryable reason과 sandbox failure code.

## 10. 검증 명령 계약

```bash
uv run pytest spikes/document-ingestion
pnpm lint && pnpm typecheck && pnpm test
uv run ruff check .
uv run mypy apps/api
uv run pytest -m "not integration and not e2e"
docker compose config
docker compose up -d --build
uv run pytest -m "integration or security"
pnpm playwright test
uv run pytest -m evaluation
```

G0 -> static -> unit/contract -> integration -> security -> E2E/evaluation 순서를 지키고 앞 gate
실패 시 뒤 결과로 release를 정당화하지 않는다. 외부 xAI smoke는 키가 명시된 환경에서만
비차단으로 실행한다 (`.omx/plans/test-spec-meeting-rag-platform.md:187-205`).

## 11. ADR

### Decision

Phase 0 disposable transport proof와 web-owner capacity를 조건으로 Next.js thin shell +
FastAPI/Python core/API/orchestrator +
secretless parser sandbox + PostgreSQL domain/durable queue + local BlobStore + mock/xAI adapter를
채택한다. source/extraction/anchor/snapshot/result는 append-only version chain이며,
summary/research는 구조·저장상 분리된다.

### Drivers

D1 early delivery-risk exposure, D2 auditable grounding/citation, D3 private/untrusted boundary.

### Alternatives considered

단일 Node/Next, 단일 Python/server-rendered, 운영형 Redis/Celery/object/vector 구성을 비교했다.

### Why chosen

Python 문서 처리를 유지하면서 citation viewer의 상호작용성과 독립 web lane을 얻는다.
다만 proxy/두 toolchain 위험은 Phase 0 proof와 Option C stop/amend/review trigger로 제한하고,
queue/blob/retrieval 추가 인프라는 현재 규모에서 제거한다.

### Consequences

- 두 lockfile과 generated client freshness를 검증해야 한다.
- API/orchestrator/sandbox는 같은 repo여도 별도 trust/process boundary다.
- queue는 at-least-once이며 fencing된 persistence만 보장한다.
- summary semantic grounding은 exact spans + blocking evaluation으로 관리하며 수학적 완전
  보장을 주장하지 않는다.
- HWP/HWPX viewer는 native render가 아니라 canonical structured highlight + download다.
- `needs_attention`이 one-or-total failure의 명시적 action state가 된다.
- Option C branch는 자동 대체가 아니라 bounded plan amendment와 독립 재승인을 요구한다.

### Follow-ups

1. G0에서 parser/OCR/license/sandbox를 ADR-0001로 pin.
2. Phase 0 결과로 Option A를 유지하거나, 중단 후 승인된 Option C amendment/ADR-0002로
   target tree·commands·staffing 전체를 교체한다.
3. 실제 xAI smoke 뒤 model/tool/schema/cost를 provider ADR에 pin.
4. vector/object storage/retention/malware scanning은 측정 또는 외부 배포 전 별도 ADR.
5. chat 구현 전 종료/snapshot/message privacy를 별도 PRD로 합의.

## 12. Agent roster와 staffing

### Available agent types

- 탐색/계획: `explore`, `analyst`, `planner`, `product-manager`, `researcher`
- 설계/검토: `architect`, `critic`, `api-reviewer`, `dependency-expert`
- 구현: `executor`, `team-executor`, `designer`, `debugger`, `build-fixer`
- 검증: `test-engineer`, `verifier`, `qa-tester`, `security-reviewer`,
  `performance-reviewer`, `quality-reviewer`, `quality-strategist`, `code-reviewer`
- 품질/전달: `style-reviewer`, `code-simplifier`, `writer`, `git-master`
- UX/제품: `ux-researcher`, `information-architect`, `product-analyst`, `vision`

### Ralph path

- owner `executor` high: Phase 0/G0 및 gate 유지.
- bounded executors high: backend/domain, ingestion/sandbox, web/viewer.
- `test-engineer` high: regression/evidence.
- `security-reviewer` high: auth/upload/parser/provider boundary.
- 구현 비참여 `architect` 또는 `verifier` high: final sign-off.
- visual iteration은 `designer`/`ux-researcher` medium + `$visual-verdict`.

### Team path

현재 leader 포함 4-slot을 기준으로 **leader + `3:executor`**로 제한한다.

1. Phase 0–2는 leader가 순차 gate/contract freeze.
2. Phase 3–5에서 worker A backend/domain/queue(high), B ingestion/sandbox(high),
   C web/viewer(medium-high).
3. 같은 Team 안에서 agent type을 바꾸지 않는다. 먼저 끝난 `executor`는 자신이 구현하지 않은
   lane의 cross-lane regression task를 수행한다.
4. Team terminal/shutdown 뒤 reasoning **high**의 별도 native turn으로 `test-engineer` ->
   `security-reviewer` -> `verifier` 또는 `architect`를 순차 실행해 독립 sign-off를 얻는다.
5. migration/OpenAPI/schema는 한 lane만 소유한다.

```bash
$ralph ".omx/plans/ralplan-meeting-rag-platform.md를 Phase 0부터 gate 순서대로 구현·검증"

# Git baseline, Phase 0 Option A proof, Phase 1 G0 GO, Phase 2 contract freeze 이후
omx team 3:executor "Execute .omx/plans/ralplan-meeting-rag-platform.md from Phase 3; preserve frozen contracts and assign completed executors only to cross-verify lanes they did not implement"

$team 3:executor "Execute the approved plan from Phase 3 with backend, ingestion, and web lanes; keep worker agentType fixed and perform cross-lane regression before terminal handoff"
```

## 13. Team verification path

1. 시작 전 Git/Lore baseline, tmux/$TMUX/omx, G0/contract-freeze 증거를 확인한다.
2. team name/panes/ACK/task ownership을 기록하고 `omx team status`/`await`로 감시한다.
3. 각 lane은 changed files, Lore commit, 실행 명령과 원문 결과를 제출한다.
4. 각 executor는 자신이 구현하지 않은 lane의 migration/contract/concurrency/security/E2E를
   cross-verify한다.
5. visual edit마다 `$visual-verdict` JSON을 `.omx/state/{scope}/ralph-progress.json`에 보존하고
   최종 accessibility/viewport를 검증한다.
6. pending/in-progress/failed가 0이고 G0–G6 증거가 모두 있을 때만 shutdown한다.
7. Team terminal 뒤 별도 native `test-engineer`, `security-reviewer`, `verifier/architect`가
   순차 검토한다.
8. flaky/security/demo gap이 남으면 별도 Ralph fix/verification loop로 넘긴다.
9. fresh full verification과 독립 Architect/Verifier 승인 없이는 완료를 선언하지 않는다.

## 14. 실행 guardrails와 합의 변경 기록

- 이 planning turn은 코드·dependency·Git·외부 서비스를 생성하지 않는다.
- G0 NO-GO, Option A proof/owner gate 실패, 유료/배포/credential 요구는 자동 우회하지 않는다.
- 테스트 삭제/완화, 원본 제3자 업로드, summary/research 혼합, chat scope 추가를 금지한다.
- 실제 설치 직전 공식 문서/버전을 재확인하고 lockfile/ADR에 pin한다.

v2는 Architect/Critic M1–M8을 반영했다. v3는 F1–F3을 반영해 total-failure projection,
fixed-agentType Team/cross-lane 검증과 Team 후 specialist sign-off, Option C stop/amend/review
gate를 닫았다. 추가로 CAS 전체 rollback, disposable Phase 0 harness, filesystem orphan
sweeper, normalization profile, safe-preview header/CSP gate를 강화했다.

최종 merge에서는 Architect/Critic 승인 후 제안된 cross-lane 명명, manifest+blob 열거,
missing-run invariant projection, post-Team specialist high reasoning을 반영했다. 250–450줄
압축 제안은 transaction/fencing/trust-boundary 실행 의미론을 잃을 위험이 있어 적용하지 않았다.

공식 근거:
[xAI Web Search](https://docs.x.ai/developers/tools/web-search),
[xAI Citations](https://docs.x.ai/developers/tools/citations),
[xAI Structured Outputs](https://docs.x.ai/developers/model-capabilities/text/structured-outputs),
[FastAPI background-task caveat](https://fastapi.tiangolo.com/tutorial/background-tasks/),
[PostgreSQL SKIP LOCKED](https://www.postgresql.org/docs/current/sql-select.html),
[Next.js App Router](https://nextjs.org/docs/app),
[PyMuPDF bbox](https://pymupdf.readthedocs.io/en/latest/app1.html),
[PaddleOCR](https://www.paddleocr.ai/main/en/index.html),
[Hancom 공개 형식](https://www.hancom.com/support/downloadCenter/hwpOwpml).
