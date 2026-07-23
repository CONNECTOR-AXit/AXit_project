import { motion } from 'framer-motion'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Info,
  Sparkles,
  type LucideIcon,
} from 'lucide-react'
import { Link } from 'react-router-dom'

import { staggerContainer, staggerItem } from '@/components/layout/PageTransition'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { AiInsight, AnalysisResult } from '@/types'

const toneMeta: Record<AiInsight['tone'], { icon: LucideIcon; badge: string; bar: string }> = {
  positive: { icon: CheckCircle2, badge: 'bg-success-soft text-success', bar: 'bg-success' },
  caution: { icon: AlertTriangle, badge: 'bg-warning-soft text-warning', bar: 'bg-warning' },
  neutral: { icon: Info, badge: 'bg-primary-50 text-primary', bar: 'bg-primary' },
}

export interface InsightTabProps {
  result: AnalysisResult
}

/** AI 종합 인사이트 — 헤드라인, 톤별 인사이트 카드, 추천 다음 단계. */
export function InsightTab({ result }: InsightTabProps) {
  return (
    <div className="space-y-5">
      {/* 헤드라인 카드 */}
      <Card className="relative overflow-hidden border-primary-100">
        <div className="brand-gradient absolute inset-x-0 top-0 h-1" />
        <div className="flex flex-col gap-4 p-6 lg:flex-row lg:items-center">
          <span className="brand-gradient flex size-11 shrink-0 items-center justify-center rounded-xl text-white shadow-brand">
            <Sparkles className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[12px] font-bold tracking-wide text-primary">AI 종합 인사이트</p>
            <p className="mt-1 text-[15px] leading-7 font-semibold text-ink">{result.headline}</p>
          </div>
          <Button asChild variant="gradient" className="shrink-0">
            <Link to={`/projects/${result.projectId}/editor`}>
              통합 문서 편집
              <ArrowRight />
            </Link>
          </Button>
        </div>
      </Card>

      <motion.div
        variants={staggerContainer}
        initial="hidden"
        animate="show"
        className="grid gap-4 lg:grid-cols-3"
      >
        {result.insights.map((insight) => {
          const meta = toneMeta[insight.tone]
          return (
            <motion.div key={insight.id} variants={staggerItem}>
              <Card className="relative h-full overflow-hidden p-5 transition-all duration-250 hover:-translate-y-0.5 hover:shadow-lift">
                <span className={cn('absolute inset-y-0 left-0 w-1', meta.bar)} />
                <span className={cn('flex size-9 items-center justify-center rounded-lg', meta.badge)}>
                  <meta.icon className="size-4" />
                </span>
                <h3 className="mt-3.5 text-[14px] leading-5 font-bold text-ink">{insight.title}</h3>
                <p className="mt-2 text-[13px] leading-6 text-ink-muted">{insight.body}</p>
              </Card>
            </motion.div>
          )
        })}
      </motion.div>

      {/* 추천 다음 단계 */}
      <Card className="p-5">
        <h3 className="text-[14px] font-bold text-ink">추천 다음 단계</h3>
        <ol className="mt-3.5 space-y-2.5">
          {[
            '예산 담당자에게 총 예산 확정을 요청하세요.',
            'KPI 정의를 1차 · 2차로 계층화해 통합 문서에 반영하세요.',
            '실행 채널 우선순위는 런칭 4주 후 성과 데이터로 재조정하세요.',
          ].map((step, index) => (
            <li key={step} className="flex items-start gap-3">
              <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-primary-50 text-[11px] font-extrabold text-primary">
                {index + 1}
              </span>
              <span className="text-[13px] leading-5 text-ink-muted">{step}</span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  )
}
