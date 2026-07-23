import { motion } from 'framer-motion'
import { CircleCheck, Quote } from 'lucide-react'

import { staggerContainer, staggerItem } from '@/components/layout/PageTransition'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import type { AnalysisResult } from '@/types'

export interface CommonTabProps {
  result: AnalysisResult
}

/** 공통 주제 전체를, 그 근거가 되는 원문 발췌와 함께 보여줍니다. */
export function CommonTab({ result }: CommonTabProps) {
  return (
    <motion.div
      variants={staggerContainer}
      initial="hidden"
      animate="show"
      className="grid gap-4 lg:grid-cols-2"
    >
      {result.commonTopics.map((topic) => {
        const pct = Math.round((topic.matched / topic.total) * 100)
        return (
          <motion.div key={topic.id} variants={staggerItem}>
            <Card className="h-full p-5 transition-shadow hover:shadow-lift">
              <div className="flex items-start gap-2.5">
                <CircleCheck className="mt-0.5 size-4.5 shrink-0 text-success" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="min-w-0 flex-1 truncate text-[14px] font-bold text-ink">
                      {topic.label}
                    </h3>
                    <Badge variant={pct === 100 ? 'success' : 'neutral'}>
                      {topic.matched}/{topic.total} 문서
                    </Badge>
                  </div>
                  <p className="mt-1.5 text-[13px] leading-5 text-ink-muted">{topic.summary}</p>
                </div>
              </div>

              <div className="mt-3.5 h-1.5 overflow-hidden rounded-full bg-line">
                <motion.div
                  className="h-full rounded-full bg-success"
                  initial={{ width: 0 }}
                  animate={{ width: `${pct}%` }}
                  transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
                />
              </div>

              <ul className="mt-4 space-y-2">
                {topic.excerpts.map((excerpt, index) => (
                  <li
                    key={`${topic.id}-${index}`}
                    className="rounded-lg border border-line bg-line-soft/50 px-3 py-2.5"
                  >
                    <p className="flex items-center gap-1.5 text-[11.5px] font-bold text-ink-subtle">
                      <Quote className="size-3" />
                      {excerpt.document}
                    </p>
                    <p className="mt-1 text-[12.5px] leading-5 text-ink">{excerpt.text}</p>
                  </li>
                ))}
              </ul>
            </Card>
          </motion.div>
        )
      })}
    </motion.div>
  )
}
