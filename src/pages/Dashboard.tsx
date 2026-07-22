import { PhasePlaceholder } from '@/components/common/PhasePlaceholder'
import { currentUser } from '@/data/user'

export default function Dashboard() {
  return (
    <PhasePlaceholder
      title={`안녕하세요, ${currentUser.name}님 👋`}
      description="오늘의 문서 통합 현황을 한눈에 확인하세요."
      phase="Phase 1"
      planned={[
        'KPI 카드 4종 — 프로젝트 수 · 업로드 문서 · AI 분석 완료 · 통합 문서',
        '문서 통합 추이 Area 차트',
        'AI 진행 현황 패널',
        '최근 프로젝트 · 최근 활동',
        '최근 생성된 통합 문서 목록',
      ]}
    />
  )
}
