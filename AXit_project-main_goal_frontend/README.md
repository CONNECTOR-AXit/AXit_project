# AXit

> **현재 프런트엔드 기준 경로**: 모든 신규 화면·기능 작업은 이
> `AXit_project-main_goal_frontend` 폴더에서 진행합니다. 이전 참고본이었던
> 저장소 루트의 `Frontend`와 `Final` 폴더는 기능 이관 완료 후 삭제됐으며
> 실행·배포·문서 경로로 사용하지 않습니다.

## Upstream synchronization

- UI source: `https://github.com/CONNECTOR-AXit/AXit_project`
- Last reviewed upstream commit: `c72eeb13fbc7a131bee7d10995ccbd7caeef3de9`
- Reviewed on: `2026-08-06`

The upstream repository is a design/demo surface whose API and authentication
layers use local dummy data. This active folder selectively adopts its latest
pages and navigation while retaining the production FastAPI gateway, HttpOnly
session cookie, CSRF, upload, session, analysis, and report integrations.

여러 문서를 업로드하면 AI가 **공통 내용 · 차이점 · 핵심 내용**을 정리하고
하나의 **통합 문서**를 만들어주는 문서 협업 플랫폼입니다.

## 기술 스택

| 구분 | 사용 기술 |
| --- | --- |
| Core | React 19, TypeScript (strict), Vite |
| Style | Tailwind CSS v4, shadcn/ui 패턴 |
| Routing | React Router |
| Data | TanStack Query, Axios |
| UI | lucide-react, Framer Motion, Recharts, Radix UI |

## 시작하기

저장소 루트에서 실행합니다.

```bash
corepack pnpm install
corepack pnpm --dir AXit_project-main_goal_frontend run dev       # http://localhost:5173
corepack pnpm --dir AXit_project-main_goal_frontend run typecheck
corepack pnpm --dir AXit_project-main_goal_frontend run lint
corepack pnpm --dir AXit_project-main_goal_frontend run test
corepack pnpm --dir AXit_project-main_goal_frontend run build
```

## 프로젝트 구조

```
src/
  components/   layout · ui · dashboard · project · upload · analysis · editor · charts · common
  pages/        라우트 단위 페이지
  data/         표시 메타데이터와 정적 UI 설명
  api/          실제 FastAPI 쿼리·뮤테이션 및 CSRF 클라이언트
  auth/         HttpOnly 세션 기반 인증 컨텍스트
  hooks/        커스텀 훅
  lib/          유틸리티 · 포매터
  types/        도메인 타입 정의
```

## 원본 UI 구현 이력 (참고)

| Phase | 내용 |
| --- | --- |
| 0 | 프로젝트 구조 · Router · Layout · Theme · Dummy Data |
| 1 | Dashboard |
| 2 | 프로젝트 목록 |
| 3 | 프로젝트 상세 |
| 4 | 문서 업로드 |
| 5 | AI 분석 진행 |
| 6 | 분석 결과 |
| 7 | 통합 문서 편집기 |
| 8 | 반응형 |
| 9 | 애니메이션 |

## 원본 UI 브랜치 이력 (참고)

- `main` — 초기 설정 커밋
- `frontend` — Phase 0 이후 모든 기능 개발
