import { useEffect, useRef, useState } from 'react'

export type SaveState = 'idle' | 'pending' | 'saving' | 'saved'

export interface UseAutosaveOptions {
  /** 저장이 실행되기 전 디바운스(ms). */
  delay?: number
  /** 저장 왕복 시간을 흉내내는 지연(ms). */
  duration?: number
  enabled?: boolean
}

export interface UseAutosaveResult {
  state: SaveState
  savedAt: Date | null
  /** 문서를 dirty 로 표시 — 저장을 예약합니다. */
  touch: () => void
  /** 디바운스를 건너뛰고 즉시 저장합니다. */
  saveNow: () => void
}

/**
 * 상태가 눈에 보이는(`pending → saving → saved`) 디바운스 자동 저장.
 * Google Docs 처럼 "자동 저장됨 14:32" 를 노출할 수 있게 합니다.
 */
export function useAutosave({
  delay = 1200,
  duration = 600,
  enabled = true,
}: UseAutosaveOptions = {}): UseAutosaveResult {
  const [state, setState] = useState<SaveState>('idle')
  const [savedAt, setSavedAt] = useState<Date | null>(new Date())
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const saveRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const run = () => {
    setState('saving')
    saveRef.current = setTimeout(() => {
      setSavedAt(new Date())
      setState('saved')
    }, duration)
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
      if (saveRef.current) clearTimeout(saveRef.current)
    },
    [],
  )

  return { state, savedAt, touch, saveNow }
}
