# Approved Amendment — Full Grok RAG Report Pipeline

## Status

- **승인됨**
- 승인일: 2026-08-10
- 승인자: 프로젝트 소유자
- 적용 범위: 현재 사용자가 명시한 보고서 생성 파이프라인

## Requested pipeline

1. 사용자가 업로드한 문서만 독립 작업으로 병렬 분석한다. 프로젝트 설명을 이용한
   `synthetic_brief` 또는 "AI가 생각한 문서"는 생성하거나 결과 화면에 노출하지 않는다.
   - 문서별 근거 기반 요약
   - 외부 근거를 이용한 사실 검증
   - `supported | refuted | mixed | unverifiable` 판정
   - `mixed`, `unverifiable`, 근거 부족 항목은 사용자에게 `검증 의심` 경고로 노출
2. 문서별 분석 결과를 입력으로 1차 초안을 생성한다. 초안의 모든 주장에는 사용한
   source-anchor 또는 web-evidence ID를 기록한다.
3. 초안의 각 주장별로 원문 anchor를 다시 검색한 뒤, 검색 결과만 사용해 최종 문서를
   생성한다. 최종 문서에서도 RAG 태그와 인용 provenance를 유지한다.
4. 최종 문서와 근거를 비교해 수정·추가·삭제 추천을 생성하고 `/editor`의 AI 추천에
   저장한다.

## Required authorization expansion

승인 시 다음 기존 제한에 대한 명시적이고 한정된 예외가 필요하다.

- 반복적인 프로덕션 xAI 호출
- 업로드 문서에서 추출한 텍스트 anchor의 xAI 전송
- 외부 웹 검색 및 검증 결과 저장
- 단계별 생성물과 provider 메타데이터의 영속 저장

원본 바이너리 파일은 xAI 또는 다른 제3자에게 전송하지 않는다. 전송 범위는 서버에서
추출·정규화·크기 제한·프롬프트 인젝션 검사를 마친 텍스트 anchor로 제한한다.

## Fail-closed requirements

- `XAI_API_KEY` 부재, 인증 실패, 요청 거부, 타임아웃, 스키마 불일치 시 MockProvider나
  로컬 생성으로 대체하지 않는다.
- 해당 generation stage를 typed retryable/terminal failure로 기록한다.
- 최종 보고서가 완성되지 않은 경우 기존 보고서를 새 결과로 가장하지 않는다.
- UI는 빨간 오류 상태와 호스트 전용 재시도 동작을 제공한다.

## Data and safety constraints

- xAI 요청은 `store: false`를 유지한다.
- 이 보고서 파이프라인에서는 승인된 source anchor 외 프로젝트 설명·개인정보·자격 증명·
  원본 파일을 보내지 않는다.
- 각 결과는 provider/model/prompt-version/input-snapshot/content-hash를 기록한다.
- 외부 검증 결과는 URL, 접근 시각, snippet hash와 함께 저장한다.
- source summary와 web research는 별도 단계·별도 저장소로 격리한다.
- 최종 문장의 RAG 태그는 현재 snapshot에 속한 anchor만 참조할 수 있다.

## Proposed durable stages

`document_analysis[*] + fact_check[*] -> draft -> grounded_final -> suggestions`

각 단계는 snapshot과 pipeline version으로 멱등성을 보장하며, 선행 단계 성공 전 후속 단계를
enqueue하지 않는다. 문서별 분석·검증만 병렬 실행하고 draft 이후 단계는 순차 실행한다.

## Approval record

프로젝트 소유자는 2026-08-10 현재 채팅 세션에서 다음을 명시적으로 승인했다.

1. 보고서 파이프라인의 반복 xAI 호출 및 관련 비용
2. 정규화된 문서 텍스트 anchor의 xAI 전송
3. 외부 웹 사실 검증
4. 원본 바이너리는 계속 전송하지 않음
5. Grok 실패 시 MockProvider 및 오프라인 생성으로 대체하지 않음
