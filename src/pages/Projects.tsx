import { PhasePlaceholder } from '@/components/common/PhasePlaceholder'

export default function Projects() {
  return (
    <PhasePlaceholder
      title="프로젝트"
      description="모든 문서 통합 프로젝트를 관리하세요."
      phase="Phase 2"
      planned={[
        '카드형 Grid — 프로젝트명 · 생성일 · 문서 수 · 멤버 수 · 진행률 · 상태',
        '검색 · 정렬 · 상태 필터 툴바',
        '새 프로젝트 생성 다이얼로그',
        'Grid / List 보기 전환',
      ]}
    />
  )
}
