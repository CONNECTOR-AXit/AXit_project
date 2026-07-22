# AXit

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

```bash
npm install
npm run dev      # 개발 서버 (http://localhost:5173)
npm run build    # 타입 체크 + 프로덕션 빌드
npm run preview  # 빌드 결과 미리보기
npm run lint     # 정적 분석
```

## 프로젝트 구조

```
src/
  components/   layout · ui · dashboard · project · upload · analysis · editor · charts · common
  pages/        라우트 단위 페이지
  data/         더미 데이터 (페이지에서 import 하여 사용)
  hooks/        커스텀 훅
  lib/          유틸리티 · 포매터
  types/        도메인 타입 정의
```

## 개발 순서

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

## 브랜치 전략

- `main` — 초기 설정 커밋
- `frontend` — Phase 0 이후 모든 기능 개발
