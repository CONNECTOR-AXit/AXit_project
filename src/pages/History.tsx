import { PhasePlaceholder } from '@/components/common/PhasePlaceholder'

export default function History() {
  return (
    <PhasePlaceholder
      title="히스토리"
      description="프로젝트에서 일어난 모든 변경 기록입니다."
      phase="Phase 3"
      planned={['일자별 그룹 타임라인', '활동 유형 필터', '기록 검색']}
    />
  )
}
