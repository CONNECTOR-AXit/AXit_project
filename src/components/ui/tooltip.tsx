import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import type { ComponentProps, ReactNode } from 'react'

import { cn } from '@/lib/utils'

export const TooltipProvider = TooltipPrimitive.Provider
export const TooltipRoot = TooltipPrimitive.Root
export const TooltipTrigger = TooltipPrimitive.Trigger

export function TooltipContent({
  className,
  sideOffset = 6,
  ...props
}: ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        data-slot="tooltip-content"
        sideOffset={sideOffset}
        className={cn(
          'z-50 rounded-lg bg-ink px-2.5 py-1.5 text-[12px] font-semibold text-white shadow-pop',
          'origin-(--radix-tooltip-content-transform-origin) transition-all duration-150',
          'data-[state=closed]:scale-[0.96] data-[state=closed]:opacity-0',
          className,
        )}
        {...props}
      />
    </TooltipPrimitive.Portal>
  )
}

export interface TooltipProps {
  label: ReactNode
  children: ReactNode
  side?: 'top' | 'right' | 'bottom' | 'left'
  /** 툴팁 자체를 렌더링하지 않음. 사이드바가 펼쳐진 경우 등에 사용합니다. */
  disabled?: boolean
}

/** trigger + 텍스트 조합을 간단히 쓰기 위한 래퍼. */
export function Tooltip({ label, children, side = 'top', disabled }: TooltipProps) {
  if (disabled) return <>{children}</>
  return (
    <TooltipRoot>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side}>{label}</TooltipContent>
    </TooltipRoot>
  )
}
