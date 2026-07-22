import { PhasePlaceholder } from '@/components/common/PhasePlaceholder'

export default function Analysis() {
  return (
    <PhasePlaceholder
      title="AI 분석 진행 중"
      description="업로드된 문서를 분석하고 있습니다. 잠시만 기다려주세요."
      phase="Phase 5"
      planned={[
        '중앙 대형 Circular Progress',
        '5단계 Stepper — 업로드 · 내용 추출 · 공통점 · 차이점 · 통합 생성',
        '실시간 진행 애니메이션',
        '예상 완료 시간 및 분석 정보',
      ]}
    />
  )
}
