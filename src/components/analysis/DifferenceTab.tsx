import { motion } from 'framer-motion'
import { AlertTriangle } from 'lucide-react'

import { staggerContainer, staggerItem } from '@/components/layout/PageTransition'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { AnalysisResult } from '@/types'
import { severityTone } from './DocumentChips'

export interface DifferenceTabProps {
  result: AnalysisResult
}

const clusterTone = [
  'border-primary-200 bg-primary-50/60',
  'border-secondary-200 bg-secondary-50/60',
  'border-warning/25 bg-warning-soft/60',
] as const

/** 상충하는 서술을, 문서가 취한 입장별 그룹으로 묶어 보여줍니다. */
export function DifferenceTab({ result }: DifferenceTabProps) {
  return (
    <motion.div variants={staggerContainer} initial="hidden" animate="show" className="space-y-4">
      {result.differences.map((diff) => (
        <motion.div key={diff.id} variants={staggerItem}>
          <Card className="p-5">
            <div className="flex flex-wrap items-center gap-2.5">
              <span
                className={cn('size-2.5 shrink-0 rounded-full', severityTone[diff.severity].dot)}
              />
              <h3 className="text-[14.5px] font-bold text-ink">{diff.label}</h3>
              <Badge variant={severityTone[diff.severity].badge}>
                차이 {severityTone[diff.severity].label}
              </Badge>
              <span className="ml-auto text-[12px] font-semibold text-ink-subtle">
                {diff.clusters.length}개 그룹으로 갈림
              </span>
            </div>

            <p className="mt-2 text-[13px] leading-5 text-ink-muted">{diff.summary}</p>

            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {diff.clusters.map((cluster, index) => (
                <div
                  key={`${diff.id}-${index}`}
                  className={cn(
                    'rounded-xl border p-3.5 transition-transform duration-200 hover:-translate-y-0.5',
                    clusterTone[index % clusterTone.length],
                  )}
                >
                  <div className="flex flex-wrap items-center gap-1">
                    {cluster.documents.map((doc) => (
                      <span
                        key={doc}
                        className="rounded-md bg-white px-1.5 py-0.5 text-[11px] font-bold text-ink shadow-soft"
                      >
                        {doc}
                      </span>
                    ))}
                  </div>
                  <p className="mt-2.5 text-[12.5px] leading-5 font-semibold text-ink">
                    {cluster.stance}
                  </p>
                </div>
              ))}
            </div>

            {diff.severity === 'high' && (
              <p className="mt-4 flex items-start gap-2 rounded-lg bg-danger-soft/70 px-3 py-2.5 text-[12.5px] leading-5 text-danger">
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                이 항목은 통합 문서에 자동 반영되지 않았습니다. 담당자 확인 후 확정해주세요.
              </p>
            )}
          </Card>
        </motion.div>
      ))}
    </motion.div>
  )
}
