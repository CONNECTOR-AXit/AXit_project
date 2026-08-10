import { useEffect, useRef, useState } from 'react'

export type SaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error'

export interface UseAutosaveOptions {
  /** 저장이 실행되기 전 디바운스(ms). */
  delay?: number
  enabled?: boolean
  /** 실제로 서버에 저장하는 함수. reject되면 'error' 상태로 표시됩니다. */
  save: () => Promise<void>
}

export interface UseAutosaveResult {
  state: SaveState
  savedAt: Date | null
  errorMessage: string | null
  /** 문서를 dirty 로 표시 — 저장을 예약합니다. */
  touch: () => void
  /** 디바운스를 건너뛰고 즉시 저장합니다(실패 후 재시도에도 사용). */
  saveNow: () => void
}

/**
 * 상태가 눈에 보이는(`pending → saving → saved`) 디바운스 자동 저장.
 * `saved`는 실제 서버 저장 요청이 성공했을 때만 표시되고, 실패하면 `error`로
 * 남아 재시도할 수 있습니다 — 저장되지 않았는데 "자동 저장됨"이라고 말하지 않습니다.
 */
export function useAutosave({
  delay = 1200,
  enabled = true,
  save,
}: UseAutosaveOptions): UseAutosaveResult {
  const [state, setState] = useState<SaveState>('idle')
  const [savedAt, setSavedAt] = useState<Date | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const saveRef = useRef(save)
  saveRef.current = save
  const runTokenRef = useRef(0)

  const run = () => {
    const token = ++runTokenRef.current
    setState('saving')
    setErrorMessage(null)
    saveRef.current()
      .then(() => {
        if (runTokenRef.current !== token) return
        setSavedAt(new Date())
        setState('saved')
      })
      .catch((error: unknown) => {
        if (runTokenRef.current !== token) return
        setState('error')
        setErrorMessage(error instanceof Error ? error.message : '저장하지 못했습니다.')
      })
  }

  const touch = () => {
    if (!enabled) return
    setState('pending')
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(run, delay)
  }

  const saveNow = () => {
    if (!enabled) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    run()
  }

  useEffect(
    () => () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      runTokenRef.current += 1
    },
    [],
  )

  return { state, savedAt, errorMessage, touch, saveNow }
}
