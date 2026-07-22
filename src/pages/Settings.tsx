import { PhasePlaceholder } from '@/components/common/PhasePlaceholder'

export default function Settings() {
  return (
    <PhasePlaceholder
      title="설정"
      description="계정, 알림, AI 분석 동작을 관리하세요."
      phase="Phase 3"
      planned={['계정 / 알림 / AI 분석 / 팀 / 플랜 탭', '프로필 편집', '사용량 표시']}
    />
  )
}
