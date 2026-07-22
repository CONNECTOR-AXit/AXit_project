import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1 rounded-md border px-2 py-0.5 text-[12px] font-semibold whitespace-nowrap [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-3",
  {
    variants: {
      variant: {
        neutral: 'border-line bg-line-soft text-ink-muted',
        primary: 'border-primary-100 bg-primary-50 text-primary-600',
        secondary: 'border-secondary-100 bg-secondary-50 text-secondary-600',
        success: 'border-success/20 bg-success-soft text-success',
        warning: 'border-warning/25 bg-warning-soft text-warning',
        danger: 'border-danger/20 bg-danger-soft text-danger',
        outline: 'border-line bg-white text-ink-muted',
      },
    },
    defaultVariants: { variant: 'neutral' },
  },
)

export interface BadgeProps extends ComponentProps<'span'>, VariantProps<typeof badgeVariants> {
  asChild?: boolean
}

export function Badge({ className, variant, asChild = false, ...props }: BadgeProps) {
  const Comp = asChild ? Slot : 'span'
  return <Comp data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { badgeVariants }
