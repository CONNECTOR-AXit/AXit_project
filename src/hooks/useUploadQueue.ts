import { useCallback, useEffect, useRef, useState } from 'react'

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
  add: (files: FileList | File[]) => void
  remove: (id: string) => void
  clear: () => void
  retry: (id: string) => void
  totalCount: number
  isUploading: boolean
  /** 마지막으로 거부된 파일에 대한 안내 메시지. */
  lastError: string | null
}

const TICK_MS = 160
const ACCEPT_ALL: FileKind[] = ['pdf', 'docx', 'txt', 'hwp', 'pptx', 'xlsx']

/**
 * 클라이언트 업로드 큐. 진행률을 흉내내며 채웁니다.
 * 실제 서버 연동 시 add 를 axios onUploadProgress 로 바꾸면 UI 는 그대로입니다.
 */
export function useUploadQueue({
  initial = [],
  maxFiles = uploadLimits.maxFiles,
  maxSize = uploadLimits.maxSize,
  accept = ACCEPT_ALL,
}: UseUploadQueueOptions = {}): UseUploadQueueResult {
  const [items, setItems] = useState<UploadItem[]>(initial)
  const [lastError, setLastError] = useState<string | null>(null)
  // 파일별 진행 타이머를 id 로 관리합니다.
  const timers = useRef(new Map<string, ReturnType<typeof setInterval>>())

  const startUpload = useCallback((id: string) => {
    const existing = timers.current.get(id)
    if (existing) clearInterval(existing)

    const timer = setInterval(() => {
      setItems((prev) =>
        prev.map((item) => {
          if (item.id !== id || item.status !== 'uploading') return item
          // 큰 파일일수록 천천히 올라 실제처럼 보입니다.
          const step = Math.max(3, 18 - item.size / (1024 * 1024))
          const next = Math.min(100, item.progress + step)
          return next >= 100
            ? { ...item, progress: 100, status: 'uploaded' as DocumentStatus }
            : { ...item, progress: next }
        }),
      )
    }, TICK_MS)

    timers.current.set(id, timer)
  }, [])

  // 파일이 완료되면 해당 타이머를 정리합니다.
  useEffect(() => {
    for (const item of items) {
      if (item.status !== 'uploading') {
        const timer = timers.current.get(item.id)
        if (timer) {
          clearInterval(timer)
          timers.current.delete(item.id)
        }
      }
    }
  }, [items])

  // 언마운트 시 남은 타이머 모두 정리
  useEffect(() => {
    const map = timers.current
    return () => {
      map.forEach((timer) => clearInterval(timer))
      map.clear()
    }
  }, [])

  const add = useCallback(
    (files: FileList | File[]) => {
      const incoming = Array.from(files)
      setLastError(null)

      setItems((prev) => {
        const room = maxFiles - prev.length
        if (room <= 0) {
          setLastError(`파일은 최대 ${maxFiles}개까지 업로드할 수 있습니다.`)
          return prev
        }

        const accepted: UploadItem[] = []
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
            id: `up-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            name: file.name,
            kind,
            size: file.size,
            progress: 0,
            status: 'uploading',
            addedAt: new Date().toISOString(),
          })
        }

        if (incoming.length > room) {
          setLastError(`파일은 최대 ${maxFiles}개까지 업로드할 수 있습니다.`)
        }

        accepted.forEach((item) => startUpload(item.id))
        // 새 파일을 맨 위에 쌓아 방금 올린 게 바로 보입니다.
        return [...accepted, ...prev]
      })
    },
    [accept, maxFiles, maxSize, startUpload],
  )

  const remove = useCallback((id: string) => {
    const timer = timers.current.get(id)
    if (timer) {
      clearInterval(timer)
      timers.current.delete(id)
    }
    setItems((prev) => prev.filter((item) => item.id !== id))
  }, [])

  const clear = useCallback(() => {
    timers.current.forEach((timer) => clearInterval(timer))
    timers.current.clear()
    setItems([])
  }, [])

  const retry = useCallback(
    (id: string) => {
      setItems((prev) =>
        prev.map((item) =>
          item.id === id ? { ...item, progress: 0, status: 'uploading', error: undefined } : item,
        ),
      )
      startUpload(id)
    },
    [startUpload],
  )

  return {
    items,
    add,
    remove,
    clear,
    retry,
    totalCount: items.length,
    isUploading: items.some((item) => item.status === 'uploading'),
    lastError,
  }
}
