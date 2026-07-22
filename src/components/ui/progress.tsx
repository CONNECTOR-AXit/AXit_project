import * as ProgressPrimitive from '@radix-ui/react-progress'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

export interface ProgressProps extends ComponentProps<typeof ProgressPrimitive.Root> {
  /** 0–100 */
  value?: number
  /** 채움 색. `gradient` 는 Blue → Mint 브랜드 램프입니다. */
  tone?: 'primary' | 'gradient' | 'success' | 'warning' | 'danger'
}

const toneClass: Record<NonNullable<ProgressProps['tone']>, string> = {
  primary: 'bg-primary',
  gradient: 'brand-gradient',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
}

export function Progress({ className, value = 0, tone = 'primary', ...props }: ProgressProps) {
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      className={cn('relative h-1.5 w-full overflow-hidden rounded-full bg-line', className)}
      value={value}
      {...props}
    >
      <ProgressPrimitive.Indicator
        data-slot="progress-indicator"
        className={cn(
          'h-full w-full rounded-full transition-transform duration-700 ease-out',
          toneClass[tone],
        )}
        style={{ transform: `translateX(-${100 - value}%)` }}
      />
    </ProgressPrimitive.Root>
  )
}
