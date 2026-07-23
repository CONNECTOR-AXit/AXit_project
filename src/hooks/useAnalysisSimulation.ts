import { useCallback, useEffect, useRef, useState } from 'react'

import type { AnalysisStage } from '@/types'

export interface AnalysisStep {
  id: Exclude<AnalysisStage, 'done'>
  label: string
  caption: string
  /** 이 단계가 끝나는 전체 진행률(%). */
  endsAt: number
}

/** 분석 화면에 노출되는 5단계 파이프라인. */
export const analysisSteps: AnalysisStep[] = [
  { id: 'upload', label: '문서 업로드', caption: '파일을 안전하게 저장했어요', endsAt: 12 },
  { id: 'extract', label: '내용 추출', caption: '문서에서 텍스트와 표를 읽는 중', endsAt: 38 },
  { id: 'common', label: '공통점 분석', caption: '문서 간 겹치는 내용을 찾는 중', endsAt: 62 },
  { id: 'difference', label: '차이점 분석', caption: '상충하는 서술을 비교하는 중', endsAt: 84 },
  { id: 'merge', label: '통합 문서 생성', caption: '하나의 문서로 재구성하는 중', endsAt: 100 },
]

export type StepState = 'done' | 'active' | 'waiting'

export interface UseAnalysisSimulationOptions {
  /** 전체 실행 시간(ms). */
  durationMs?: number
  autoStart?: boolean
  onComplete?: () => void
}

export interface UseAnalysisSimulationResult {
  progress: number
  stage: AnalysisStage
  currentStep: AnalysisStep
  stepStates: Record<AnalysisStep['id'], StepState>
  elapsedSeconds: number
  remainingSeconds: number
  isComplete: boolean
  isRunning: boolean
  restart: () => void
}

const TICK_MS = 120

/**
 * AI 분석 진행 화면을 구동합니다. 실제 파이프라인처럼 끝으로 갈수록
 * 감속하도록 easeOutCubic 곡선으로 진행률을 올립니다.
 */
export function useAnalysisSimulation({
  durationMs = 24_000,
  autoStart = true,
  onComplete,
}: UseAnalysisSimulationOptions = {}): UseAnalysisSimulationResult {
  const [progress, setProgress] = useState(0)
  const [isRunning, setIsRunning] = useState(autoStart)
  const startedAt = useRef<number>(Date.now())
  const completedRef = useRef(false)
  const onCompleteRef = useRef(onComplete)
  onCompleteRef.current = onComplete

  useEffect(() => {
    if (!isRunning) return

    const timer = setInterval(() => {
      const elapsed = Date.now() - startedAt.current
      const linear = Math.min(1, elapsed / durationMs)
      // easeOutCubic — 빠르게 시작해 부드럽게 마무리.
      const eased = 1 - (1 - linear) ** 3
      const next = Math.round(eased * 100)
      setProgress(next)

      if (linear >= 1) {
        setIsRunning(false)
        if (!completedRef.current) {
          completedRef.current = true
          onCompleteRef.current?.()
        }
      }
    }, TICK_MS)

    return () => clearInterval(timer)
  }, [durationMs, isRunning])

  const restart = useCallback(() => {
    startedAt.current = Date.now()
    completedRef.current = false
    setProgress(0)
    setIsRunning(true)
  }, [])

  const currentStep =
    analysisSteps.find((step) => progress < step.endsAt) ?? analysisSteps[analysisSteps.length - 1]!

  const stepStates = analysisSteps.reduce(
    (acc, step) => {
      acc[step.id] =
        progress >= step.endsAt ? 'done' : step.id === currentStep.id ? 'active' : 'waiting'
      return acc
    },
    {} as Record<AnalysisStep['id'], StepState>,
  )

  const isComplete = progress >= 100
  const elapsedSeconds = Math.round((durationMs / 1000) * (progress / 100))
  const remainingSeconds = Math.max(0, Math.round(durationMs / 1000) - elapsedSeconds)

  return {
    progress,
    stage: isComplete ? 'done' : currentStep.id,
    currentStep,
    stepStates,
    elapsedSeconds,
    remainingSeconds,
    isComplete,
    isRunning,
    restart,
  }
}
