import { PhasePlaceholder } from '@/components/common/PhasePlaceholder'

export default function Editor() {
  return (
    <PhasePlaceholder
      title="통합 문서 편집"
      description="AI가 만든 통합 문서를 편집하고 공유하세요."
      phase="Phase 7"
      planned={[
        'Google Docs + Notion 스타일 에디터',
        '우측 AI 추천 패널 — 추가 · 수정 · 삭제 제안',
        '문서 구조(목차) 패널',
        '미리보기 · 다운로드 · 공유 · 버전 관리',
        'Autosave 지원',
      ]}
    />
  )
}
