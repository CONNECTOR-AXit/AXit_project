import { motion } from 'framer-motion'
import {
  Check,
  FileStack,
  GitCompare,
  ScanText,
  Sparkles,
  Upload,
  type LucideIcon,
} from 'lucide-react'

import { analysisSteps, type AnalysisStep, type StepState } from '@/hooks/useAnalysisSimulation'
import { cn } from '@/lib/utils'

const stepIcon: Record<AnalysisStep['id'], LucideIcon> = {
  upload: Upload,
  extract: ScanText,
  common: FileStack,
  difference: GitCompare,
  merge: Sparkles,
}

const stateLabel: Record<StepState, string> = {
  done: '완료',
  active: '진행 중',
  waiting: '대기 중',
}

export interface AnalysisStepperProps {
  stepStates: Record<AnalysisStep['id'], StepState>
  className?: string
  /** 세로로 쌓기 — 좁은 화면에서 사용합니다. */
  orientation?: 'horizontal' | 'vertical'
}

/** 5단계 분석 파이프라인을 노드·커넥터로 시각화합니다. */
export function AnalysisStepper({
  stepStates,
  className,
  orientation = 'horizontal',
}: AnalysisStepperProps) {
  const vertical = orientation === 'vertical'

  return (
    <ol
      className={cn(
        'relative',
        vertical ? 'flex flex-col gap-0' : 'flex items-start justify-between gap-2',
        className,
      )}
    >
      {analysisSteps.map((step, index) => {
        const state = stepStates[step.id]
        const Icon = stepIcon[step.id]
        const isLast = index === analysisSteps.length - 1
        const connectorFilled = state === 'done'

        return (
          <li
            key={step.id}
            className={cn(
              'relative',
              vertical ? 'flex gap-3.5 pb-6 last:pb-0' : 'flex flex-1 flex-col items-center gap-2.5',
            )}
          >
            {/* 커넥터 */}
            {!isLast && (
              <span
                className={cn(
                  'absolute bg-line',
                  vertical
                    ? 'top-10 bottom-2 left-[19px] w-0.5'
                    : 'top-5 right-0 left-1/2 h-0.5 translate-x-5',
                )}
                aria-hidden="true"
              >
                <motion.span
                  className="block h-full w-full origin-top-left brand-gradient"
                  initial={false}
                  animate={
                    vertical
                      ? { scaleY: connectorFilled ? 1 : 0 }
                      : { scaleX: connectorFilled ? 1 : 0 }
                  }
                  style={{ originX: 0, originY: 0 }}
                  transition={{ duration: 0.5, ease: 'easeOut' }}
                />
              </span>
            )}

            {/* 노드 */}
            <span className="relative z-10 shrink-0">
              {state === 'active' && (
                <span className="animate-pulse-ring absolute -inset-1 rounded-full bg-primary/25" />
              )}
              <span
                className={cn(
                  'relative flex size-10 items-center justify-center rounded-full border-2 transition-colors duration-300',
                  state === 'done' && 'border-transparent bg-success text-white',
                  state === 'active' && 'brand-gradient border-transparent text-white shadow-brand',
                  state === 'waiting' && 'border-line bg-white text-ink-subtle',
                )}
              >
                {state === 'done' ? (
                  <Check className="size-4.5" strokeWidth={3} />
                ) : (
                  <Icon className="size-4.5" strokeWidth={2} />
                )}
              </span>
            </span>

            {/* 라벨 */}
            <div className={cn(vertical ? 'min-w-0 pt-1' : 'text-center')}>
              <p
                className={cn(
                  'text-[12.5px] leading-4 font-bold transition-colors',
                  state === 'waiting' ? 'text-ink-subtle' : 'text-ink',
                )}
              >
                {step.label}
              </p>
              <p
                className={cn(
                  'mt-0.5 text-[11.5px] leading-4',
                  state === 'active' ? 'font-semibold text-primary' : 'text-ink-subtle',
                )}
              >
                {vertical && state === 'active' ? step.caption : stateLabel[state]}
              </p>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
