import {
  Download,
  FileEdit,
  FolderPlus,
  MessageSquare,
  Sparkles,
  Upload,
  UserPlus,
  type LucideIcon,
} from 'lucide-react'

import { formatTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Activity, ActivityKind } from '@/types'

/** 활동 유형별 아이콘과 색. 히스토리 화면에서도 재사용합니다. */
export const activityKindMeta: Record<ActivityKind, { icon: LucideIcon; className: string }> = {
  upload: { icon: Upload, className: 'bg-line-soft text-ink-muted' },
  analysis: { icon: Sparkles, className: 'bg-line-soft text-ink-muted' },
  create: { icon: FolderPlus, className: 'bg-line-soft text-ink-muted' },
  comment: { icon: MessageSquare, className: 'bg-line-soft text-ink-muted' },
  edit: { icon: FileEdit, className: 'bg-line-soft text-ink-muted' },
  invite: { icon: UserPlus, className: 'bg-line-soft text-ink-muted' },
  export: { icon: Download, className: 'bg-line-soft text-ink-muted' },
  settings: { icon: FileEdit, className: 'bg-line-soft text-ink-muted' },
  system: { icon: Sparkles, className: 'bg-line-soft text-ink-muted' },
}

export interface ActivityFeedProps {
  activities: Activity[]
  className?: string
}

export function ActivityFeed({ activities, className }: ActivityFeedProps) {
  return (
    <ul className={cn('space-y-1', className)}>
      {activities.map((activity) => {
        const meta = activityKindMeta[activity.kind]
        return (
          <li
            key={activity.id}
            className="flex items-center gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-line-soft/70"
          >
            <span
              className={cn(
                'flex size-7 shrink-0 items-center justify-center rounded-lg',
                meta.className,
              )}
            >
              <meta.icon className="size-3.5" />
            </span>
            <p className="min-w-0 flex-1 text-[13px] leading-5 text-ink-muted">
              {/* AI 는 "AXit AI님이" 가 어색하므로 주어를 생략합니다. */}
              {activity.actor !== 'AXit AI' && (
                <>
                  <span className="font-bold text-ink">{activity.actor}</span>
                  <span>님이 </span>
                </>
              )}
              {activity.message}
            </p>
            <time className="shrink-0 text-[11.5px] text-ink-subtle tabular-nums">
              {formatTime(activity.createdAt)}
            </time>
          </li>
        )
      })}
    </ul>
  )
}
