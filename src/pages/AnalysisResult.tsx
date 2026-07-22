import { PhasePlaceholder } from '@/components/common/PhasePlaceholder'

export default function AnalysisResult() {
  return (
    <PhasePlaceholder
      title="분석 결과"
      description="AI가 찾아낸 공통 내용과 차이점을 확인하세요."
      phase="Phase 6"
      planned={[
        '6개 탭 — 요약 · 공통 내용 · 차이점 · 문서별 분석 · 키워드 · AI Insight',
        'KPI 4종 — 문서 수 · 공통 내용 · 차이점 · 중복률',
        '문서별 기여도 Pie Chart',
        'AI Insight 카드',
      ]}
    />
  )
}
