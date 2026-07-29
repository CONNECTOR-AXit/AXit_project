import { Check } from 'lucide-react'

export interface PlanFeatureProps {
  text: string
}

/** 요금제 카드의 체크 항목 한 줄. */
export function PlanFeature({ text }: PlanFeatureProps) {
  return (
    <li className="flex items-start gap-2">
      <Check className="mt-0.5 size-4 shrink-0 text-[#2777E7]" strokeWidth={2.5} />
      <span className="text-[13px] leading-5 text-ink-muted">{text}</span>
    </li>
  )
}
