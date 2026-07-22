import { Construction } from 'lucide-react'

import { PageHeader } from '@/components/common/PageHeader'
import { PageTransition } from '@/components/layout/PageTransition'
import { Card } from '@/components/ui/card'
import { EmptyState } from './EmptyState'

export interface PhasePlaceholderProps {
  title: string
  description: string
  /** 이 화면을 채울 개발 단계. */
  phase: string
  /** 완성 시 포함될 항목. */
  planned: string[]
}

/**
 * 이후 Phase 에서 구현될 라우트의 임시 화면.
 * 페이지 본문이 없어도 Router / Layout / Navigation 을 완전히 검증할 수 있게 합니다.
 */
export function PhasePlaceholder({ title, description, phase, planned }: PhasePlaceholderProps) {
  return (
    <PageTransition className="space-y-6">
      <PageHeader title={title} description={description} />
      <Card className="p-6">
        <EmptyState
          icon={Construction}
          title={`${phase}에서 구현 예정입니다`}
          description="아래 항목이 이 화면에 들어갑니다."
          className="border-0 bg-transparent py-8"
        />
        <ul className="mx-auto mt-2 grid max-w-md gap-2">
          {planned.map((item, index) => (
            <li
              key={item}
              className="flex items-start gap-2.5 rounded-lg bg-line-soft/70 px-3.5 py-2.5"
            >
              <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-primary-50 text-[11px] font-extrabold text-primary">
                {index + 1}
              </span>
              <span className="text-[13px] leading-5 text-ink-muted">{item}</span>
            </li>
          ))}
        </ul>
      </Card>
    </PageTransition>
  )
}
