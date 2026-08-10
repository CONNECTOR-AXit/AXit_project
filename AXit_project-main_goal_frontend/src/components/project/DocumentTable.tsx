import { AlertCircle, Download, Eye, Loader2, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { api, ApiError } from '@/api/client'
import { FileTypeIcon } from '@/components/common/FileTypeIcon'
import { DocumentStatusBadge } from '@/components/common/StatusBadge'
import { DocumentSummaryDialog } from '@/components/project/DocumentSummaryDialog'
import { DocumentPreviewDialog, type PreviewTarget } from '@/components/upload/DocumentPreviewDialog'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { formatBytes, formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DocumentFile } from '@/types'

export interface DocumentTableProps {
  documents: DocumentFile[]
  /** 업로더 열을 숨깁니다. 좁은 컨테이너에서 사용합니다. */
  compact?: boolean
  className?: string
  onDelete?: (submissionId: string) => Promise<void>
}

/**
 * 업로드된 문서 목록.
 * 표는 최소 폭을 유지하고 컨테이너가 좁아지면 가로로만 스크롤됩니다.
 * 페이지 자체가 가로로 밀리지 않습니다.
 */
export function DocumentTable({ documents, compact = false, className, onDelete }: DocumentTableProps) {
  const columns = ['문서명', '크기', ...(compact ? [] : ['업로드']), '상태', '업로드 일시', '']
  const [previewTarget, setPreviewTarget] = useState<PreviewTarget | null>(null)
  const [summaryDocument, setSummaryDocument] = useState<DocumentFile | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<DocumentFile | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const downloadOriginal = async (doc: DocumentFile) => {
    setActionError(null)
    try {
      let blob: Blob
      let filename = doc.name
      if (doc.submissionKind === 'text') {
        const response = await api.get<{ text: string }>(`/source-revisions/${doc.revisionId}/viewer`)
        blob = new Blob([response.data.text], { type: 'text/markdown;charset=utf-8' })
        if (!filename.toLowerCase().endsWith('.md')) filename = `${filename}.md`
      } else {
        const response = await api.get<Blob>(`/source-revisions/${doc.revisionId}/original`, {
          responseType: 'blob',
        })
        blob = response.data
      }
      const url = URL.createObjectURL(blob)
      const link = window.document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 0)
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : '원본 문서를 다운로드하지 못했습니다.')
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget || !onDelete) return
    setDeleting(true)
    setActionError(null)
    try {
      await onDelete(deleteTarget.id)
      setDeleteTarget(null)
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : '문서를 삭제하지 못했습니다.')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className={cn('overflow-x-auto', className)}>
      <table className="w-full min-w-[640px] border-collapse text-left">
        <thead>
          <tr className="border-b border-line">
            {columns.map((label, index) => (
              <th
                key={`${label}-${index}`}
                scope="col"
                className="px-3 py-2.5 text-[11px] font-bold tracking-wide text-ink-subtle"
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {documents.map((doc) => (
            <tr
              key={doc.id}
              className="group border-b border-line-soft transition-colors last:border-0 hover:bg-line-soft/60"
            >
              <td className="px-3 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  <FileTypeIcon kind={doc.kind} size="sm" />
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-semibold text-ink">{doc.name}</p>
                    {doc.pages !== undefined && (
                      <p className="text-[11px] text-ink-subtle">{doc.pages}페이지</p>
                    )}
                  </div>
                </div>
              </td>

              <td className="px-3 py-3 text-[12px] font-medium text-ink-muted tabular-nums">
                {formatBytes(doc.size)}
              </td>

              {!compact && (
                <td className="px-3 py-3 text-[12px] font-medium text-ink-muted">
                  {doc.uploadedBy}
                </td>
              )}

              <td className="px-3 py-3">
                {doc.status === 'analyzed' ? (
                  <button
                    type="button"
                    onClick={() => setSummaryDocument(doc)}
                    aria-label={`${doc.name} Grok 요약 보기`}
                    title="Grok 요약 보기"
                    className="rounded-full transition-transform hover:scale-[1.03] focus-visible:ring-2 focus-visible:ring-primary/30 focus-visible:outline-none"
                  >
                    <DocumentStatusBadge status={doc.status} />
                  </button>
                ) : (
                  <DocumentStatusBadge status={doc.status} />
                )}
              </td>

              <td className="px-3 py-3 text-[12px] text-ink-subtle tabular-nums">
                {formatDateTime(doc.uploadedAt)}
              </td>

              <td className="px-3 py-3 text-right">
                <div className="flex items-center justify-end gap-0.5">
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() =>
                      setPreviewTarget({
                        name: doc.name,
                        mimeType: doc.mimeType,
                        revisionId: doc.revisionId,
                        submissionKind: doc.submissionKind,
                      })
                    }
                    aria-label={`${doc.name} 미리보기`}
                    className="text-ink-subtle hover:bg-primary-50 hover:text-primary"
                  >
                    <Eye />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => void downloadOriginal(doc)}
                    aria-label={`${doc.name} 원본 다운로드`}
                    title="원본 다운로드"
                    className="text-ink-subtle hover:bg-primary-50 hover:text-primary"
                  >
                    <Download />
                    <span className="sr-only">원본 다운로드</span>
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`${doc.name} 삭제`}
                    onClick={() => {
                      setActionError(null)
                      setDeleteTarget(doc)
                    }}
                    disabled={!onDelete}
                    className="text-ink-subtle hover:bg-danger-soft hover:text-danger"
                  >
                    <Trash2 />
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {actionError && (
        <p className="mx-3 mt-3 flex items-center gap-2 rounded-lg bg-danger-soft px-3 py-2 text-[12px] font-semibold text-danger">
          <AlertCircle className="size-4 shrink-0" />
          {actionError}
        </p>
      )}

      <DocumentPreviewDialog
        target={previewTarget}
        onOpenChange={(open) => {
          if (!open) setPreviewTarget(null)
        }}
      />
      <DocumentSummaryDialog
        document={summaryDocument}
        onOpenChange={(open) => {
          if (!open) setSummaryDocument(null)
        }}
      />
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open && !deleting) setDeleteTarget(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>문서를 정말 삭제하시겠습니까?</DialogTitle>
            <DialogDescription>
              “{deleteTarget?.name}” 문서와 추출된 내용이 프로젝트에서 삭제됩니다. 이 작업은
              되돌릴 수 없습니다.
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button variant="outline" disabled={deleting} onClick={() => setDeleteTarget(null)}>
              취소
            </Button>
            <Button variant="danger" disabled={deleting} onClick={() => void confirmDelete()}>
              {deleting ? <Loader2 className="animate-spin" /> : <Trash2 />}
              삭제
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
