export type BillingCycle = 'annual' | 'monthly'

export interface PricingPlan {
  id: string
  name: string
  price: number
  description: string
  recommended: boolean
  /** 월 변환 시간 (예: '1,000분') */
  conversionTime: string
  /** 월 AI 요약 횟수 (예: '25회') */
  aiSummary: string
  /** 공통 기본 기능 목록 */
  features: string[]
  buttonType: 'primary' | 'outline'
}

/** 연간 결제 시 할인율(최대 20%). */
export const ANNUAL_DISCOUNT = 0.2

/**
 * 카드에 표시할 월 요금.
 * `price` 는 연간 결제(기본) 기준 월 요금이며, 월간은 할인 전 정가로 환산합니다.
 */
export function priceFor(plan: PricingPlan, billing: BillingCycle): number {
  if (billing === 'annual') return plan.price
  return Math.round(plan.price / (1 - ANNUAL_DISCOUNT) / 10) * 10
}

/** 전 플랜 공통 기본 기능. */
const baseFeatures = ['실시간 녹음/파일 업로드 지원', '계정당 동시 접속 기기 2대', 'PC웹/화상회의 녹음']

export const pricingPlans: PricingPlan[] = [
  {
    id: 'lite',
    name: 'Lite',
    price: 18000,
    description: '소규모 팀 단위 또는, 가볍게 시작하기 좋은 플랜',
    recommended: false,
    buttonType: 'outline',
    conversionTime: '1,000분',
    aiSummary: '25회',
    features: baseFeatures,
  },
  {
    id: 'team',
    name: 'Team',
    price: 86500,
    description: '팀/부서 단위 모임 또는, 본격적으로 노트 활용하는 기업에 추천',
    recommended: true,
    buttonType: 'primary',
    conversionTime: '6,000분',
    aiSummary: '150회',
    features: baseFeatures,
  },
  {
    id: 'business',
    name: 'Business',
    price: 423000,
    description: '규모 있는 조직/회사 단위 모임 또는, 회의가 빈번한 기업에 최적화한 플랜',
    recommended: false,
    buttonType: 'outline',
    conversionTime: '3,000분',
    aiSummary: '750회',
    features: baseFeatures,
  },
  {
    id: 'business-plus',
    name: 'Business Plus',
    price: 1651000,
    description: '대형 기업 또는, 회의 프로세스 디지털화(DX)를 위한 플랜',
    recommended: false,
    buttonType: 'outline',
    conversionTime: '120,000분',
    aiSummary: '3,000회',
    features: baseFeatures,
  },
]
