import { cn } from '@/lib/utils'

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
              className="rounded-md bg-line-soft px-1.5 py-0.5 text-[11px] font-bold text-ink-muted"
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
  medium: { dot: 'bg-warning', label: '보통', badge: 'warning' },
  low: { dot: 'bg-line', label: '낮음', badge: 'neutral' },
} as const
