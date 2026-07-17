# PRD — 회의 사전 브리핑 RAG 플랫폼

- 상태: Ralplan consensus 승인 (`.omx/plans/ralplan-meeting-rag-platform.md`)
- 범위: 첫 마일스톤(참여자 전달형 완성 + 대화형 공통 기반)
- 품질 목표: 해커톤 데모
- 요구사항 기준: `.omx/specs/deep-interview-meeting-rag-platform.md`

## 1. 문제와 목표

초대된 참가자가 회의 전에 제출한 자료와 의견을 모두가 열람할 수 있게 보존하고, 원본에만 근거한 요약본과 외부 조사·팩트체크를 담은 별도 조사본을 제공한다. 모든 생성 항목은 원본 또는 웹 근거로 역추적 가능해야 한다(`.omx/specs/deep-interview-meeting-rag-platform.md:26-38`).

### 핵심 성공 결과

1. 친구 관계를 바탕으로 비공개 방과 전달형 토크 세션을 만든다.
2. 참가자는 텍스트 의견과 PDF/HWP/PNG/JPG를 제출하고 방 구성원은 원본을 본다.
3. 주최자는 제출을 마감하고 불변 스냅샷에서 1회의 논리적 생성 작업을 시작한다.
4. 요약본에는 참가자 원본 내용과 원본 인용만 존재한다.
5. 조사본에는 주제 웹 조사와 선별된 참가자 주장 팩트체크가 존재하며 원본·웹 이중 인용을 제공한다.
6. Grok API 키가 없어도 결정론적 fixture로 전체 데모가 가능하다.

## 2. 범위

### 포함

- 로컬 이메일/비밀번호 데모 인증, 세션 쿠키
- 친구 요청/수락/거절
- 비공개 방, 방 멤버십, 주최자 권한
- 전달형 세션 생성/오픈/마감/처리/완료 상태
- 텍스트 의견과 PDF/HWP/PNG/JPG 업로드
- 원본 저장·다운로드·안전한 미리보기
- PDF 텍스트 좌표, 이미지/스캔 OCR 좌표, HWP 섹션/문단 좌표
- 제출 리비전과 마감 스냅샷
- PostgreSQL 기반 비동기 작업 큐와 독립 worker
- 요약 파이프라인과 조사/팩트체크 파이프라인 분리
- Grok 어댑터와 목 어댑터
- 인용 resolver와 원본 viewer 딥링크
- 향후 대화형을 위한 공통 모델과 `chat_message` anchor 계약

### 제외

명시적 비목표는 요구 명세를 그대로 따른다(`.omx/specs/deep-interview-meeting-rag-platform.md:74-82`): 음성·영상/STT, 실시간 공동편집, 공개 링크/문서 내보내기, 네이티브 모바일, 과금/관리자 분석, 완성된 대화형 UI·실시간 채팅, 상용 수준의 고가용성·규정 준수.

## 3. 사용자와 권한

| 역할 | 허용 작업 |
|---|---|
| 사용자 | 가입/로그인, 친구 요청/수락/거절 |
| 방 주최자 | 방 생성, 친구 초대, 세션 생성, 제출 마감, 생성 시작/재시도 |
| 방 참가자 | 자신의 제출 생성/교체, 모든 방 원본과 결과 열람 |
| 비구성원 | 방 리소스 접근 불가 |

모든 방 리소스 조회는 객체 ID 존재 여부보다 멤버십을 먼저 검증해 IDOR을 방지한다. 주최자 권한은 마감·재시도 같은 상태 전이에 추가로 검사한다(`.omx/specs/deep-interview-meeting-rag-platform.md:40-53`).

## 4. 사용자 여정

1. Alice와 Bob이 계정을 만들고 Alice의 친구 요청을 Bob이 수락한다.
2. Alice가 방을 만들고 Bob을 초대한다.
3. Alice가 회의 주제와 마감 시각을 가진 전달형 세션을 연다.
4. Alice는 텍스트 의견, Bob은 파일을 제출한다.
5. 각 파일은 원본 저장 후 파싱/OCR worker가 처리한다.
6. 두 사용자는 제출자, 처리 상태, 원본, 추출 미리보기를 본다.
7. Alice가 세션을 마감한다. 마감 트랜잭션은 현재 리비전 목록을 고정한다.
8. worker가 요약과 조사를 독립 단계로 실행한다.
9. 요약 문장의 인용을 클릭하면 원본 viewer의 줄/페이지/문단/이미지 영역으로 이동한다.
10. 조사 문장의 인용은 웹 URL로, 팩트체크의 대상 인용은 참가자 원문으로 이동한다.

