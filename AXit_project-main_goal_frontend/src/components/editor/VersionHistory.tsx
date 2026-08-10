import { Loader2, Save } from 'lucide-react'

import { UserAvatar } from '@/components/common/UserAvatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { colorForName, formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DocumentVersion } from '@/types'

export interface VersionHistoryProps {
  versions: DocumentVersion[]
  /** "현재 버전으로 저장" 버튼 클릭 핸들러 — 없으면 버튼 자체를 숨깁니다. */
  onCreateVersion?: () => void
  isCreating?: boolean
  /** 버전을 클릭하면 그 시점의 문서를 미리 볼 수 있게 합니다. */
  onSelectVersion?: (version: DocumentVersion) => void
  className?: string
}

/** 버전 타임라인 — 실제로 저장된 버전만 나열합니다(가짜 v1.0 항목 없음). */
export function VersionHistory({
  versions,
  onCreateVersion,
  isCreating,
  onSelectVersion,
  className,
}: VersionHistoryProps) {
  return (
    <div className={cn('space-y-3', className)}>
      {onCreateVersion && (
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          disabled={isCreating}
          onClick={onCreateVersion}
        >
          {isCreating ? <Loader2 className="animate-spin" /> : <Save />}
          현재 버전으로 저장
        </Button>
      )}

      {versions.length === 0 ? (
        <p className="px-2 py-4 text-center text-[12px] text-ink-subtle">
          아직 저장된 버전이 없어요. 위 버튼으로 현재 문서를 첫 버전으로 남겨보세요.
        </p>
      ) : (
        <ol className="relative space-y-1 pl-2">
          <span className="absolute top-3 bottom-3 left-[13px] w-px bg-line" aria-hidden="true" />
          {versions.map((version) => (
            <li key={version.id} className="group relative">
              <button
                type="button"
                disabled={!onSelectVersion}
                onClick={() => onSelectVersion?.(version)}
                className={cn(
                  'flex w-full gap-3 rounded-lg p-2 text-left transition-colors',
                  onSelectVersion && 'hover:bg-line-soft/70',
                )}
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
                    <Badge variant="neutral" className="font-mono text-[10px]">
                      v{version.versionNumber}
                    </Badge>
                    {version.current && <Badge variant="primary">최신</Badge>}
                    <time className="ml-auto shrink-0 text-[11px] text-ink-subtle tabular-nums">
                      {formatDateTime(version.createdAt)}
                    </time>
                  </div>
                  <div className="mt-1.5 flex items-center gap-1.5">
                    <UserAvatar
                      user={{ name: version.author, color: colorForName(version.author) }}
                      size="xs"
                      ring={false}
                    />
                    <span className="text-[11.5px] font-medium text-ink-subtle">{version.author}</span>
                  </div>
                </div>
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
