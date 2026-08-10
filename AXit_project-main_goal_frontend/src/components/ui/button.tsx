import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-semibold outline-none transition-all duration-200 disabled:pointer-events-none disabled:opacity-50 focus-visible:ring-[3px] focus-visible:ring-primary/25 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        primary:
          'bg-primary text-white shadow-brand hover:bg-primary-600 active:bg-primary-700 active:shadow-none',
        gradient: 'brand-gradient text-white hover:brightness-[1.06] active:brightness-95',
        secondary:
          'bg-secondary-50 text-secondary-600 hover:bg-secondary-100 active:bg-secondary-200',
        outline:
          'bg-white text-ink shadow-soft hover:bg-line-soft hover:text-ink active:bg-line',
        ghost: 'text-ink-muted hover:bg-line-soft hover:text-ink active:bg-line',
        subtle: 'bg-line-soft text-ink hover:bg-line active:bg-line',
        danger: 'bg-danger text-white hover:bg-danger/90 active:bg-danger/80',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        sm: 'h-8 gap-1.5 px-3 text-[13px]',
        md: 'h-9.5 px-4',
        lg: 'h-11 px-5 text-[15px]',
        icon: 'size-9.5',
        'icon-sm': 'size-8 rounded-md',
      },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
)

export interface ButtonProps extends ComponentProps<'button'>, VariantProps<typeof buttonVariants> {
  /** button 대신 자식 엘리먼트로 렌더링. Link 와 합성할 때 사용합니다. */
  asChild?: boolean
}

export function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : 'button'
  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  )
}

export { buttonVariants }
