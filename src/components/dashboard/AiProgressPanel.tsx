import { motion } from 'framer-motion'
import { Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import type { Project } from '@/types'

/** 상태별로 지금 무슨 단계인지 한 줄로 설명합니다. */
const stageLabel: Record<Project['status'], string> = {
  draft: '문서 대기 중',
  uploading: '문서 업로드 중',
  analyzing: '공통·차이점 분석 중',
  review: '통합 문서 검토 중',
  completed: '통합 완료',
}

export interface AiProgressPanelProps {
  /** 진행 중인 프로젝트. 완료된 항목은 호출부에서 걸러 넘깁니다. */
  projects: Project[]
  credit: { used: number; total: number }
  className?: string
}

/** 아직 통합이 끝나지 않은 프로젝트의 AI 파이프라인 현황. */
export function AiProgressPanel({ projects, credit, className }: AiProgressPanelProps) {
  const creditPercent = Math.round((credit.used / credit.total) * 100)

  return (
    <div className={cn('space-y-4', className)}>
      {projects.length === 0 && (
        <p className="py-8 text-center text-[13px] text-ink-muted">진행 중인 AI 분석이 없습니다.</p>
      )}

      {projects.map((project) => (
        <div key={project.id} className="space-y-2">
          <div className="flex items-center gap-2">
            {/* 진행 중임을 나타내는 맥박 점 */}
            <span className="relative flex size-1.5 shrink-0">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-secondary opacity-70" />
              <span className="relative inline-flex size-1.5 rounded-full bg-secondary" />
            </span>
            <Link
              to={`/projects/${project.id}`}
              className="min-w-0 flex-1 truncate text-[13px] font-bold text-ink transition-colors hover:text-primary"
            >
              {project.name}
            </Link>
            <span className="shrink-0 text-[12px] font-bold text-ink tabular-nums">
              {project.progress}%
            </span>
          </div>
          <Progress value={project.progress} tone="gradient" />
          <p className="text-[11.5px] text-ink-subtle">
            {stageLabel[project.status]} · 문서 {project.documentCount}개
          </p>
        </div>
      ))}

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        className="rounded-xl border border-primary-100 bg-primary-50/60 p-4"
      >
        <p className="flex items-center gap-1.5 text-[12.5px] font-bold text-primary">
          <Sparkles className="size-3.5" />
          AI 크레딧
        </p>
        <p className="mt-1.5 text-[12px] leading-4 text-ink-muted">
          이번 달{' '}
          <span className="font-bold text-ink">
            {credit.used} / {credit.total}
          </span>
          회 분석을 사용했어요.
        </p>
        <Progress value={creditPercent} tone="primary" className="mt-2.5 bg-white" />
        <Button
          asChild
          variant="ghost"
          size="sm"
          className="mt-2 h-7 w-full text-primary hover:bg-white"
        >
          <Link to="/settings">플랜 관리</Link>
        </Button>
      </motion.div>
    </div>
  )
}
