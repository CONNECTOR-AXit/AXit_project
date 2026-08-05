import * as TabsPrimitive from '@radix-ui/react-tabs'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

export const Tabs = TabsPrimitive.Root

/** 밑줄형 탭 바 — 페이지 레벨 네비게이션에 씁니다. */
export function TabsList({ className, ...props }: ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn(
        'scrollbar-none flex w-full items-center gap-1 overflow-x-auto',
        className,
      )}
      {...props}
    />
  )
}

export function TabsTrigger({ className, ...props }: ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        'relative -mb-px shrink-0 rounded-t-md px-3.5 py-2.5 text-sm font-semibold whitespace-nowrap text-ink-muted transition-colors outline-none',
        'hover:bg-line-soft hover:text-ink',
        'focus-visible:ring-[3px] focus-visible:ring-primary/20',
        // 밑줄은 항상 자리를 차지하고 색만 바뀌어 레이아웃이 흔들리지 않습니다.
        'after:absolute after:inset-x-2.5 after:-bottom-px after:h-0.5 after:rounded-full after:bg-transparent after:transition-colors',
        'data-[state=active]:text-primary data-[state=active]:after:bg-primary',
        className,
      )}
      {...props}
    />
  )
}

/** 알약형 탭 — 카드 안쪽 좁은 영역의 전환에 씁니다. */
export function TabsListPill({ className, ...props }: ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list-pill"
      className={cn(
        'inline-flex items-center gap-0.5 rounded-lg bg-line-soft p-0.5',
        className,
      )}
      {...props}
    />
  )
}

export function TabsTriggerPill({
  className,
  ...props
}: ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger-pill"
      className={cn(
        'rounded-[6px] px-3 py-1 text-[13px] font-semibold text-ink-muted transition-all outline-none',
        'hover:text-ink',
        'data-[state=active]:bg-white data-[state=active]:text-ink data-[state=active]:shadow-soft',
        className,
      )}
      {...props}
    />
  )
}

export function TabsContent({ className, ...props }: ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn('mt-5 outline-none', className)}
      {...props}
    />
  )
}
