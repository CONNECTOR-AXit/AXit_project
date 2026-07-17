# Deep Interview Transcript — 회의 사전 브리핑 RAG 플랫폼

- 프로필: Standard
- 컨텍스트: Greenfield
- 라운드: 10
- 최종 모호성: 12% (종료 임계치 20%)
- 컨텍스트 스냅샷: `.omx/context/meeting-rag-platform-20260716T080912Z.md`
- 작성 시각(UTC): 2026-07-16T09:19:24Z

## 최초 요구 요약

친구 요청과 초대로 구성된 방에서 두 종류의 토크 세션을 지원한다.

1. **참여자 전달형**: 참가자가 회의 전에 파일 또는 의견을 제출한다. 원본은 방 구성원 모두에게 보존·공개되고, LLM은 원본에만 근거한 요약본과 별도의 LLM 조사본을 만든다.
2. **참여자 대화형**: 카카오톡형 채팅으로 회의하고 종료 시 전체 대화를 한 번 처리한다.

두 모드 모두 원본 인용이 가능해야 한다. LLM 조사본에는 주제 웹 조사와 참가자 주장 팩트체크가 들어가며, 요약본에는 웹 조사나 팩트체크 내용을 섞지 않는다.

## 라운드 기록

| # | 질문 초점 | 사용자 결정 | 명세에 반영된 의미 |
|---|---|---|---|
| 1 | 첫 마일스톤 범위 | `submission-complete-chat-foundation` | 전달형은 데모 가능한 수준으로 완성하고 대화형은 공통 스키마·API 기반만 만든다. |
| 2 | 핵심 사용 시점 | `pre-meeting-preparation` | 제출형 결과물은 회의 전 사전 브리핑이다. |
| 3 | 생성 경계 | `organizer-freeze-once` | 주최자가 마감한 스냅샷으로 요약본과 조사본을 한 번 생성한다. |
| 4 | 비목표 탐색 | 자유 응답 | PDF·HWP·PNG·JPG 등 폭넓은 형식과 Grok 후보 요구를 확인했다. |
| 5 | RAG 태그 의미 | `native-format-locators` | 텍스트 줄, PDF 페이지·문단, 이미지 영역 등 형식별 원본 위치를 가리키는 클릭 가능한 인용으로 정의한다. |
| 6 | 팩트체크 범위 | `auto-checkworthy-claims` | 외부에서 검증 가능한 핵심 주장만 자동 선별하고 의견·가치판단은 제외한다. |
| 7 | LLM 공급자 | `grok-default-provider-adapter` | Grok을 최초 공급자로 사용하되 교체 가능한 어댑터 경계를 둔다. |
| 8 | 개인정보 경계 | `send-extracted-content-only` | 원본은 서비스 저장소에 남기고 필요한 추출 조각만 Grok에 전송한다. |
| 9 | 비목표 확정 | `accept-proposed-non-goals` | 음성·영상, 공동편집, 공개·내보내기, 네이티브 앱, 과금·분석, 대화형 완성 UI를 제외한다. |
| 10 | 완성도·자율성 | `hackathon-demo-autonomous-stack` | 핵심 흐름과 인용 정확성 중심의 데모. 로컬 기술 선택은 자율, 외부 배포·유료 자원·자격증명은 승인 필요. |

## 압박 검증 결과

- “회의 전 준비”라는 목적을 9시 59분 수정 사례로 재검증했다. 결과물을 실시간 재생성하지 않고 주최자가 마감한 불변 스냅샷에서 1회 생성하도록 경계를 고정했다.
- 폭넓은 파일 형식과 “몇 번째 줄” 요구의 충돌을 검증했다. 모든 형식을 가짜 줄 번호로 평탄화하지 않고 형식별 원본 좌표를 사용하기로 했다.
- 원본을 제3자 LLM에 직접 업로드하는 편의성보다 데이터 통제권을 우선했다. 자체 파싱·OCR 결과의 필요한 조각만 외부로 보낸다.

## 공식 문서로 확인한 사실

- Grok 4.5는 서버 측 웹 검색과 URL 인용 메타데이터를 지원한다.
- xAI 파일 문서 검색은 PDF와 텍스트 계열을 지원하지만 HWP/HWPX 지원을 명시적으로 보장하지 않는다.
- 따라서 광범위한 형식, OCR, 원본 좌표 인용은 애플리케이션이 소유하는 전처리·출처 계층이 필요하다.

참고: [xAI Web Search](https://docs.x.ai/developers/tools/web-search), [xAI Citations](https://docs.x.ai/developers/tools/citations), [Chat with Files](https://docs.x.ai/developers/model-capabilities/files/chat-with-files), [Managing Files](https://docs.x.ai/developers/files/managing-files), [Grok 4.5](https://docs.x.ai/developers/grok-4-5)

## 잔여 위험

- HWP와 스캔/이미지의 파싱 품질은 파일별 편차가 크다. 추출 실패·낮은 OCR 신뢰도를 사용자에게 표시해야 한다.
- 웹 팩트체크는 진실 판정기가 아니다. 상충·불충분한 근거를 별도 상태로 표현하고 출처를 공개해야 한다.
- 해커톤 범위이므로 상용 수준의 규정 준수, 고가용성, 과금, 운영 분석은 후속 단계다.

