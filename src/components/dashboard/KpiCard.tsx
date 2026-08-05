import { motion } from 'framer-motion'
import { ArrowDownRight, ArrowUpRight, type LucideIcon } from 'lucide-react'

import { staggerItem } from '@/components/layout/PageTransition'
import { Card } from '@/components/ui/card'
import { formatNumber } from '@/lib/format'
import { cn } from '@/lib/utils'

export type KpiTone = 'primary' | 'mint' | 'violet' | 'amber'

const toneClass: Record<KpiTone, string> = {
  primary: 'bg-line-soft text-ink-muted',
  mint: 'bg-line-soft text-ink-muted',
  violet: 'bg-line-soft text-ink-muted',
  amber: 'bg-line-soft text-ink-muted',
}

export interface KpiCardProps {
  label: string
  value: number
  /** 직전 기간 대비 증감률. 없으면 배지를 표시하지 않습니다. */
  delta?: number
  unit?: string
  icon: LucideIcon
  tone?: KpiTone
  /** 값 아래 보조 설명. */
  caption?: string
  className?: string
}

/**
 * 대시보드 상단 KPI 카드.
 * 값 하나를 크게 보여주는 자리이므로 차트 대신 숫자를 주인공으로 둡니다.
 */
export function KpiCard({
  label,
  value,
  delta,
  unit = '개',
  icon: Icon,
  tone = 'primary',
  caption,
  className,
}: KpiCardProps) {
  const positive = (delta ?? 0) >= 0
  const DeltaIcon = positive ? ArrowUpRight : ArrowDownRight

  return (
    <motion.div variants={staggerItem} className={className}>
      <Card className="h-full p-5 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lift">
        <div className="flex items-start justify-between gap-3">
          <span
            className={cn(
              'flex size-10 shrink-0 items-center justify-center rounded-xl',
              toneClass[tone],
            )}
          >
            <Icon className="size-[18px]" strokeWidth={2} />
          </span>

          {/* 증감은 색만이 아니라 화살표 방향으로도 구분됩니다. */}
          {delta !== undefined && (
            <span
              className={cn(
                'flex items-center gap-0.5 rounded-md px-1.5 py-1 text-[11.5px] font-bold tabular-nums',
                positive ? 'bg-success-soft text-success' : 'bg-danger-soft text-danger',
              )}
            >
              <DeltaIcon className="size-3" />
              {Math.abs(delta).toFixed(1)}%
            </span>
          )}
        </div>

        <p className="mt-4 text-[12.5px] font-semibold text-ink-muted">{label}</p>
        <p className="mt-1 flex items-baseline gap-1">
          <span className="text-[28px] leading-9 font-extrabold tracking-tight text-ink tabular-nums">
            {formatNumber(value)}
          </span>
          <span className="text-[13px] font-bold text-ink-subtle">{unit}</span>
        </p>
        {caption && <p className="mt-1 text-[11.5px] text-ink-subtle">{caption}</p>}
      </Card>
    </motion.div>
  )
}
