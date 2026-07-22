import { PhasePlaceholder } from '@/components/common/PhasePlaceholder'

export default function Documents() {
  return (
    <PhasePlaceholder
      title="통합 문서"
      description="AI가 생성한 통합 문서를 한곳에서 확인하고 이어서 편집하세요."
      phase="Phase 7"
      planned={['통합 문서 카드 목록', '검색 · 정렬', '편집기로 바로 이동']}
    />
  )
}
