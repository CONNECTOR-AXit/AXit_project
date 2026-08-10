import { motion } from 'framer-motion'
import { Sparkle } from 'lucide-react'

import { FileTypeIcon, kindFromName } from '@/components/common/FileTypeIcon'
import { staggerContainer, staggerItem } from '@/components/layout/PageTransition'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import type { AnalysisResult, DocumentBreakdown } from '@/types'

const sentimentVariant: Record<DocumentBreakdown['sentiment'], BadgeProps['variant']> = {
  적극적: 'secondary',
  중립적: 'neutral',
  보수적: 'warning',
}

export interface PerDocumentTabProps {
  result: AnalysisResult
}

/** 문서별 분석 — 기여도·중복률과 각 파일이 고유하게 더한 내용. */
export function PerDocumentTab({ result }: PerDocumentTabProps) {
  return (
    <motion.div variants={staggerContainer} initial="hidden" animate="show" className="space-y-3">
      {result.breakdown.map((doc, index) => (
        <motion.div key={doc.documentId} variants={staggerItem}>
          <Card className="p-5 transition-shadow hover:shadow-lift">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
              <div className="flex min-w-0 flex-1 items-center gap-3">
                <FileTypeIcon kind={kindFromName(doc.name)} />
                <div className="min-w-0">
                  <p className="flex items-center gap-2 truncate text-[14px] font-bold text-ink">
                    <span className="flex size-5 shrink-0 items-center justify-center rounded bg-line-soft text-[11px] font-extrabold text-ink-muted">
                      {String.fromCharCode(65 + index)}
                    </span>
                    {doc.name}
                  </p>
                  <p className="mt-0.5 text-[12px] text-ink-subtle">
                    RAG 정보 단위 {doc.ragUnits}개 · 최종 문서 반영 {doc.usedRagUnits}개
                  </p>
                </div>
              </div>

              <div className="flex shrink-0 items-center gap-6">
                <div className="w-36">
                  <div className="mb-1 flex items-baseline justify-between">
                    <span className="text-[11.5px] font-semibold text-ink-subtle">기여도</span>
                    <span className="text-[13px] font-extrabold text-ink tabular-nums">
                      {doc.contribution}%
                    </span>
                  </div>
                  <Progress value={doc.contribution} tone="gradient" />
                </div>
                <Badge variant={sentimentVariant[doc.sentiment]}>{doc.sentiment} 서술</Badge>
              </div>
            </div>

            {doc.highlights.length > 0 && <ul className="mt-4 flex flex-wrap gap-2 border-t border-line-soft pt-3.5">
              {doc.highlights.map((highlight) => (
                <li
                  key={highlight}
                  className="flex items-center gap-1.5 rounded-lg bg-line-soft px-2.5 py-1.5 text-[12px] font-medium text-ink-muted"
                >
                  <Sparkle className="size-3 text-ink-subtle" />
                  {highlight}
                </li>
              ))}
            </ul>}
          </Card>
        </motion.div>
      ))}
    </motion.div>
  )
}
