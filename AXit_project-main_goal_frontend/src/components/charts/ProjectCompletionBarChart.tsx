import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { INTEGRATION_PROGRESS_STEPS, type WeekdayCompletionPoint } from '@/types'
import { ChartTooltip } from './ChartTooltip'
import { SERIES_MERGED, axisProps, gridProps } from './palette'

export interface ProjectCompletionBarChartProps {
  data: WeekdayCompletionPoint[]
}

/** 프로젝트 최종 수정 요일별 평균 통합 완료율. */
export function ProjectCompletionBarChart({ data }: ProjectCompletionBarChartProps) {
  const summary = data
    .filter((point) => point.projects > 0)
    .map((point) => `${point.label}요일 ${point.progress}%`)
    .join(', ')

  return (
    <div
      className="h-[220px] w-full"
      role="img"
      aria-label={`요일별 프로젝트 평균 통합 완료율: ${summary}`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 12, right: 4, left: 4, bottom: 0 }}>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="label" {...axisProps} dy={6} />
          <YAxis
            {...axisProps}
            width={48}
            domain={[0, 100]}
            ticks={INTEGRATION_PROGRESS_STEPS}
            tickFormatter={(value: number) => `${value}%`}
            allowDecimals={false}
          />
          <Tooltip
            cursor={{ fill: 'var(--color-primary-50)', opacity: 0.55 }}
            content={<ChartTooltip unit="%" labelMap={{ progress: '평균 완료율' }} />}
          />
          <Bar
            dataKey="progress"
            name="평균 완료율"
            fill={SERIES_MERGED}
            radius={[5, 5, 0, 0]}
            maxBarSize={28}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
