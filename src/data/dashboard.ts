import type { DashboardStats, TrendPoint, WeeklyPoint } from '@/types'

/** 상단 KPI 4종. */
export const dashboardStats: DashboardStats = {
  projects: { value: 12, delta: 16.7 },
  documents: { value: 148, delta: 24.2 },
  analyses: { value: 96, delta: 12.4 },
  merged: { value: 34, delta: -4.1 },
}

/** 월별 업로드 문서 vs 통합 문서 — 대시보드 메인 차트. */
export const trend: TrendPoint[] = [
  { label: '1월', uploaded: 18, merged: 4 },
  { label: '2월', uploaded: 26, merged: 6 },
  { label: '3월', uploaded: 22, merged: 5 },
  { label: '4월', uploaded: 34, merged: 9 },
  { label: '5월', uploaded: 41, merged: 12 },
  { label: '6월', uploaded: 37, merged: 10 },
  { label: '7월', uploaded: 52, merged: 16 },
]

/** 요일별 AI 분석 · 통합 건수. */
export const weeklyActivity: WeeklyPoint[] = [
  { label: '월', 분석: 8, 통합: 3 },
  { label: '화', 분석: 12, 통합: 5 },
  { label: '수', 분석: 6, 통합: 2 },
  { label: '목', 분석: 15, 통합: 7 },
  { label: '금', 분석: 11, 통합: 4 },
  { label: '토', 분석: 3, 통합: 1 },
  { label: '일', 분석: 2, 통합: 1 },
]

/** 이번 달 AI 크레딧 사용량. */
export const aiCredit = { used: 32, total: 50 } as const

/**
 * 데모 기준 시각.
 * 더미 데이터의 날짜가 고정되어 있으므로 "3시간 전" 같은 상대 표기가
 * 항상 같은 결과를 내도록 기준 시각을 하나로 고정합니다.
 */
export const DEMO_NOW = new Date('2024-05-16T15:00:00')
