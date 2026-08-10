import { motion } from 'framer-motion'

import { staggerItem } from '@/components/layout/PageTransition'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { priceFor, type BillingCycle, type PricingPlan } from '@/data/pricing'
import { cn } from '@/lib/utils'
import { PlanFeature } from './PlanFeature'

export interface PricingCardProps {
  plan: PricingPlan
  billing: BillingCycle
}

/** 단일 요금제 카드. 추천 플랜은 상단 리본·Primary 테두리·Primary 버튼으로 강조합니다. */
export function PricingCard({ plan, billing }: PricingCardProps) {
  const price = priceFor(plan, billing)

  const groups = [
    { heading: '월 변환 시간', items: [plan.conversionTime] },
    { heading: '월 AI 요약 횟수', items: [plan.aiSummary] },
    { heading: '기본 기능', items: plan.features },
  ]

  return (
    <motion.div
      variants={staggerItem}
      whileHover={{ y: -4 }}
      transition={{ type: 'spring', stiffness: 300, damping: 24 }}
    >
      <Card
        className={cn(
          'flex flex-col overflow-hidden p-0 shadow-none',
          plan.recommended && 'border-[#2777E7] ring-1 ring-[#2777E7]/25',
        )}
      >
        {plan.recommended && (
          <div className="bg-[#2777E7] py-2 text-center text-[12px] font-bold text-white">
            가장 인기있는 플랜
          </div>
        )}

        <div className={cn('flex flex-1 flex-col px-7 pt-7', plan.recommended ? 'pb-19' : 'pb-24')}>
          {/* 상단 — 플랜명 · 가격 · 설명 */}
          <h3 className="text-[15px] font-bold text-[#182235]">{plan.name}</h3>
          <p className="mt-3 text-[26px] leading-8 font-extrabold tracking-tight text-[#182235] tabular-nums">
            {price.toLocaleString('ko-KR')}원
          </p>
          <p className="mt-1 text-[12px] text-ink-subtle">기업당 월 비용</p>
          <p className="mt-3 min-h-[40px] text-[12.5px] leading-5 text-ink-muted">
            {plan.description}
          </p>

          <Button
            variant={plan.buttonType === 'primary' ? 'primary' : 'outline'}
            className={cn(
              'mt-5 w-full font-medium shadow-none!',
              plan.buttonType === 'primary'
                ? 'bg-[#2777E7] hover:bg-[#2777E7] hover:brightness-95'
                : 'border-[#2777E7] text-[#2777E7] hover:text-[#2777E7]',
            )}
          >
            무료체험 신청
          </Button>

          <div className="my-6 h-px bg-line-soft" />

          {/* 기능 그룹 */}
          <div className="space-y-7 pb-2">
            {groups.map((group) => (
              <div key={group.heading}>
                <p className="text-[12.5px] font-bold text-[#182235]">{group.heading}</p>
                <ul className="mt-2.5 space-y-2.5">
                  {group.items.map((item) => (
                    <PlanFeature key={item} text={item} />
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </Card>
    </motion.div>
  )
}
