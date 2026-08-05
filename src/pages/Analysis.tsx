import { AnimatePresence, motion } from 'framer-motion'
import { ArrowRight, CheckCircle2, Clock, FileText, RotateCcw, Sparkles, X } from 'lucide-react'
import { useEffect } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { AnalysisStepper } from '@/components/analysis/AnalysisStepper'
import { CircularProgress } from '@/components/common/CircularProgress'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { PageTransition } from '@/components/layout/PageTransition'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useAnalysisSimulation } from '@/hooks/useAnalysisSimulation'
import { useIsMobile } from '@/hooks/useMediaQuery'
import { projectById } from '@/data/projects'
import { formatDateTime, formatDuration } from '@/lib/format'

export default function Analysis() {
  const { projectId = 'p-1' } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const isMobile = useIsMobile()
  const project = projectById(projectId)

  const { progress, currentStep, stepStates, remainingSeconds, isComplete, restart } =
    useAnalysisSimulation({ durationMs: 22_000 })

  // 파이프라인이 끝나면 잠시 뒤 결과 페이지로 넘겨줍니다.
  useEffect(() => {
    if (!isComplete) return
    const timer = setTimeout(() => navigate(`/projects/${projectId}/result`), 1600)
    return () => clearTimeout(timer)
  }, [isComplete, navigate, projectId])

  const documentCount = project?.documentCount ?? 5

  return (
    <PageTransition className="space-y-6">
      <PageHeader
        breadcrumbs={[
          { label: '프로젝트', to: '/projects' },
          { label: project?.name ?? '프로젝트', to: `/projects/${projectId}` },
          { label: 'AI 분석' },
        ]}
        title={isComplete ? 'AI 분석 완료' : 'AI 분석 진행 중'}
        description={
          isComplete
            ? '분석이 끝났습니다. 결과 페이지로 이동합니다.'
            : '업로드된 문서를 분석하고 있습니다. 잠시만 기다려주세요.'
        }
        actions={
          <Button asChild variant="outline">
            <Link to={`/projects/${projectId}`}>
              <X />
              분석 중단
            </Link>
          </Button>
        }
      />

      <Card className="overflow-hidden">
        <div className="brand-gradient h-1 w-full" />
        <div className="flex flex-col items-center px-5 py-10 sm:px-10">
          <CircularProgress
            value={progress}
            size={200}
            strokeWidth={14}
            glow={!isComplete}
            tone={isComplete ? 'success' : 'gradient'}
          >
            <AnimatePresence mode="wait">
              {isComplete ? (
                <motion.span
                  key="done"
                  initial={{ scale: 0.6, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{ type: 'spring', stiffness: 300, damping: 18 }}
                  className="flex flex-col items-center gap-1"
                >
                  <CheckCircle2 className="size-11 text-success" strokeWidth={2} />
                  <span className="text-[13px] font-bold text-success">완료</span>
                </motion.span>
              ) : (
                <motion.span key="pct" className="flex flex-col items-center">
                  <span className="text-[34px] leading-10 font-extrabold tracking-tight text-ink tabular-nums">
                    {progress}%
                  </span>
                </motion.span>
              )}
            </AnimatePresence>
          </CircularProgress>

          <AnimatePresence mode="wait">
            <motion.div
              key={isComplete ? 'complete' : currentStep.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.25 }}
              className="mt-7 text-center"
            >
              <p className="text-[19px] font-extrabold tracking-tight text-ink">
                {isComplete ? '통합 문서가 준비되었어요' : `${currentStep.label} 중...`}
              </p>
              <p className="mt-1.5 text-[13.5px] text-ink-muted">
                {isComplete ? '공통 내용 12건과 차이점 8건을 정리했습니다.' : currentStep.caption}
              </p>
            </motion.div>
          </AnimatePresence>

          {isComplete && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              className="mt-6 flex flex-wrap justify-center gap-2"
            >
              <Button asChild variant="gradient">
                <Link to={`/projects/${projectId}/result`}>
                  분석 결과 보기
                  <ArrowRight />
                </Link>
              </Button>
              <Button variant="outline" onClick={restart}>
                <RotateCcw />
                다시 분석하기
              </Button>
            </motion.div>
          )}

          <div className="mt-10 w-full max-w-3xl">
            <AnalysisStepper
              stepStates={stepStates}
              orientation={isMobile ? 'vertical' : 'horizontal'}
            />
          </div>
        </div>
      </Card>

      <SectionCard title="분석 정보">
        <dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <InfoTile icon={FileText} label="프로젝트" value={project?.name ?? '—'} />
          <InfoTile icon={Sparkles} label="분석 문서 수" value={`${documentCount}개`} />
          <InfoTile
            icon={Clock}
            label="예상 완료 시간"
            value={isComplete ? '완료됨' : formatDuration(remainingSeconds)}
          />
          <InfoTile icon={Clock} label="시작 시간" value={formatDateTime('2024-05-15T14:20:00')} />
        </dl>
      </SectionCard>
    </PageTransition>
  )
}

function InfoTile({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof FileText
  label: string
  value: string
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl bg-line-soft/50 px-4 py-3">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-white text-ink-muted shadow-soft">
        <Icon className="size-4" />
      </span>
      <div className="min-w-0">
        <dt className="text-[11.5px] font-semibold text-ink-subtle">{label}</dt>
        <dd className="truncate text-[13px] font-bold text-ink">{value}</dd>
      </div>
    </div>
  )
}
