import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'

import { cn } from '@/lib/utils'
import { ChartTooltip } from './ChartTooltip'
import { chartPalette } from './palette'

export interface ContributionDatum {
  name: string
  value: number
}

export interface ContributionPieChartProps {
  data: ContributionDatum[]
  /** 도넛 가운데에 표시할 텍스트. */
  centerLabel?: string
  centerCaption?: string
  height?: number
  className?: string
}

/** 각 원본 문서가 통합에 기여한 비율을 보여주는 도넛 차트. */
export function ContributionPieChart({
  data,
  centerLabel = '기여도',
  centerCaption = '내용 기준',
  height = 220,
  className,
}: ContributionPieChartProps) {
  return (
    <div className={cn('flex flex-col items-center gap-5 sm:flex-row', className)}>
      <div className="relative shrink-0" style={{ width: height, height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              innerRadius="62%"
              outerRadius="92%"
              paddingAngle={2}
              stroke="none"
              startAngle={90}
              endAngle={-270}
            >
              {data.map((entry, index) => (
                <Cell key={entry.name} fill={chartPalette[index % chartPalette.length]} />
              ))}
            </Pie>
            <Tooltip content={<ChartTooltip unit="%" />} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-[13px] font-bold text-ink">{centerLabel}</span>
          <span className="text-[11px] text-ink-subtle">({centerCaption})</span>
        </div>
      </div>

      <ul className="w-full min-w-0 flex-1 space-y-2.5">
        {data.map((entry, index) => (
          <li key={entry.name} className="flex items-center gap-2.5 text-[13px]">
            <span
              className="size-2.5 shrink-0 rounded-[3px]"
              style={{ backgroundColor: chartPalette[index % chartPalette.length] }}
            />
            <span className="min-w-0 flex-1 truncate font-medium text-ink-muted">{entry.name}</span>
            <span className="font-bold text-ink tabular-nums">{entry.value}%</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
