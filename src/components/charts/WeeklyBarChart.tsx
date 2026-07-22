import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import type { WeeklyPoint } from '@/types'
import { ChartTooltip } from './ChartTooltip'
import { SERIES_MERGED, SERIES_UPLOADED, axisProps, gridProps } from './palette'

export interface WeeklyBarChartProps {
  data: WeeklyPoint[]
  height?: number
}

/**
 * 요일별 AI 분석 · 통합 건수.
 * barGap 2px 로 인접 막대 사이에 배경이 비쳐 경계가 분리됩니다.
 */
export function WeeklyBarChart({ data, height = 200 }: WeeklyBarChartProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 4, left: -22, bottom: 0 }} barGap={2}>
        <CartesianGrid {...gridProps} />
        <XAxis dataKey="label" {...axisProps} dy={6} />
        <YAxis {...axisProps} width={44} />
        <Tooltip cursor={{ fill: 'var(--color-line-soft)' }} content={<ChartTooltip unit="건" />} />

        {/* 데이터 끝만 둥글게, 기준선 쪽은 각지게 유지합니다. */}
        <Bar dataKey="분석" fill={SERIES_UPLOADED} radius={[4, 4, 0, 0]} maxBarSize={14} />
        <Bar dataKey="통합" fill={SERIES_MERGED} radius={[4, 4, 0, 0]} maxBarSize={14} />
      </BarChart>
    </ResponsiveContainer>
  )
}
