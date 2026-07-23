import { cn } from '@/lib/utils'

const chipTone = [
  'bg-primary-50 text-primary',
  'bg-secondary-50 text-secondary-600',
  'bg-violet-50 text-violet-500',
  'bg-warning-soft text-warning',
  'bg-line-soft text-ink-muted',
] as const

export interface DocumentChipsProps {
  /** 클러스터 라벨. 예) `[['문서 A','문서 B'], ['문서 C']]` */
  clusters: string[][]
  className?: string
}

/** 문서 클러스터를 가운뎃점으로 구분해 표시합니다. `A, B · C, D` */
export function DocumentChips({ clusters, className }: DocumentChipsProps) {
  return (
    <div className={cn('flex flex-wrap items-center gap-1.5', className)}>
      {clusters.map((cluster, clusterIndex) => (
        <span key={clusterIndex} className="flex items-center gap-1.5">
          {clusterIndex > 0 && <span className="px-0.5 text-ink-subtle">·</span>}
          {cluster.map((label) => (
            <span
              key={label}
              className={cn(
                'rounded-md px-1.5 py-0.5 text-[11px] font-bold',
                chipTone[clusterIndex % chipTone.length],
              )}
            >
              {label.replace('문서 ', '')}
            </span>
          ))}
        </span>
      ))}
    </div>
  )
}

export const severityTone = {
  high: { dot: 'bg-danger', label: '높음', badge: 'danger' },
  medium: { dot: 'bg-primary', label: '보통', badge: 'primary' },
  low: { dot: 'bg-warning', label: '낮음', badge: 'warning' },
} as const
