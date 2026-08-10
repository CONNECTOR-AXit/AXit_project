import { AlertCircle, Download, FileWarning, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { api, ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

export interface PreviewTarget {
  name: string
  mimeType: string
  revisionId: string
  submissionKind: 'text' | 'file'
  /** 이번 세션에 직접 작성해 올린 텍스트 — 있으면 재조회 없이 그대로 보여줍니다. */
  inlineText?: string
}

export interface DocumentPreviewDialogProps {
  target: PreviewTarget | null
  onOpenChange: (open: boolean) => void
}

type PreviewMode = 'image' | 'pdf' | 'text' | 'unsupported'

function previewMode(mimeType: string): PreviewMode {
  if (mimeType.startsWith('image/')) return 'image'
  if (mimeType === 'application/pdf') return 'pdf'
  if (mimeType.startsWith('text/')) return 'text'
  return 'unsupported'
}

type Status = 'idle' | 'loading' | 'error'

interface ExtractedPreview {
  text: string
  truncated: boolean
}

interface SourceViewerResponse {
  text: string
}

function markdownFilename(name: string) {
  const safeName = name.replace(/[\\/:*?"<>|]/g, '-').trim() || '문서'
  return safeName.toLowerCase().endsWith('.md') ? safeName : `${safeName}.md`
}

/**
 * 원문 조회는 인증 세션 쿠키뿐 아니라 `X-AXit-Original-Host` 헤더도 확인하므로
 * (`_authenticated_read`), 일반 `<a href>` 이동으로는 403이 납니다. 항상 이미
 * 헤더를 채워 보내는 axios 클라이언트로 blob을 받아온 뒤 화면에 그리거나
 * 내려받기용 임시 링크로 저장합니다.
 *
 * `/source-revisions/{id}/original`은 백엔드에서 `kind='file'` 제출만
 * 지원합니다(`file_submission_service.download_original`). "문서 직접
 * 작성"으로 만든 텍스트 문서는 같은 세션에서 작성한 내용(inlineText)이
 * 있으면 바로 보여주고, 없으면 권한 확인된 `/viewer` 응답에서 원문을 다시 읽습니다.
 *
 * 브라우저에서 바로 렌더링할 수 없는 형식(hwp, hwpx, docx, pptx, xlsx 등)은 원본 파일을
 * 그릴 수 없더라도, 서버가 이미 추출해 둔 텍스트 블록 앞부분(`/preview`)을
 * "첫 페이지" 감각의 미리보기로 대신 보여줍니다 — 실패하면 조용히 생략할 뿐
 * 다운로드 자체를 막지는 않습니다.
 */
export function DocumentPreviewDialog({ target, onOpenChange }: DocumentPreviewDialogProps) {
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState<string | null>(null)
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [textContent, setTextContent] = useState<string | null>(null)
  const [extractedPreview, setExtractedPreview] = useState<ExtractedPreview | null>(null)

  useEffect(() => {
    if (!target) {
      setBlobUrl(null)
      setTextContent(null)
      setExtractedPreview(null)
      setStatus('idle')
      setError(null)
      return
    }

    if (target.inlineText !== undefined) {
      setBlobUrl(null)
      setTextContent(target.inlineText)
      setExtractedPreview(null)
      setStatus('idle')
      setError(null)
      return
    }

    let cancelled = false
    let objectUrl: string | null = null
    setStatus('loading')
    setError(null)
    setTextContent(null)
    setExtractedPreview(null)
    setBlobUrl(null)

    const mode = previewMode(target.mimeType)

    if (target.submissionKind === 'text') {
      api
        .get<SourceViewerResponse>(`/source-revisions/${target.revisionId}/viewer`)
        .then((response) => {
          if (cancelled) return
          setTextContent(response.data.text)
          setStatus('idle')
        })
        .catch((err: unknown) => {
          if (cancelled) return
          setError(err instanceof ApiError ? err.message : '문서를 불러오지 못했습니다.')
          setStatus('error')
        })

      return () => {
        cancelled = true
      }
    }

    api
      .get<Blob>(`/source-revisions/${target.revisionId}/original`, { responseType: 'blob' })
      .then(async (response) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(response.data)
        setBlobUrl(objectUrl)
        if (mode === 'text') {
          setTextContent(await response.data.text())
        }
        setStatus('idle')
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : '문서를 불러오지 못했습니다.')
        setStatus('error')
      })

    if (mode === 'unsupported') {
      api
        .get<ExtractedPreview>(`/source-revisions/${target.revisionId}/preview`)
        .then((response) => {
          if (!cancelled) setExtractedPreview(response.data)
        })
        .catch(() => {
          // 추출 텍스트 미리보기는 있으면 좋은 보조 정보일 뿐이라, 실패해도
          // 원본 다운로드 흐름을 막지 않고 조용히 생략합니다.
        })
    }

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [target])

  const mode = target ? previewMode(target.mimeType) : 'unsupported'

  const download = () => {
    if (!target) return

    if (target.submissionKind === 'text') {
      if (textContent === null) return
      const textUrl = URL.createObjectURL(
        new Blob([textContent], { type: 'text/markdown;charset=utf-8' }),
      )
      const link = document.createElement('a')
      link.href = textUrl
      link.download = markdownFilename(target.name)
      link.click()
      setTimeout(() => URL.revokeObjectURL(textUrl), 0)
      return
    }

    if (!blobUrl) return
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = target.name
    link.click()
  }

  const canDownload = target?.submissionKind === 'text' ? textContent !== null : Boolean(blobUrl)

  return (
    <Dialog open={target !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader className="flex-row items-start justify-between gap-4 pr-8">
          <div>
            <DialogTitle>{target?.name ?? '문서 미리보기'}</DialogTitle>
            <DialogDescription>
              {target?.submissionKind === 'text'
                ? '직접 작성한 문서를 다시 불러와 보여드립니다.'
                : '업로드된 원본 문서를 그대로 보여드립니다.'}
            </DialogDescription>
          </div>
          {status === 'idle' && canDownload && (
            <Button variant="outline" size="sm" onClick={download} className="shrink-0">
              <Download className="size-3.5" />
              {target?.submissionKind === 'text' ? '.md 다운로드' : '다운로드'}
            </Button>
          )}
        </DialogHeader>

        <div className="max-h-[70vh] min-h-[220px] overflow-auto rounded-lg border border-line-soft bg-line-soft/30">
          {status === 'loading' && (
            <div className="flex h-[300px] items-center justify-center gap-2 text-[13px] text-ink-muted">
              <Loader2 className="size-4 animate-spin" />
              불러오는 중입니다...
            </div>
          )}

          {status === 'error' && (
            <div className="flex h-[300px] flex-col items-center justify-center gap-2 px-6 text-center text-[13px] text-danger">
              <AlertCircle className="size-5" />
              {error}
            </div>
          )}

          {status === 'idle' && mode === 'image' && blobUrl && (
            <img
              src={blobUrl}
              alt={target?.name}
              className="mx-auto max-h-[70vh] object-contain"
            />
          )}

          {status === 'idle' && mode === 'pdf' && blobUrl && (
            <iframe src={blobUrl} title={target?.name} className="h-[70vh] w-full" />
          )}

          {status === 'idle' && mode === 'text' && textContent !== null && (
            <pre className="whitespace-pre-wrap break-words p-4 text-[12.5px] leading-5 text-ink">
              {textContent}
            </pre>
          )}

          {status === 'idle' && mode === 'unsupported' && (
            <div className="space-y-3 p-4">
              <p className="flex items-center gap-1.5 text-[12px] text-ink-muted">
                <FileWarning className="size-3.5 shrink-0" />
                이 형식은 브라우저에서 전체를 바로 미리보기할 수 없어, 추출된 첫 부분만
                보여드려요. 전체 내용은 다운로드해서 확인해주세요.
              </p>
              {extractedPreview && extractedPreview.text.length > 0 && (
                <div className="rounded-lg border border-line-soft bg-white p-3">
                  <pre className="whitespace-pre-wrap break-words text-[12.5px] leading-5 text-ink">
                    {extractedPreview.text}
                  </pre>
                  {extractedPreview.truncated && (
                    <p className="mt-2 text-[11.5px] text-ink-subtle">이후 내용은 생략했어요.</p>
                  )}
                </div>
              )}
              {!extractedPreview && (
                <div className="flex h-[140px] items-center justify-center text-[12.5px] text-ink-subtle">
                  미리보기를 불러오는 중이거나 아직 준비되지 않았어요.
                </div>
              )}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
