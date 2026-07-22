import type { ReactNode } from 'react'

export interface TooltipEntry {
  name?: ReactNode
  value?: number | string
  color?: string
  dataKey?: string | number
}

export interface ChartTooltipProps {
  active?: boolean
  label?: ReactNode
  payload?: TooltipEntry[]
  /** 값 뒤에 붙일 단위. 예) `건`, `%` */
  unit?: string
  /** dataKey 를 한글 라벨로 바꿀 때 사용합니다. */
  labelMap?: Record<string, string>
}

/**
 * 모든 차트가 공유하는 툴팁.
 * 색 점은 계열 식별용이고, 수치와 라벨은 텍스트 토큰을 그대로 씁니다.
 */
export function ChartTooltip({ active, label, payload, unit = '', labelMap }: ChartTooltipProps) {
  if (!active || !payload?.length) return null

  return (
    <div className="rounded-lg border border-line bg-white px-3 py-2 shadow-pop">
      {label !== undefined && label !== '' && (
        <p className="mb-1.5 text-[11px] font-bold text-ink-subtle">{label}</p>
      )}
      <ul className="space-y-1">
        {payload.map((entry, index) => {
          const key = String(entry.dataKey ?? entry.name ?? index)
          return (
            <li key={key} className="flex items-center gap-2 text-[12px]">
              <span
                className="size-2 shrink-0 rounded-full"
                style={{ backgroundColor: entry.color }}
              />
              <span className="text-ink-muted">{labelMap?.[key] ?? entry.name}</span>
              <span className="ml-auto font-bold text-ink tabular-nums">
                {entry.value}
                {unit}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export interface ChartLegendItem {
  label: string
  color: string
}

/**
 * 차트 범례.
 * 계열이 2개 이상이면 항상 표시해 색상만으로 구분하지 않도록 합니다.
 */
export function ChartLegend({ items }: { items: ChartLegendItem[] }) {
  return (
    <div className="flex items-center gap-3 text-[11.5px] font-semibold text-ink-muted">
      {items.map((item) => (
        <span key={item.label} className="flex items-center gap-1.5">
          <span className="size-2 rounded-full" style={{ backgroundColor: item.color }} />
          {item.label}
        </span>
      ))}
    </div>
  )
}
