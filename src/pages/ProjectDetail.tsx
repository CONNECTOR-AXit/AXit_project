import { PhasePlaceholder } from '@/components/common/PhasePlaceholder'

export default function ProjectDetail() {
  return (
    <PhasePlaceholder
      title="프로젝트 상세"
      description="프로젝트 정보와 참여 멤버, 업로드된 문서를 확인합니다."
      phase="Phase 3"
      planned={[
        '개요 / 문서 / 멤버 / 설정 탭 네비게이션',
        '프로젝트 정보 및 통합 완료율',
        '참여 멤버 목록과 권한 관리',
        '최근 활동 피드',
        '업로드된 문서 테이블',
      ]}
    />
  )
}
