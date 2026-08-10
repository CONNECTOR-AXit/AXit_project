export interface AnalysisStep {
  id: 'extract' | 'common' | 'difference' | 'merge' | 'suggestions'
  label: string
  caption: string
}

/** 분석 화면에 노출되는 5단계 파이프라인. 실제 백엔드 작업 순서와 일치합니다. */
export const analysisSteps: AnalysisStep[] = [
  { id: 'extract', label: '내용 추출', caption: '문서에서 텍스트와 표를 읽는 중' },
  { id: 'common', label: '요약 문서 생성', caption: '문서별 핵심 내용을 근거와 함께 요약하는 중' },
  { id: 'difference', label: '외부 검증', caption: '문서의 주요 주장을 외부 자료로 검증하는 중' },
  { id: 'merge', label: '통합 문서 생성', caption: '하나의 문서로 재구성하는 중' },
  { id: 'suggestions', label: '수정 추천안 준비', caption: '통합 문서를 검토해 수정 추천안을 준비하는 중' },
]

export type StepState = 'done' | 'active' | 'waiting'