## 5. 상태 모델

### 토크 세션

`draft -> open -> closed -> processing -> ready`

- `open -> closed`: 주최자만 가능, 단일 DB 트랜잭션.
- `closed -> processing`: 스냅샷과 generation job 생성이 성공했을 때.
- `processing -> ready`: 요약·조사 결과가 모두 완료되었을 때.
- 처리 실패는 단계별로 기록하고, 요약과 조사는 독립 상태를 가져 부분 완료를 표시한다.
- 재시도는 같은 스냅샷·파이프라인 버전의 idempotency key를 사용하며 새 논리 결과 버전을 만들지 않는다.

### 원본 처리

`uploaded -> queued -> extracting -> ready | failed`

- 실패 원본은 삭제하지 않는다.
- 주최자는 마감 전에 실패 원본을 스냅샷에서 제외할지 확인한다.
- `ready`가 아니면서 명시적 제외도 아닌 현재 리비전이 있으면 마감을 막는다.

## 6. 입력 제한

해커톤 데모를 안정화하기 위한 기본값이며 구성값으로 둔다.

- 파일당 20 MiB
- 세션당 현재 리비전 최대 20개
- PDF 최대 100페이지
- 이미지 최대 25MP
- 허용 확장자와 MIME: PDF, HWP/HWPX, PNG, JPEG
- 암호화/비밀번호 보호 문서는 처리 실패로 표시
- 압축 해제 비율, XML 엔터티, 파서 시간/메모리 상한 적용

## 7. 출력 계약

### 요약본

- Grok 요약 호출에는 web/x-search tool을 절대 제공하지 않는다.
- 입력은 `GenerationSnapshot`의 `ExtractedBlock`과 내부 anchor ID로 제한한다.
- 구조화 출력은 `sections[].items[].text`와 `source_anchor_ids[]`를 요구한다.
- 저장 전 모든 anchor 존재, 스냅샷 소속, 최소 1개 인용을 검증한다.
- 웹 URL, 팩트체크 상태, 조사 문구가 포함되면 validation failure로 처리한다(`.omx/specs/deep-interview-meeting-rag-platform.md:98-106`).

### 조사본

- 주제 조사와 팩트체크를 별도 sub-run으로 실행한다.
- 주제 조사는 Grok web search를 사용하고 URL, 제목, 도메인, 접근 시각, 스니펫 해시를 정규화한다.
- 팩트체크는 원본에서 검증 가능 주장 후보를 추출하고 의견/예측을 필터링한 뒤 주장별 웹 검색을 수행한다.
- 각 항목은 participant anchor와 하나 이상의 web evidence를 가진다.
- 상태는 `supported | refuted | mixed | unverifiable`로 제한한다(`.omx/specs/deep-interview-meeting-rag-platform.md:108-123`).

## 8. RAG와 인용 의미

첫 마일스톤의 RAG는 **provenance-first grounded generation**이다. 벡터 데이터베이스 도입 자체가 성공 조건은 아니다.

- 긴 문서는 안정된 `ExtractedBlock` 단위로 나눈다.
- 요약은 문서별 map 결과를 만든 뒤 citation ID를 보존하며 reduce한다.
- 팩트체크 후보 검색은 PostgreSQL full-text/메타데이터 필터로 시작한다.
- 자료 규모가 커질 때만 embedding/vector retrieval을 어댑터로 추가한다.

### Anchor 종류

| 종류 | 위치 |
|---|---|
| `text_line` | 시작/끝 줄과 문자 오프셋 |
| `pdf_block` | 페이지, block ID, bbox |
| `image_bbox` | 이미지 ID, 정규화 bbox, OCR text/confidence |
| `hwp_paragraph` | section/paragraph/table-cell 경로 |
| `chat_message` | 향후 message ID, 작성자, 시각 |
| `web_url` | URL, 제목, 접근 시각, 스니펫 해시 |

인용은 파일명이 아니라 불변 `SourceRevision`과 anchor를 참조한다(`.omx/specs/deep-interview-meeting-rag-platform.md:125-151`).

## 9. 데이터 모델

### 계정·협업

