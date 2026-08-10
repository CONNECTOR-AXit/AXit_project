# Approved Amendment — Limited Live xAI Provider Smoke

## 2026-08-06 재검증 승인

- 상태: **승인됨 — 프로젝트 소유자가 현재 채팅에서 반복 호출을 명시적으로 허용**
- 이전 1회 호출은 `grok_incomplete_response`로 종료되었다.
- 이번 승인으로 합성 입력을 사용하는 추가 호출을 최대 3회 허용한다.
- `PASS`가 확인되는 즉시 호출을 중단한다. 동일 페이로드의 무제한 재시도는 금지한다.
- 각 호출은 계속 `store: false`, `tools: []`이며 실제 사용자 자료를 전송하지 않는다.
- 구조화 출력 완결성을 위해 `max_output_tokens` 상한을 4,000으로 조정할 수 있다.
- 호출 사이에는 실패 원인을 근거로 한 코드·스키마 수정과 오프라인 회귀 테스트가 선행되어야 한다.
- 이 승인은 프로덕션 통합, 브라우저 키 전달, 원본 파일 업로드, 웹/X 검색 도구 사용을 허용하지 않는다.

- 상태: **승인됨 — 프로젝트 소유자가 2026-07-23 채팅 세션에서 활성화**
- 작성일: 2026-07-23
- 승인일: 2026-07-23 (프로젝트 소유자, 본 세션 채팅 지시)
- 대체 대상: `.omx/plans/provider-experiment-override-meeting-rag-platform.md`의
  `외부 xAI/Grok 호출: 보류` 조항
- 관련 구현:
  - `apps/api/app/grok_provider.py`
  - `apps/api/app/grok_smoke.py`
  - `config/grok-online.env.template`

## 1. 목적

MockProvider 회귀 기준을 유지하면서 xAI Responses API와 AXit provider 경계의 최소 호환성을
확인한다. 이 개정은 제품 트래픽, 외부 배포, 원본 문서 업로드 또는 Grok 품질 승인을 허용하지
않는다. 허용 대상은 합성 자료를 사용하는 명시적 1회 smoke뿐이다.

## 2. 제안하는 제한적 허용

상위 런타임 계약이 이 개정안을 명시적으로 채택한 이후에만 다음을 허용한다.

1. `app.grok_smoke`를 통한 xAI Responses API 요청 최대 1회.
2. 입력은 `synthetic_rag_anchors()`에 고정된 합성 한국어 문장만 사용한다.
3. `store: false`, `tools: []`, `max_output_tokens: 1200`을 변경하지 않는다.
4. 모델은 배포 계정에서 사용 가능한 텍스트 모델 1개로 제한한다.
5. 결과는 stdout의 비밀정보 없는 검증 메타데이터로만 남긴다.
6. 실제 응답 원문, API 키, Authorization header, 참가자 원문은 파일이나 DB에 저장하지 않는다.
7. MockProvider fixture와 canonical 결과를 갱신하거나 덮어쓰지 않는다.

## 3. 계속 금지되는 사항

- API 키를 Git 추적 파일, `.env.example`, 로그, 테스트 fixture, DB에 기록
- web/API 서버 또는 브라우저에 API 키 전달
- 실제 사용자 문서, 추출문, PII, 회의 원문을 xAI에 전송
- web search, X search, code execution 또는 파일 업로드 tool 사용
- 반복 호출, 부하 시험, 평가 corpus batch 호출, 자동 재시도
- 외부 배포를 이 smoke 승인에 포함하는 것으로 해석
- smoke 결과를 Grok production 품질 또는 완전한 schema 호환성 증거로 표현

## 4. Credential 계약

실제 키는 저장소 파일에 쓰지 않는다. 배포 플랫폼 secret 또는 실행 프로세스의
`XAI_API_KEY` 환경변수로만 공급한다. `config/grok-online.env.template`은 변수 이름을
설명하는 빈 템플릿이며 실제 secret 저장 위치가 아니다.

필수 런타임 변수:

```text
XAI_API_KEY=<platform secret>
GROK_MODEL=<approved model id>
GROK_LIVE_SMOKE_ACK=I_ACKNOWLEDGE_XAI_BILLING_AND_DATA_TRANSFER
```

## 5. 단일 호출 및 비용 경계

- 한 프로세스 실행당 전송 계층 호출 수는 정확히 1회다.
- provider 또는 HTTP 오류가 발생해도 자동 재시도하지 않는다.
- 호출 전 사용자가 xAI 계정의 모델 접근 권한과 결제 한도를 확인한다.
- 호출 후 추가 실험은 별도 승인 없이는 금지한다.

## 6. 성공 기준

다음을 모두 만족해야 smoke를 `PASS`로 기록할 수 있다.

1. HTTP 요청이 xAI Responses API에서 정상 완료된다.
2. 응답이 지정 JSON Schema로 파싱된다.
3. 출력 item이 한국어를 포함한다.
4. 모든 item에 합성 participant anchor와 정확한 support quote가 있다.
5. foreign anchor, URL, web verdict가 요약 후보에 없다.
6. API 키나 Authorization 값이 출력·오류·저장소에 나타나지 않는다.
7. canonical persistence는 시도하지 않는다.

## 7. 실패 및 중단 기준

- 인증 실패, schema 불일치, foreign anchor, quote mismatch, 비한국어 결과는 `FAIL`이다.
- 429/5xx/timeout도 해당 실행에서는 재시도하지 않고 중단한다.
- `store: false`가 요청에 없으면 전송 전에 차단한다.
- 키 노출이 의심되면 즉시 해당 키를 폐기하고 결과를 무효화한다.

## 8. 활성화 절차

이 문서를 저장소에 추가하는 것만으로는 현재 계약을 변경하지 않는다. 활성화에는 다음 두
조건이 모두 필요하다.

1. 프로젝트 소유자가 이 개정안을 승인된 상태로 변경한다.
2. 새 실행 세션의 상위 developer/runtime overlay가 다음 금지를 명시적으로 대체한다.
   - `Do not call xAI/Grok during the current experiment.`
   - `Do not ... use paid resources ...`

둘 중 하나라도 없으면 `app.grok_smoke`를 실행하지 않고 MockProvider 경로만 유지한다.

**활성화 기록 (2026-07-23):** 프로젝트 소유자가 본 채팅 세션에서 두 조건을 모두
충족했다 — (1) 위 상태 필드를 승인됨으로 직접 변경, (2) `AGENTS.md`의
`Do not call xAI/Grok during the current experiment.` 및
`Do not ... use paid resources ...` 금지 조항을 본 개정안으로 명시적으로 대체하도록
지시. 범위는 여전히 1절~7절에 정의된 1회 synthetic smoke로 제한되며, 프로덕션 통합이나
반복 호출을 허용하지 않는다.

## 9. 승인 후 후속 범위

1회 smoke 성공은 transport/schema 후보 검증까지만 닫는다. `ground_summary()`의 reviewed
assertion 경계, production provider 선택, research/web tool, retry, 운영 배포는 여전히 별도
Phase/ADR 승인이 필요하다.

> **후속 승인 기록:** 이 문서의 프로덕션 통합 금지는 2026-08-08 설명 구체화 개정과
> 2026-08-10 전체 보고서 파이프라인 개정의 각 명시적 범위에서만 대체되었다. 그 밖의
> 기능에는 본 문서의 제한이 계속 적용된다.
