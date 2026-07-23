import { AnimatePresence, motion } from 'framer-motion'
import { CheckCircle2, RotateCcw, Trash2 } from 'lucide-react'

import { FileTypeIcon } from '@/components/common/FileTypeIcon'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import type { UploadItem } from '@/hooks/useUploadQueue'
import { formatBytes, formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'

export interface UploadListProps {
  items: UploadItem[]
  onRemove: (id: string) => void
  onRetry: (id: string) => void
  className?: string
}

/** 업로드된 파일 목록. 진행률과 상태를 파일별로 표시합니다. */
export function UploadList({ items, onRemove, onRetry, className }: UploadListProps) {
  return (
    <ul className={cn('divide-y divide-line-soft', className)}>
      <AnimatePresence initial={false}>
        {items.map((item) => (
          <motion.li
            key={item.id}
            layout
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, x: 24, height: 0, marginTop: 0, marginBottom: 0 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            className="group flex items-center gap-3 py-3"
          >
            <FileTypeIcon kind={item.kind} size="sm" />

            <div className="min-w-0 flex-[1.4]">
              <p className="truncate text-[13px] font-semibold text-ink">{item.name}</p>
              <p className="text-[11.5px] text-ink-subtle tabular-nums">{formatBytes(item.size)}</p>
            </div>

            {/* 상태 라벨 — 완료 시 아이콘을 함께 붙여 색 외에도 구분됩니다. */}
            <span
              className={cn(
                'hidden shrink-0 items-center gap-1 text-[12px] font-bold sm:flex',
                item.status === 'failed'
                  ? 'text-danger'
                  : item.status === 'uploading'
                    ? 'text-primary'
                    : 'text-secondary-600',
              )}
            >
              {item.status === 'uploaded' && <CheckCircle2 className="size-3.5" />}
              {statusLabel(item.status)}
            </span>

            <time className="hidden shrink-0 text-[11.5px] text-ink-subtle tabular-nums lg:block">
              {formatDateTime(item.addedAt)}
            </time>

            <div className="flex w-[110px] shrink-0 items-center gap-2 sm:w-[160px]">
              <Progress
                value={item.progress}
                tone={
                  item.status === 'failed' ? 'danger' : item.progress >= 100 ? 'success' : 'primary'
                }
                className="flex-1"
              />
              <span className="w-9 shrink-0 text-right text-[11.5px] font-bold text-ink-muted tabular-nums">
                {Math.round(item.progress)}%
              </span>
            </div>

            {item.status === 'failed' ? (
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => onRetry(item.id)}
                aria-label={`${item.name} 다시 시도`}
              >
                <RotateCcw />
              </Button>
            ) : (
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => onRemove(item.id)}
                aria-label={`${item.name} 삭제`}
                className="text-ink-subtle hover:bg-danger-soft hover:text-danger"
              >
                <Trash2 />
              </Button>
            )}
          </motion.li>
        ))}
      </AnimatePresence>
    </ul>
  )
}

function statusLabel(status: UploadItem['status']) {
  switch (status) {
    case 'uploading':
      return '업로드 중'
    case 'uploaded':
      return '업로드 완료'
    case 'analyzed':
      return '분석 완료'
    case 'failed':
      return '실패'
    default:
      return '대기 중'
  }
}
