import { motion } from 'framer-motion'
import { ChevronRight, CircleCheck, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'

import { ContributionPieChart } from '@/components/charts/ContributionPieChart'
import { SectionCard } from '@/components/common/SectionCard'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { AnalysisResult } from '@/types'
import { AnalysisKpiRow } from './AnalysisKpiRow'
import { DocumentChips, severityTone } from './DocumentChips'

export interface SummaryTabProps {
  result: AnalysisResult
  onOpenDifferences: () => void
}

/** 분석 결과 요약 탭 — KPI · 공통 TOP5 · 차이점 요약 · 기여도 · 한줄 인사이트. */
export function SummaryTab({ result, onOpenDifferences }: SummaryTabProps) {
  const topCommon = [...result.commonTopics]
    .sort((a, b) => b.matched / b.total - a.matched / a.total)
    .slice(0, 5)

  const contribution = result.breakdown.map((item, index) => ({
    name: `문서 ${String.fromCharCode(65 + index)}`,
    value: item.contribution,
  }))

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-5">
        <SectionCard
          title="분석 요약"
          description="AI가 각 문서를 분석하여 공통 내용과 차이점을 정리했습니다."
        >
          <AnalysisKpiRow result={result} />
        </SectionCard>

        <div className="grid gap-5 lg:grid-cols-2">
          {/* 공통 내용 */}
          <SectionCard title="공통 내용 TOP 5">
            <ul className="space-y-4">
              {topCommon.map((topic, index) => {
                const pct = Math.round((topic.matched / topic.total) * 100)
                return (
                  <li key={topic.id} className="space-y-1.5">
                    <div className="flex items-center gap-2">
                      <CircleCheck className="size-4 shrink-0 text-success" />
                      <span className="min-w-0 flex-1 truncate text-[13px] font-bold text-ink">
                        {topic.label}
                      </span>
                      <span className="shrink-0 text-[12px] font-bold text-ink tabular-nums">
                        {pct}%
                      </span>
                      <span className="shrink-0 text-[11.5px] text-ink-subtle tabular-nums">
                        ({topic.matched}/{topic.total})
                      </span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-line">
                      <motion.div
                        className="h-full rounded-full bg-success"
                        initial={{ width: 0 }}
                        animate={{ width: `${pct}%` }}
                        transition={{ duration: 0.7, delay: index * 0.06, ease: [0.22, 1, 0.36, 1] }}
                      />
                    </div>
                  </li>
                )
              })}
            </ul>
          </SectionCard>

          {/* 차이점 */}
          <SectionCard
            title="차이점 요약"
            action={
              <Button variant="ghost" size="sm" onClick={onOpenDifferences} className="-mt-1 -mr-2">
                자세히 보기
                <ChevronRight />
              </Button>
            }
          >
            <ul className="space-y-4">
              {result.differences.slice(0, 3).map((diff) => (
                <li key={diff.id} className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn('size-2 shrink-0 rounded-full', severityTone[diff.severity].dot)}
                    />
                    <span className="text-[13px] font-bold text-ink">{diff.label}</span>
                  </div>
                  <p className="pl-4 text-[12.5px] leading-5 text-ink-muted">{diff.summary}</p>
                  <DocumentChips
                    clusters={diff.clusters.map((cluster) => cluster.documents)}
                    className="pl-4"
                  />
                </li>
              ))}
            </ul>
          </SectionCard>
        </div>
      </div>

      {/* 우측 사이드 레일 */}
      <div className="space-y-5">
        <SectionCard title="문서별 기여도" description="통합 문서에 반영된 내용의 비율입니다.">
          <ContributionPieChart data={contribution} height={200} className="sm:flex-col" />
        </SectionCard>

        <Card className="overflow-hidden border-primary-100">
          <div className="brand-gradient h-1 w-full" />
          <div className="p-5">
            <p className="flex items-center gap-1.5 text-[13px] font-bold text-ink">
              <Sparkles className="size-4 text-secondary-500" />
              AI 한줄 인사이트
            </p>
            <p className="mt-2.5 text-[13px] leading-6 text-ink-muted">
              모든 문서가 <strong className="font-bold text-ink">‘캠페인 목표’</strong>와{' '}
              <strong className="font-bold text-ink">‘타겟 분석’</strong>에 대해 일치하고 있으며,{' '}
              <strong className="font-bold text-primary">예산 규모와 실행 채널</strong>에서 가장 큰
              차이를 보이고 있습니다.
            </p>
            <Button asChild variant="outline" size="sm" className="mt-4 w-full">
              <Link to={`/projects/${result.projectId}/editor`}>통합 문서에서 확인하기</Link>
            </Button>
          </div>
        </Card>
      </div>
    </div>
  )
}
