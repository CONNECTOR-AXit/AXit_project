import { AnimatePresence, motion } from 'framer-motion'
import { CheckCircle2, Eye, RotateCcw, Trash2 } from 'lucide-react'
import { useRef } from 'react'

import { FileTypeIcon } from '@/components/common/FileTypeIcon'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import type { UploadItem } from '@/hooks/useUploadQueue'
import { formatBytes, formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'

const REUPLOAD_ACCEPT =
  '.pdf,.docx,.doc,.hwp,.hwpx,.txt,.pptx,.ppt,.xlsx,.xls,.png,.jpg,.jpeg'

export interface UploadListProps {
  items: UploadItem[]
  onRemove: (id: string) => void
  /**
   * 서버에 이미 저장된(리비전 ID가 있는) 실패 항목을 다시 처리합니다 — 같은
   * 파일 그대로 서버에서 파싱을 다시 시도할 뿐, 파일을 새로 받지 않습니다.
   */
  onRetryExtraction: (revisionId: string) => void
  /** 업로드 자체가 서버에 닿지 못하고 실패한(리비전 ID가 없는) 항목만 새로 고른 파일로 대체합니다. */
  onReupload: (id: string, file: File) => void
  /** 서버에 저장된 문서(리비전 ID가 있는 항목)에서만 뜹니다. */
  onPreview: (item: UploadItem) => void
  className?: string
}

/** 업로드된 파일 목록. 진행률과 상태를 파일별로 표시합니다. */
export function UploadList({
  items,
  onRemove,
  onRetryExtraction,
  onReupload,
  onPreview,
  className,
}: UploadListProps) {
  const reuploadInputs = useRef<Record<string, HTMLInputElement | null>>({})
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
                  : item.status === 'analyzed'
                    ? 'text-success'
                    : 'text-warning',
              )}
            >
              {item.status === 'analyzed' && <CheckCircle2 className="size-3.5" />}
              {statusLabel(item)}
            </span>

            <time className="hidden shrink-0 text-[11.5px] text-ink-subtle tabular-nums lg:block">
              {formatDateTime(item.addedAt)}
            </time>

            <div className="flex w-[110px] shrink-0 items-center gap-2 sm:w-[160px]">
              <Progress
                value={item.progress}
                tone={
                  item.status === 'failed' ? 'danger' : item.progress >= 100 ? 'success' : 'warning'
                }
                className="flex-1"
              />
              <span className="w-9 shrink-0 text-right text-[11.5px] font-bold text-ink-muted tabular-nums">
                {Math.round(item.progress)}%
              </span>
            </div>

            <div className="flex shrink-0 items-center gap-0.5">
              {item.revisionId && item.status !== 'failed' && (
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => onPreview(item)}
                  aria-label={`${item.name} 보기`}
                  className="text-ink-subtle hover:bg-primary-50 hover:text-primary"
                >
                  <Eye />
                </Button>
              )}
              {item.status === 'failed' &&
                (item.revisionId ? (
                  // 서버에 이미 올라간 파일 — 그대로 서버에서 다시 처리하게 시킵니다.
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => onRetryExtraction(item.revisionId!)}
                    aria-label={`${item.name} 다시 처리`}
                  >
                    <RotateCcw />
                  </Button>
                ) : (
                  // 업로드 자체가 서버에 닿지 못한 경우만 파일을 새로 골라야 합니다.
                  <>
                    <input
                      ref={(el) => {
                        reuploadInputs.current[item.id] = el
                      }}
                      type="file"
                      accept={REUPLOAD_ACCEPT}
                      className="sr-only"
                      aria-label={`${item.name} 재업로드할 파일 선택`}
                      onChange={(event) => {
                        const file = event.target.files?.[0]
                        event.target.value = ''
                        if (file) onReupload(item.id, file)
                      }}
                    />
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => reuploadInputs.current[item.id]?.click()}
                      aria-label={`${item.name} 재업로드`}
                    >
                      <RotateCcw />
                    </Button>
                  </>
                ))}
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => onRemove(item.id)}
                aria-label={`${item.name} 삭제`}
                className="text-ink-subtle hover:bg-danger-soft hover:text-danger"
              >
                <Trash2 />
              </Button>
            </div>
          </motion.li>
        ))}
      </AnimatePresence>
    </ul>
  )
}

function statusLabel(item: UploadItem) {
  switch (item.status) {
    case 'uploading':
      return '업로드 중'
    case 'queued':
      // 서버에 이미 저장된(revisionId 있음) 뒤라면 전송 대기가 아니라
      // 문서 처리(추출)를 기다리는 중입니다.
      return item.revisionId ? '처리 중' : '업로드 대기'
    case 'analyzed':
      return '업로드 완료'
    case 'failed':
      return '처리 실패'
    default:
      return '대기 중'
  }
}
