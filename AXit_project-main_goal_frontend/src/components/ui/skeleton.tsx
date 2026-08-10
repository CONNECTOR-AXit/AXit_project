import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

/** 로딩 placeholder. index.css 의 shimmer 키프레임을 사용합니다. */
export function Skeleton({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      data-slot="skeleton"
      className={cn(
        'animate-shimmer rounded-lg bg-[length:200%_100%]',
        'bg-[linear-gradient(90deg,var(--color-line-soft)_25%,var(--color-line)_37%,var(--color-line-soft)_63%)]',
        className,
      )}
      {...props}
    />
  )
}