- `users`: email unique, password_hash, display_name
- `auth_sessions`: opaque token hash, user_id, expires_at
- `friendships`: requester_id, addressee_id, status, canonical_pair unique
- `rooms`: owner_id, name
- `room_memberships`: room_id, user_id, role, unique pair
- `room_invitations`: room_id, invitee_id, status

### 세션·원본

- `talk_sessions`: room_id, mode, topic, description, deadline, state
- `submissions`: session_id, author_id, kind
- `source_revisions`: submission_id, revision_no, filename, MIME, size, sha256, storage_key, processing_state
- `extracted_blocks`: revision_id, ordinal, text, block_type, confidence, anchor_json
- `generation_snapshots`: session_id, created_by, topic_copy, pipeline_version
- `snapshot_revisions`: snapshot_id, revision_id, unique pair

### 작업·생성

- `jobs`: type, payload_json, idempotency_key unique, state, attempts, lease_until, heartbeat_at, error_code
- `generation_runs`: snapshot_id, kind, provider, model, prompt_version, state
- `generated_documents`: run_id, kind, structured_content_json
- `generated_segments`: document_id, ordinal, text
- `citations`: segment_id, target_type, source_anchor_id/web_evidence_id
- `web_evidence`: url, title, domain, accessed_at, snippet_hash
- `research_claims`: run_id, claim_text, source_anchor_id, verdict, explanation

삭제 cascade는 원본 감사 추적을 깨뜨리지 않게 계획한다. 첫 마일스톤에는 사용자 셀프 삭제 UI를 두지 않는다.

## 10. API 표면

### 인증·친구

- `POST /api/auth/register|login|logout`
- `GET /api/me`
- `POST /api/friend-requests`
- `POST /api/friend-requests/{id}/accept|reject`
- `GET /api/friends`

### 방·세션

- `POST /api/rooms`, `GET /api/rooms`
- `POST /api/rooms/{roomId}/invitations`
- `POST /api/rooms/{roomId}/sessions`
- `GET /api/sessions/{sessionId}`
- `POST /api/sessions/{sessionId}/close`
- `POST /api/sessions/{sessionId}/retry`

### 제출·결과

- `POST /api/sessions/{sessionId}/submissions/text`
- `POST /api/sessions/{sessionId}/submissions/files`
- `PUT /api/submissions/{submissionId}`
- `GET /api/source-revisions/{revisionId}/original`
- `GET /api/source-revisions/{revisionId}/viewer?anchor=...`
- `GET /api/sessions/{sessionId}/summary|research`
- `GET /api/citations/{citationId}/resolve`

OpenAPI가 계약의 기준이며 web 클라이언트 타입을 생성한다. 대화형은 `ConversationMessage`와 `chat_message` anchor 스키마만 먼저 정의한다.

## 11. 보안·개인정보

- 비밀번호는 Argon2id, 세션은 DB에 hash로 저장한 opaque token을 사용한다.
- 쿠키는 HttpOnly, SameSite=Lax, 운영 HTTPS에서는 Secure. 상태 변경 요청은 CSRF token을 검증한다.
- 업로드는 확장자+magic/MIME allowlist, 무작위 storage key, 원본 이름 분리, web root 밖 저장을 적용한다.
- 원본은 attachment로 내려주고 이미지/PDF viewer도 안전한 content-type/CSP를 사용한다.
- 파서는 별도 worker 프로세스/컨테이너에서 non-root, 네트워크 차단, CPU/메모리/시간 제한으로 실행한다.
- ZIP/XML 기반 HWPX는 압축 폭탄과 XXE를 차단한다.
- Grok 요청 DTO는 storage key, 원본 URL, 파일 bytes 필드를 가지지 않는다.
- 로그에는 원문/추출문/비밀번호/API key를 남기지 않고 ID, 상태, latency, token usage만 기록한다.

## 12. 데모 준비 정의

1. Docker Compose로 web/api/worker/postgres 실행.
2. seed 계정 3개 생성.
3. Alice-Bob 친구/방/세션/다중 형식 제출.
4. Eve의 비인가 접근 거부.
5. 제출 마감과 mock 생성 완료.
6. 요약 원본 딥링크, 주제 조사 URL, 팩트체크 이중 인용 확인.
7. 같은 스냅샷 재시도 시 중복 결과가 생기지 않음.

세부 검증은 `.omx/plans/test-spec-meeting-rag-platform.md`를 따른다.
