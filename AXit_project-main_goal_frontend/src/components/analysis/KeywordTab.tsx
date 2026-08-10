import { motion } from 'framer-motion'
import { Minus, TrendingDown, TrendingUp } from 'lucide-react'

import { SectionCard } from '@/components/common/SectionCard'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import type { AnalysisResult, Keyword } from '@/types'

const trendMeta = {
  up: { icon: TrendingUp, className: 'text-success' },
  down: { icon: TrendingDown, className: 'text-danger' },
  flat: { icon: Minus, className: 'text-ink-subtle' },
} as const

/** 가중치가 클수록 글자를 키워, 클라우드가 실제 빈도 지도처럼 읽히게 합니다. */
function sizeFor(weight: number) {
  if (weight >= 90) return 'text-[26px]'
  if (weight >= 75) return 'text-[22px]'
  if (weight >= 60) return 'text-[18px]'
  if (weight >= 45) return 'text-[16px]'
  return 'text-[14px]'
}

function toneFor(weight: number) {
  if (weight >= 90) return 'bg-primary text-white border-transparent shadow-brand'
  if (weight >= 60) return 'bg-line text-ink border-transparent'
  return 'bg-line-soft text-ink-muted border-transparent'
}

export interface KeywordTabProps {
  result: AnalysisResult
}

/** 키워드 클라우드 + 가중치 순위. */
export function KeywordTab({ result }: KeywordTabProps) {
  const ranked = [...result.keywords].sort((a, b) => b.weight - a.weight)

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
      <SectionCard
        title="키워드 클라우드"
        description="문서 전체에서 추출한 핵심 키워드입니다. 크기는 등장 빈도에 비례합니다."
      >
        <div className="flex flex-wrap items-center gap-2.5 py-2">
          {ranked.map((keyword, index) => (
            <motion.span
              key={keyword.term}
              initial={{ opacity: 0, scale: 0.85 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: index * 0.035, duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
              whileHover={{ scale: 1.06 }}
              className={cn(
                'cursor-default rounded-xl border px-3 py-1.5 leading-none font-bold transition-shadow hover:shadow-card',
                sizeFor(keyword.weight),
                toneFor(keyword.weight),
              )}
            >
              {keyword.term}
            </motion.span>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="키워드 순위" description="가중치 및 등장 문서 수 기준">
        <ul className="space-y-3">
          {ranked.slice(0, 8).map((keyword, index) => (
            <KeywordRow key={keyword.term} keyword={keyword} rank={index + 1} />
          ))}
        </ul>
      </SectionCard>
    </div>
  )
}

function KeywordRow({ keyword, rank }: { keyword: Keyword; rank: number }) {
  const meta = trendMeta[keyword.trend]
  return (
    <li className="space-y-1.5">
      <div className="flex items-center gap-2">
        <span className="w-4 shrink-0 text-[11.5px] font-extrabold text-ink-subtle tabular-nums">
          {rank}
        </span>
        <span className="min-w-0 flex-1 truncate text-[13px] font-bold text-ink">
          {keyword.term}
        </span>
        <meta.icon className={cn('size-3.5 shrink-0', meta.className)} />
        <span className="w-10 shrink-0 text-right text-[12px] font-bold text-ink tabular-nums">
          {keyword.weight}
        </span>
      </div>
      <div className="flex items-center gap-2 pl-6">
        <Progress value={keyword.weight} tone="gradient" className="h-1" />
        <span className="w-14 shrink-0 text-right text-[11px] text-ink-subtle">
          문서 {keyword.documents}개
        </span>
      </div>
    </li>
  )
}
