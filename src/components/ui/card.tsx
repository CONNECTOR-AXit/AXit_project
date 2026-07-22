import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** 흰 배경 + 얇은 테두리 + Soft Shadow 카드. */
export function Card({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      data-slot="card"
      className={cn(
        'rounded-xl border border-line bg-white shadow-card transition-shadow duration-200',
        className,
      )}
      {...props}
    />
  )
}

export function CardHeader({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      data-slot="card-header"
      className={cn('flex items-start justify-between gap-4 px-5 pt-5 pb-3', className)}
      {...props}
    />
  )
}

export function CardTitle({ className, ...props }: ComponentProps<'h3'>) {
  return (
    <h3
      data-slot="card-title"
      className={cn('text-[15px] leading-6 font-bold tracking-tight text-ink', className)}
      {...props}
    />
  )
}

export function CardDescription({ className, ...props }: ComponentProps<'p'>) {
  return (
    <p
      data-slot="card-description"
      className={cn('text-[13px] leading-5 text-ink-muted', className)}
      {...props}
    />
  )
}

export function CardContent({ className, ...props }: ComponentProps<'div'>) {
  return <div data-slot="card-content" className={cn('px-5 pb-5', className)} {...props} />
}

export function CardFooter({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      data-slot="card-footer"
      className={cn('flex items-center gap-3 border-t border-line px-5 py-3.5', className)}
      {...props}
    />
  )
}
