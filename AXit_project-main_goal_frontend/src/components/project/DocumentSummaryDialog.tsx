import { AlertCircle, Loader2, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'

import { ApiError, get } from '@/api/client'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { DocumentFile } from '@/types'

interface SummarySupport {
  source_anchor_id: string
  exact_quote: string
}

interface SummaryItem {
  text: string
  source_anchor_ids: string[]
  supports: SummarySupport[]
}

interface SummaryResult {
  sections: Array<{ heading: string; items: SummaryItem[] }>
}

interface SourceAnchorTarget {
  source_anchor_id: string
  source_revision_id: string
}

interface DocumentSummarySection {
  heading: string
  items: Array<{ text: string; quotes: string[] }>
}

async function loadDocumentSummary(document: DocumentFile): Promise<DocumentSummarySection[]> {
  const summary = await get<SummaryResult>(`/sessions/${document.projectId}/summary`)
  const anchorIds = [
    ...new Set(
      summary.sections.flatMap((section) =>
        section.items.flatMap((item) => item.source_anchor_ids),
      ),
    ),
  ]
  const resolved = await Promise.all(
    anchorIds.map((anchorId) =>
      get<SourceAnchorTarget>(`/source-anchors/${anchorId}/resolve`),
    ),
  )
  const documentAnchorIds = new Set(
    resolved
      .filter((target) => target.source_revision_id === document.revisionId)
      .map((target) => target.source_anchor_id),
  )

  return summary.sections
    .map((section) => ({
      heading: section.heading,
      items: section.items
        .filter((item) => item.source_anchor_ids.some((id) => documentAnchorIds.has(id)))
        .map((item) => ({
          text: item.text,
          quotes: item.supports
            .filter((support) => documentAnchorIds.has(support.source_anchor_id))
            .map((support) => support.exact_quote),
        })),
    }))
    .filter((section) => section.items.length > 0)
}

export function DocumentSummaryDialog({
  document,
  onOpenChange,
}: {
  document: DocumentFile | null
  onOpenChange: (open: boolean) => void
}) {
  const [sections, setSections] = useState<DocumentSummarySection[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!document) {
      setSections([])
      setError(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    void loadDocumentSummary(document)
      .then((result) => {
        if (!cancelled) setSections(result)
      })
      .catch((reason: unknown) => {
        if (cancelled) return
        setError(
          reason instanceof ApiError && reason.status === 404
            ? 'Grok 요약이 아직 준비되지 않았습니다. 잠시 후 다시 확인해 주세요.'
            : reason instanceof ApiError
              ? reason.message
              : 'Grok 요약을 불러오지 못했습니다.',
        )
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [document])

  return (
    <Dialog open={document !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="size-5 text-primary" />
            Grok 문서 요약
          </DialogTitle>
          <DialogDescription>{document?.name}에서 확인된 핵심 내용을 근거와 함께 보여드립니다.</DialogDescription>
        </DialogHeader>

        <div className="max-h-[65vh] min-h-44 overflow-y-auto rounded-xl border border-line-soft bg-line-soft/30 p-4">
          {loading && (
            <div className="flex min-h-36 items-center justify-center gap-2 text-[13px] text-ink-muted">
              <Loader2 className="size-4 animate-spin" /> Grok 요약을 불러오는 중입니다...
            </div>
          )}
          {!loading && error && (
            <div className="flex min-h-36 items-center justify-center gap-2 px-4 text-center text-[13px] text-danger">
              <AlertCircle className="size-5 shrink-0" /> {error}
            </div>
          )}
          {!loading && !error && sections.length === 0 && (
            <p className="py-12 text-center text-[13px] text-ink-muted">
              이 문서에 연결된 Grok 요약 항목이 없습니다.
            </p>
          )}
          {!loading && !error && sections.map((section) => (
            <section key={section.heading} className="mb-5 last:mb-0">
              <h3 className="mb-2 text-[14px] font-bold text-ink">{section.heading}</h3>
              <div className="space-y-3">
                {section.items.map((item, index) => (
                  <article key={`${section.heading}-${index}`} className="rounded-lg bg-white p-3 shadow-soft">
                    <p className="text-[13px] leading-6 font-medium text-ink">{item.text}</p>
                    {item.quotes.map((quote, quoteIndex) => (
                      <blockquote key={quoteIndex} className="mt-2 border-l-2 border-primary/30 pl-3 text-[11.5px] leading-5 text-ink-muted">
                        {quote}
                      </blockquote>
                    ))}
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
