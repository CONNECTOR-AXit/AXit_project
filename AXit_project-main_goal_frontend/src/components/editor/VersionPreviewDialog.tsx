import { History, Loader2 } from 'lucide-react'

import { ApiError } from '@/api/client'
import { useMergedDocumentVersion } from '@/api/queries'
import { UserAvatar } from '@/components/common/UserAvatar'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { DocumentCanvas } from '@/components/editor/DocumentCanvas'
import { colorForName, formatDateTime } from '@/lib/format'
import type { DocumentVersion } from '@/types'

export interface VersionPreviewDialogProps {
  projectId: string
  version: DocumentVersion | null
  authorName?: string
  onClose: () => void
}

/** 클릭한 과거 버전의 문서 내용을 읽기 전용으로 보여줍니다. 복원 기능은 없습니다. */
export function VersionPreviewDialog({
  projectId,
  version,
  authorName,
  onClose,
}: VersionPreviewDialogProps) {
  const { data, isLoading, error } = useMergedDocumentVersion(projectId, version?.id ?? null)
  const displayAuthor = authorName ?? version?.author ?? ''

  return (
    <Dialog open={version !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <History className="size-4 text-primary" />
            {version?.label ?? '버전 미리보기'}
          </DialogTitle>
          <DialogDescription asChild>
            <div className="flex items-center gap-2">
              {version && (
                <Badge variant="neutral" className="font-mono text-[10px]">
                  v{version.versionNumber}
                </Badge>
              )}
              {version && (
                <span className="tabular-nums">{formatDateTime(version.createdAt)}</span>
              )}
              {displayAuthor && (
                <span className="flex items-center gap-1.5">
                  <UserAvatar
                    user={{ name: displayAuthor, color: colorForName(displayAuthor) }}
                    size="xs"
                    ring={false}
                  />
                  {displayAuthor}
                </span>
              )}
            </div>
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex min-h-40 items-center justify-center gap-2 text-[13px] text-ink-muted">
            <Loader2 className="size-4 animate-spin" />
            버전을 불러오는 중입니다...
          </div>
        ) : error ? (
          <p className="rounded-lg bg-danger-soft px-4 py-3 text-[13px] text-danger">
            {error instanceof ApiError ? error.message : '버전을 불러오지 못했습니다.'}
          </p>
        ) : data ? (
          <div className="max-h-[65vh] overflow-y-auto rounded-xl border border-line-soft p-5">
            <DocumentCanvas blocks={data.blocks} editable={false} />
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
