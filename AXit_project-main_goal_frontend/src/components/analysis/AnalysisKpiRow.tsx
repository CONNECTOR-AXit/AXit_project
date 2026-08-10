import { AlertTriangle, FileText, ShieldCheck, type LucideIcon } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { AnalysisResult } from '@/types'

interface Tile {
  label: string
  value: string
  icon: LucideIcon
  className: string
}

export interface AnalysisKpiRowProps {
  result: AnalysisResult
  className?: string
}

/** 분석 결과 상단의 KPI — 문서 수 · 외부검증 항목 · 주의 필요 항목. */
export function AnalysisKpiRow({ result, className }: AnalysisKpiRowProps) {
  const needsAttention = result.differences.filter(
    (diff) =>
      diff.verdict === 'refuted' ||
      diff.verdict === 'mixed' ||
      diff.verdict === 'unverifiable',
  ).length

  const tiles: Tile[] = [
    {
      label: '문서 수',
      value: `${result.documentCount}`,
      icon: FileText,
      className: 'bg-line-soft text-ink-muted',
    },
    {
      label: '외부검증 항목',
      value: `${result.differenceCount}`,
      icon: ShieldCheck,
      className: 'bg-line-soft text-ink-muted',
    },
    {
      label: '주의 필요',
      value: `${needsAttention}`,
      icon: AlertTriangle,
      className: needsAttention > 0 ? 'bg-danger-soft text-danger' : 'bg-line-soft text-ink-muted',
    },
  ]

  return (
    <div className={cn('grid gap-3 sm:grid-cols-3', className)}>
      {tiles.map((tile) => (
        <div
          key={tile.label}
          className="flex items-center gap-3 rounded-xl bg-line-soft/50 px-4 py-3.5"
        >
          <span
            className={cn(
              'flex size-9 shrink-0 items-center justify-center rounded-lg',
              tile.className,
            )}
          >
            <tile.icon className="size-4" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-[12px] font-semibold text-ink-muted">{tile.label}</p>
            <p className="text-[22px] leading-7 font-extrabold tracking-tight text-ink tabular-nums">
              {tile.value}
            </p>
          </div>
        </div>
      ))}
    </div>
  )
}
