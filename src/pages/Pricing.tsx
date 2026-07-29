import { useState } from 'react'

import { PageHeader } from '@/components/common/PageHeader'
import { PageTransition, staggerContainer } from '@/components/layout/PageTransition'
import { CurrentPlanNotice } from '@/components/pricing/CurrentPlanNotice'
import { PricingCard } from '@/components/pricing/PricingCard'
import { PricingToggle } from '@/components/pricing/PricingToggle'
import { pricingPlans, type BillingCycle } from '@/data/pricing'
import { motion } from 'framer-motion'

export default function Pricing() {
  const [billing, setBilling] = useState<BillingCycle>('annual')

  return (
    <PageTransition className="space-y-10">
      <PageHeader
        breadcrumbs={[{ label: '설정', to: '/settings' }, { label: '이용요금' }]}
        title="이용요금"
        description="업무 환경과 팀 규모에 맞는 플랜을 선택하세요."
        actions={
          <div className="flex items-center gap-3">
            {billing === 'annual' && (
              <p className="hidden text-[12.5px] font-medium text-[#2777E7] sm:block">
                연간 결제 시 최대 20% 할인
              </p>
            )}
            <PricingToggle value={billing} onChange={setBilling} />
          </div>
        }
      />

      <motion.div
        variants={staggerContainer}
        initial="hidden"
        animate="show"
        className="grid grid-cols-1 items-end gap-6 pt-3 lg:grid-cols-2 xl:grid-cols-4"
      >
        {pricingPlans.map((plan) => (
          <PricingCard key={plan.id} plan={plan} billing={billing} />
        ))}
      </motion.div>

      <CurrentPlanNotice />
    </PageTransition>
  )
}
