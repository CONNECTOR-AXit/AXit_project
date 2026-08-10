import { ChevronRight, Sparkles } from 'lucide-react'
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

/** 분석 결과 요약 탭 — KPI · 외부검증 요약 · 기여도 · 한줄 인사이트. */
export function SummaryTab({ result, onOpenDifferences }: SummaryTabProps) {
  const contribution = result.breakdown.map((item) => ({
    name: item.name,
    value: item.contribution,
  }))

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-5">
        <SectionCard
          title="분석 요약"
          description="AI가 각 문서를 요약하고, 주요 주장을 외부 자료로 검증했습니다."
        >
          <AnalysisKpiRow result={result} />
        </SectionCard>

        <SectionCard
          title="외부검증 요약"
          description="문서의 주요 주장이 외부 자료와 얼마나 일치하는지 확인한 결과입니다."
          action={
            <Button variant="ghost" size="sm" onClick={onOpenDifferences} className="-mt-1 -mr-2">
              자세히 보기
              <ChevronRight />
            </Button>
          }
        >
          <ul className="space-y-4">
            {result.differences.slice(0, 5).map((diff) => (
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

      {/* 우측 사이드 레일 */}
      <div className="space-y-5">
        <SectionCard title="문서별 기여도" description="통합 문서에 반영된 내용의 비율입니다.">
          <ContributionPieChart data={contribution} height={200} className="sm:flex-col" />
        </SectionCard>

        <Card className="overflow-hidden border-primary-100">
          <div className="brand-gradient h-1 w-full" />
          <div className="p-5">
            <p className="flex items-center gap-1.5 text-[13px] font-bold text-ink">
              <Sparkles className="size-4 text-ink-muted" />
              AI 분석 결과
            </p>
            <p className="mt-2.5 text-[13px] leading-6 text-ink-muted">{result.oneLineInsight}</p>
            <Button asChild variant="outline" size="sm" className="mt-4 w-full">
              <Link to={`/projects/${result.projectId}/editor`}>통합 문서에서 확인하기</Link>
            </Button>
          </div>
        </Card>
      </div>
    </div>
  )
}
