import { motion } from 'framer-motion'
import type { ReactNode } from 'react'

import { clamp, cn } from '@/lib/utils'

export interface CircularProgressProps {
  /** 0–100 */
  value: number
  size?: number
  strokeWidth?: number
  tone?: 'primary' | 'success' | 'warning'
  children?: ReactNode
  className?: string
  /** 느리게 번지는 후광. 분석이 진행 중일 때 사용합니다. */
  glow?: boolean
}

const toneStroke = {
  primary: 'var(--color-primary)',
  success: 'var(--color-success)',
  warning: 'var(--color-warning)',
} as const

/** 큰 원형 진행률. Phase 5 의 AI 분석 화면에서도 재사용합니다. */
export function CircularProgress({
  value,
  size = 180,
  strokeWidth = 12,
  tone = 'primary',
  children,
  className,
  glow = false,
}: CircularProgressProps) {
  const pct = clamp(value)
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius

  return (
    <div
      className={cn('relative inline-flex items-center justify-center', className)}
      style={{ width: size, height: size }}
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      {glow && (
        <span
          className="animate-pulse-ring absolute inset-2 rounded-full bg-primary/12"
          aria-hidden="true"
        />
      )}
      {/* -90도 회전으로 12시 방향에서 시작합니다. */}
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--color-line)"
          strokeWidth={strokeWidth}
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={toneStroke[tone]}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: circumference * (1 - pct / 100) }}
          transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-0.5">
        {children ?? (
          <span className="text-3xl font-extrabold tracking-tight text-ink tabular-nums">
            {Math.round(pct)}%
          </span>
        )}
      </div>
    </div>
  )
}

export interface MiniRingProps {
  value: number
  size?: number
  strokeWidth?: number
  /** 100% 도달 여부. 텍스트 강조에만 씁니다 — 링 색은 항상 메인 컬러입니다. */
  complete?: boolean
}

/** 프로젝트 카드에 들어가는 작은 진행률 링. */
export function MiniRing({ value, size = 40, strokeWidth = 4, complete }: MiniRingProps) {
  const pct = clamp(value)
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius

  return (
    <span className="relative inline-flex shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--color-line)"
          strokeWidth={strokeWidth}
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--color-primary)"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: circumference * (1 - pct / 100) }}
          transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
        />
      </svg>
      <span
        className={cn(
          'absolute inset-0 flex items-center justify-center text-[10px] font-bold tabular-nums',
          complete ? 'text-success' : 'text-ink-muted',
        )}
      >
        {Math.round(pct)}%
      </span>
    </span>
  )
}
