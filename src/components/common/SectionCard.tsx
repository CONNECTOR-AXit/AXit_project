import type { ReactNode } from 'react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

export interface SectionCardProps {
  title: ReactNode
  description?: ReactNode
  /** 헤더 우측에 배치할 버튼이나 범례. */
  action?: ReactNode
  children: ReactNode
  className?: string
  contentClassName?: string
}

/**
 * 제목 헤더 + 우측 액션을 가진 카드 섹션.
 * Card 하위 컴포넌트를 매번 조합하지 않도록 자주 쓰는 형태를 묶었습니다.
 */
export function SectionCard({
  title,
  description,
  action,
  children,
  className,
  contentClassName,
}: SectionCardProps) {
  return (
    <Card className={className}>
      <CardHeader>
        <div className="min-w-0 space-y-0.5">
          <CardTitle>{title}</CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </div>
        {action}
      </CardHeader>
      <CardContent className={cn(contentClassName)}>{children}</CardContent>
    </Card>
  )
}
