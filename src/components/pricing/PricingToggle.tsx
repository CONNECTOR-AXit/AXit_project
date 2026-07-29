import { motion } from 'framer-motion'

import { cn } from '@/lib/utils'
import type { BillingCycle } from '@/data/pricing'

const options: { value: BillingCycle; label: string }[] = [
  { value: 'annual', label: '연간' },
  { value: 'monthly', label: '월간' },
]

export interface PricingToggleProps {
  value: BillingCycle
  onChange: (value: BillingCycle) => void
  className?: string
}

/** 연간 / 월간 결제 주기 세그먼트 컨트롤. */
export function PricingToggle({ value, onChange, className }: PricingToggleProps) {
  return (
    <div
      role="tablist"
      aria-label="결제 주기"
      className={cn(
        'inline-flex items-center gap-1 rounded-lg border border-line bg-white p-1',
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(option.value)}
            className={cn(
              'relative rounded-md px-4 py-1.5 text-[13px] font-bold transition-colors',
              active ? 'text-[#2777E7]' : 'text-ink-muted hover:text-ink',
            )}
          >
            {active && (
              <motion.span
                layoutId="pricing-toggle-active"
                className="absolute inset-0 rounded-md bg-[#2777E7]/12"
                transition={{ type: 'spring', stiffness: 400, damping: 32 }}
              />
            )}
            <span className="relative z-10">{option.label}</span>
          </button>
        )
      })}
    </div>
  )
}
