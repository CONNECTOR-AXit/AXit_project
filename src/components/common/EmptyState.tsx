import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

export interface EmptyStateProps {
  icon: LucideIcon
  title: string
  description?: string
  /** 다음 행동을 유도하는 버튼. */
  action?: ReactNode
  className?: string
}

/** 데이터가 없을 때 표시하는 빈 상태 안내. */
export function EmptyState({ icon: Icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-line bg-white/60 px-6 py-14 text-center',
        className,
      )}
    >
      <span className="flex size-12 items-center justify-center rounded-2xl bg-line-soft text-ink-subtle">
        <Icon className="size-5.5" />
      </span>
      <div className="space-y-1">
        <p className="text-sm font-bold text-ink">{title}</p>
        {description && (
          <p className="mx-auto max-w-sm text-[13px] leading-5 text-ink-muted">{description}</p>
        )}
      </div>
      {action && <div className="mt-1">{action}</div>}
    </div>
  )
}
