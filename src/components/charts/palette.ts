/**
 * 차트 전용 색상 정의.
 *
 * 브랜드 Secondary(#38D0B8)는 흰 카드 위에서 너무 밝아 차트 마크로 쓸 수 없습니다.
 * (OKLab L 0.774 로 밴드 초과, 대비 1.93:1)
 * 그래서 차트에서는 한 단계 진한 secondary-500(#1EB69F)을 사용합니다.
 *
 * 아래 순서는 검증 스크립트를 통과한 조합입니다.
 *   명도 밴드 PASS · 채도 하한 PASS
 *   색각이상 분리 ΔE 22.5 (deutan) / 13.2 (tritan) PASS
 *   정상시야 분리 ΔE 23.2 PASS
 *
 * 대비 경고(#1EB69F 2.55:1, #F59E0B 2.15:1)는 범례와 값 라벨을 항상 함께
 * 표시하는 것으로 해소합니다. 색상만으로 계열을 구분하지 않습니다.
 *
 * 계열 색은 고정 순서로 배정하며 순환시키지 않습니다.
 */
export const chartPalette = ['#0F73D8', '#1EB69F', '#8B5CF6', '#F59E0B', '#DB2777'] as const

/** 업로드 문서 계열. */
export const SERIES_UPLOADED = chartPalette[0]

/** 통합 문서 계열. */
export const SERIES_MERGED = chartPalette[1]

/**
 * 축 공통 설정.
 * 눈금선과 축선을 제거해 데이터 마크가 앞으로 나오게 합니다.
 */
export const axisProps = {
  stroke: 'transparent',
  tick: { fill: 'var(--color-ink-subtle)', fontSize: 11, fontWeight: 600 },
  tickLine: false,
  axisLine: false,
} as const

/** 그리드 공통 설정 — 가로선만, 점선으로 후퇴시킵니다. */
export const gridProps = {
  stroke: 'var(--color-line)',
  strokeDasharray: '4 4',
  vertical: false,
} as const
