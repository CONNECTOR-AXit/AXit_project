import { FileText, GitCompare, Repeat2, ShieldCheck, type LucideIcon } from 'lucide-react'

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

/** 분석 결과 상단의 KPI 4종 — 문서 수 · 공통 · 차이점 · 중복률. */
export function AnalysisKpiRow({ result, className }: AnalysisKpiRowProps) {
  const tiles: Tile[] = [
    {
      label: '문서 수',
      value: `${result.documentCount}`,
      icon: FileText,
      className: 'bg-line-soft text-ink-muted',
    },
    {
      label: '공통 내용 항목',
      value: `${result.commonCount}`,
      icon: ShieldCheck,
      className: 'bg-line-soft text-ink-muted',
    },
    {
      label: '차이점 항목',
      value: `${result.differenceCount}`,
      icon: GitCompare,
      className: 'bg-line-soft text-ink-muted',
    },
    {
      label: '중복률 (평균)',
      value: `${result.overlapRate}%`,
      icon: Repeat2,
      className: 'bg-line-soft text-ink-muted',
    },
  ]

  return (
    <div className={cn('grid gap-3 sm:grid-cols-2 xl:grid-cols-4', className)}>
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
