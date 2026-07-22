import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { TrendPoint } from '@/types'
import { ChartTooltip } from './ChartTooltip'
import { SERIES_MERGED, SERIES_UPLOADED, axisProps, gridProps } from './palette'

const labelMap = { uploaded: '업로드 문서', merged: '통합 문서' }

export interface TrendAreaChartProps {
  data: TrendPoint[]
  height?: number
}

/**
 * 월별 업로드 문서 vs 통합 문서 추이.
 * 두 계열 모두 "문서 건수"라는 같은 단위이므로 축 하나를 공유합니다.
 */
export function TrendAreaChart({ data, height = 260 }: TrendAreaChartProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
        <defs>
          {/* 면은 옅게 깔고 선이 값을 읽게 합니다. */}
          <linearGradient id="axit-area-uploaded" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={SERIES_UPLOADED} stopOpacity={0.26} />
            <stop offset="100%" stopColor={SERIES_UPLOADED} stopOpacity={0} />
          </linearGradient>
          <linearGradient id="axit-area-merged" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={SERIES_MERGED} stopOpacity={0.28} />
            <stop offset="100%" stopColor={SERIES_MERGED} stopOpacity={0} />
          </linearGradient>
        </defs>

        <CartesianGrid {...gridProps} />
        <XAxis dataKey="label" {...axisProps} dy={6} />
        <YAxis {...axisProps} width={48} />
        <Tooltip
          cursor={{ stroke: 'var(--color-line)', strokeWidth: 1 }}
          content={<ChartTooltip unit="건" labelMap={labelMap} />}
        />

        <Area
          type="monotone"
          dataKey="uploaded"
          name={labelMap.uploaded}
          stroke={SERIES_UPLOADED}
          strokeWidth={2}
          fill="url(#axit-area-uploaded)"
          activeDot={{ r: 4, strokeWidth: 2, stroke: '#fff' }}
        />
        <Area
          type="monotone"
          dataKey="merged"
          name={labelMap.merged}
          stroke={SERIES_MERGED}
          strokeWidth={2}
          fill="url(#axit-area-merged)"
          activeDot={{ r: 4, strokeWidth: 2, stroke: '#fff' }}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
