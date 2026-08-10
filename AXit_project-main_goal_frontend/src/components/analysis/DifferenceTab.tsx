import { motion } from 'framer-motion'
import { AlertTriangle } from 'lucide-react'

import { staggerContainer, staggerItem } from '@/components/layout/PageTransition'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { AnalysisResult, VerificationVerdict } from '@/types'
import { severityTone } from './DocumentChips'

export interface DifferenceTabProps {
  result: AnalysisResult
}

const verdictLabel: Record<VerificationVerdict, string> = {
  supported: '사실 확인됨',
  refuted: '사실과 다름',
  mixed: '부분 확인 · 검증 의심',
  unverifiable: '확인 불가 · 검증 의심',
}

/** 반박·혼합·검증 불가 결과는 확인 전까지 그대로 믿지 말라고 알립니다. */
const needsCaution = (verdict: VerificationVerdict | undefined) =>
  verdict === 'refuted' || verdict === 'mixed' || verdict === 'unverifiable'

/** 각 주장을 외부 자료로 검증한 결과를 보여줍니다. */
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
                {diff.verdict ? verdictLabel[diff.verdict] : severityTone[diff.severity].label}
              </Badge>
            </div>

            <p className="mt-2 text-[13px] leading-5 text-ink-muted">{diff.summary}</p>

            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {diff.clusters.map((cluster, index) => (
                <div
                  key={`${diff.id}-${index}`}
                  className="rounded-xl bg-line-soft p-3.5 transition-transform duration-200 hover:-translate-y-0.5"
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

            {needsCaution(diff.verdict) && (
              <p className="mt-4 flex items-start gap-2 rounded-lg bg-danger-soft/70 px-3 py-2.5 text-[12.5px] leading-5 text-danger">
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                외부 검증 결과 주의가 필요해요 — 통합 문서에 반영하기 전에 직접 확인해주세요.
              </p>
            )}
          </Card>
        </motion.div>
      ))}
    </motion.div>
  )
}
