import { ExternalLink, FileText, Loader2, Quote } from 'lucide-react'
import { useEffect, useState } from 'react'

import { api, ApiError } from '@/api/client'
import type { PreviewTarget } from '@/components/upload/DocumentPreviewDialog'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { DocumentFile } from '@/types'

interface SourceAnchorTarget {
  source_anchor_id: string
  source_revision_id: string
  exact_quote: string
}

export interface RagEvidenceDialogProps {
  anchorId: string | null
  documents: DocumentFile[]
  onClose: () => void
  onOpenOriginal: (target: PreviewTarget) => void
}

export function RagEvidenceDialog({
  anchorId,
  documents,
  onClose,
  onOpenOriginal,
}: RagEvidenceDialogProps) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [revisionId, setRevisionId] = useState<string | null>(null)
  const [quote, setQuote] = useState<string | null>(null)

  useEffect(() => {
    if (!anchorId) {
      setLoading(false)
      setError(null)
      setRevisionId(null)
      setQuote(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    setRevisionId(null)
    setQuote(null)

    api
      .get<SourceAnchorTarget>(`/source-anchors/${anchorId}/resolve`)
      .then(({ data: target }) => {
        if (cancelled) return
        setRevisionId(target.source_revision_id)
        setQuote(target.exact_quote)
      })
      .catch((reason: unknown) => {
        if (cancelled) return
        setError(reason instanceof ApiError ? reason.message : 'RAG 근거를 불러오지 못했습니다.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [anchorId])

  const document = documents.find((item) => item.revisionId === revisionId)
  const openOriginal = () => {
    if (!document) return
    onClose()
    onOpenOriginal({
      name: document.name,
      mimeType: document.mimeType,
      revisionId: document.revisionId,
      submissionKind: document.submissionKind,
    })
  }

  return (
    <Dialog open={anchorId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Quote className="size-4 text-primary" />
            RAG 근거
          </DialogTitle>
          <DialogDescription>
            {document?.name ?? '연결된 원문에서 근거 위치를 확인합니다.'}
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex min-h-40 items-center justify-center gap-2 text-[13px] text-ink-muted">
            <Loader2 className="size-4 animate-spin" />
            근거를 불러오는 중입니다...
          </div>
        ) : error ? (
          <p className="rounded-lg bg-danger-soft px-4 py-3 text-[13px] text-danger">{error}</p>
        ) : (
          <div className="space-y-4">
            <div className="rounded-xl border border-primary/15 bg-primary-50/60 p-4">
              <p className="mb-2 flex items-center gap-1.5 text-[11px] font-bold text-primary">
                <FileText className="size-3.5" />
                원문 근거
              </p>
              <p className="whitespace-pre-wrap text-[13.5px] leading-6 text-ink">
                {quote ?? '연결된 원문 구간을 찾지 못했습니다.'}
              </p>
            </div>
            <div className="flex justify-end">
              <Button variant="outline" disabled={!document} onClick={openOriginal}>
                <ExternalLink className="size-3.5" />
                자세히 보기
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
