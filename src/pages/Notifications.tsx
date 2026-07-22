import { PhasePlaceholder } from '@/components/common/PhasePlaceholder'

export default function Notifications() {
  return (
    <PhasePlaceholder
      title="알림"
      description="프로젝트 활동과 AI 분석 결과를 확인하세요."
      phase="Phase 1"
      planned={['전체 / 읽지 않음 탭', '알림 유형별 아이콘 구분', '모두 읽음 처리']}
    />
  )
}
