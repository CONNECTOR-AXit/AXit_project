import { RotateCcw } from 'lucide-react'

import { UserAvatar } from '@/components/common/UserAvatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { userByName } from '@/data/members'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DocumentVersion } from '@/types'

export interface VersionHistoryProps {
  versions: DocumentVersion[]
  onRestore?: (version: DocumentVersion) => void
  className?: string
}

/** 버전 타임라인. 현재 버전을 표시하고 이전 버전은 복원할 수 있습니다. */
export function VersionHistory({ versions, onRestore, className }: VersionHistoryProps) {
  return (
    <ol className={cn('relative space-y-1 pl-2', className)}>
      <span className="absolute top-3 bottom-3 left-[13px] w-px bg-line" aria-hidden="true" />
      {versions.map((version) => (
        <li
          key={version.id}
          className="group relative flex gap-3 rounded-lg p-2 hover:bg-line-soft/70"
        >
          <span
            className={cn(
              'relative z-10 mt-1 size-2.5 shrink-0 rounded-full ring-4 ring-white',
              version.current ? 'bg-primary' : 'bg-line',
            )}
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-bold text-ink">{version.label}</span>
              {version.current && <Badge variant="primary">현재</Badge>}
              <time className="ml-auto shrink-0 text-[11px] text-ink-subtle tabular-nums">
                {formatDateTime(version.createdAt)}
              </time>
            </div>
            <p className="mt-1 text-[12.5px] leading-5 text-ink-muted">{version.summary}</p>
            <div className="mt-1.5 flex items-center gap-1.5">
              <UserAvatar user={userByName(version.author)} size="xs" ring={false} />
              <span className="text-[11.5px] font-medium text-ink-subtle">{version.author}</span>
              {!version.current && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onRestore?.(version)}
                  className="ml-auto h-6 px-2 text-[11px] opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                >
                  <RotateCcw className="size-3" />
                  복원
                </Button>
              )}
            </div>
          </div>
        </li>
      ))}
    </ol>
  )
}
