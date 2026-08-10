import { useCallback, useState } from 'react'

import { kindFromName } from '@/components/common/FileTypeIcon'
import { uploadLimits } from '@/data/documents'
import type { DocumentStatus, FileKind } from '@/types'

export interface UploadItem {
  id: string
  name: string
  kind: FileKind
  size: number
  progress: number
  status: DocumentStatus
  addedAt: string
  error?: string
  /** 서버에 실제로 저장된 뒤에만 채워집니다 — 미리보기/원문 조회에 씁니다. */
  revisionId?: string
  mimeType?: string
  submissionKind?: 'text' | 'file'
  /** 이번 세션에 직접 작성해 올린 텍스트 — 있으면 재조회 없이 그대로 미리보기에 씁니다. */
  inlineText?: string
}

export interface UseUploadQueueOptions {
  /** 이미 프로젝트에 올라와 있는 파일. */
  initial?: UploadItem[]
  maxFiles?: number
  /** 파일당 최대 바이트. */
  maxSize?: number
  accept?: FileKind[]
}

export interface UseUploadQueueResult {
  items: UploadItem[]
  /** 형식/용량을 통과한 파일만 큐에 추가하고, 실제 업로드에 쓸 (항목, 원본 파일) 쌍을 돌려줍니다. */
  add: (files: FileList | File[]) => { item: UploadItem; file: File }[]
  remove: (id: string) => void
  updateProgress: (id: string, percent: number) => void
  markUploaded: (
    id: string,
    meta?: {
      revisionId?: string
      mimeType?: string
      submissionKind?: 'text' | 'file'
      inlineText?: string
    },
  ) => void
  markFailed: (id: string, error?: string) => void
  /** 서버에서 다시 읽어온 문서 목록으로 기존 항목의 상태(진행률/성공/실패 등)를 최신화합니다. */
  sync: (serverItems: UploadItem[]) => void
  totalCount: number
  isUploading: boolean
  /** 마지막으로 거부된 파일에 대한 안내 메시지. */
  lastError: string | null
}

const ACCEPT_ALL: FileKind[] = ['pdf', 'docx', 'txt', 'hwp', 'pptx', 'xlsx', 'image']

/** 클라이언트 업로드 큐. 실제 진행률/성공/실패는 호출자가 서버 응답에 맞춰 반영합니다. */
export function useUploadQueue({
  initial = [],
  maxFiles = uploadLimits.maxFiles,
  maxSize = uploadLimits.maxSize,
  accept = ACCEPT_ALL,
}: UseUploadQueueOptions = {}): UseUploadQueueResult {
  const [items, setItems] = useState<UploadItem[]>(initial)
  const [lastError, setLastError] = useState<string | null>(null)

  const add = useCallback(
    (files: FileList | File[]) => {
      const incoming = Array.from(files)
      setLastError(null)

      const room = maxFiles - items.length
      if (room <= 0) {
        setLastError(`파일은 최대 ${maxFiles}개까지 업로드할 수 있습니다.`)
        return []
      }

      const accepted: { item: UploadItem; file: File }[] = []
      for (const file of incoming.slice(0, room)) {
        const kind = kindFromName(file.name)
        if (!accept.includes(kind)) {
          setLastError(`'${file.name}'은 지원하지 않는 형식입니다.`)
          continue
        }
        if (file.size > maxSize) {
          setLastError(`'${file.name}'의 용량이 제한을 초과했습니다.`)
          continue
        }
        accepted.push({
          item: {
            id: `up-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            name: file.name,
            kind,
            size: file.size,
            progress: 0,
            status: 'uploading',
            addedAt: new Date().toISOString(),
          },
          file,
        })
      }

      if (incoming.length > room) {
        setLastError(`파일은 최대 ${maxFiles}개까지 업로드할 수 있습니다.`)
      }

      if (accepted.length > 0) {
        // 새 파일을 맨 위에 쌓아 방금 올린 게 바로 보입니다.
        setItems((prev) => [...accepted.map((entry) => entry.item), ...prev])
      }

      return accepted
    },
    [accept, items.length, maxFiles, maxSize],
  )

  const remove = useCallback((id: string) => {
    setItems((prev) => prev.filter((item) => item.id !== id))
  }, [])

  const updateProgress = useCallback((id: string, percent: number) => {
    setItems((prev) =>
      prev.map((item) =>
        item.id === id && item.status === 'uploading' ? { ...item, progress: percent } : item,
      ),
    )
  }, [])

  const markUploaded = useCallback(
    (
      id: string,
      meta?: {
        revisionId?: string
        mimeType?: string
        submissionKind?: 'text' | 'file'
        inlineText?: string
      },
    ) => {
      // HTTP 전송이 끝났다고 바로 100%/'analyzed'로 표시하면 안 됩니다 — 파일
      // 제출은 서버에서 이 시점에 processing_state='queued'로 시작해 추출
      // (OCR/파싱) 워커가 끝내야 'ready'가 되고, 그 전에는 "AI 분석 시작"이
      // 서버의 close()에서 거부(409)됩니다. 텍스트 직접 작성만 서버가 즉시
      // 'ready'로 처리하므로 바로 완료로 표시합니다.
      const isReadyImmediately = meta?.submissionKind === 'text'
      setItems((prev) =>
        prev.map((item) =>
          item.id === id
            ? {
                ...item,
                progress: isReadyImmediately ? 100 : 50,
                status: isReadyImmediately ? 'analyzed' : 'queued',
                error: undefined,
                ...meta,
              }
            : item,
        ),
      )
    },
    [],
  )

  const markFailed = useCallback((id: string, error?: string) => {
    setItems((prev) =>
      prev.map((item) =>
        item.id === id ? { ...item, progress: 0, status: 'failed', error } : item,
      ),
    )
  }, [])

  // 방금 이 세션에서 올린 항목은 서버가 실제로 준 id(제출 id)가 아니라
  // 클라이언트가 즉석에서 만든 임시 id를 그대로 쓰고 있어서, id만으로
  // 맞추면 서버 쪽 폴링 결과와 다시는 매칭되지 않습니다 — 그래서 revisionId도
  // 함께 봐서 같은 문서를 찾아내고, 그 뒤로는 서버가 준 id로 갈아 끼웁니다.
  const sync = useCallback((serverItems: UploadItem[]) => {
    setItems((prev) => {
      const byId = new Map(serverItems.map((item) => [item.id, item]))
      const byRevision = new Map(
        serverItems
          .filter((item): item is UploadItem & { revisionId: string } => Boolean(item.revisionId))
          .map((item) => [item.revisionId, item]),
      )
      return prev.map((item) => {
        const fresh = byId.get(item.id) ?? (item.revisionId ? byRevision.get(item.revisionId) : undefined)
        return fresh ?? item
      })
    })
  }, [])

  return {
    items,
    add,
    remove,
    updateProgress,
    markUploaded,
    markFailed,
    sync,
    totalCount: items.length,
    isUploading: items.some((item) => item.status === 'uploading'),
    lastError,
  }
}
