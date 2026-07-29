import { ChevronRight } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'

/** 페이지 하단 — 현재 사용 중인 플랜과 변경 안내. */
export function CurrentPlanNotice() {
  return (
    <Card className="flex flex-col gap-3 px-5 py-2.5 shadow-none sm:flex-row sm:items-center sm:justify-between">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px]">
        <span className="font-bold text-ink">현재 AXit Pro를 사용 중이에요.</span>
        <span className="text-ink-muted">플랜을 변경하면 다음 결제일부터 적용됩니다.</span>
      </p>
      <Button
        variant="ghost"
        size="sm"
        className="shrink-0 self-start font-normal text-[#718198] hover:text-[#718198] sm:self-auto"
      >
        결제 및 환불 정책
        <ChevronRight />
      </Button>
    </Card>
  )
}
