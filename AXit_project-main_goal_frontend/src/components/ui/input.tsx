import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

export function Input({ className, type = 'text', ...props }: ComponentProps<'input'>) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        'h-9.5 w-full min-w-0 rounded-lg bg-line-soft px-3 text-sm text-ink transition-all duration-200 outline-none',
        'placeholder:text-ink-subtle',
        'focus-visible:bg-white focus-visible:ring-[3px] focus-visible:ring-primary/18',
        'disabled:cursor-not-allowed disabled:bg-line-soft/60 disabled:text-ink-subtle',
        'aria-invalid:ring-[3px] aria-invalid:ring-danger/20',
        className,
      )}
      {...props}
    />
  )
}

export function Textarea({ className, ...props }: ComponentProps<'textarea'>) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        'min-h-20 w-full resize-none rounded-lg bg-line-soft px-3 py-2.5 text-sm leading-6 text-ink transition-all duration-200 outline-none',
        'placeholder:text-ink-subtle',
        'focus-visible:bg-white focus-visible:ring-[3px] focus-visible:ring-primary/18',
        className,
      )}
      {...props}
    />
  )
}
