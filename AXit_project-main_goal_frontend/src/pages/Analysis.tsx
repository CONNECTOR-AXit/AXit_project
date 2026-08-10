import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, ArrowRight, CheckCircle2, Clock, FileText, Sparkles, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { ApiError } from '@/api/client'
import { useAnalysisProgress, useProject, useRetryAnalysis } from '@/api/queries'
import { AnalysisStepper } from '@/components/analysis/AnalysisStepper'
import { CircularProgress } from '@/components/common/CircularProgress'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { PageTransition } from '@/components/layout/PageTransition'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { analysisSteps, type AnalysisStep, type StepState } from '@/lib/analysisSteps'
import { useIsMobile } from '@/hooks/useMediaQuery'
import { formatDuration } from '@/lib/format'

const STEP_ORDER: AnalysisStep['id'][] = ['extract', 'common', 'difference', 'merge', 'suggestions']

export default function Analysis() {
  const { projectId = 'p-1' } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const isMobile = useIsMobile()
  const { data: projectData } = useProject(projectId)
  const project = projectData?.project

  const { data: progress, isError, error, refetch } = useAnalysisProgress(projectId)
  const retryAnalysis = useRetryAnalysis(projectId)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)

  useEffect(() => {
    const timer = setInterval(() => setElapsedSeconds((s) => s + 1), 1000)
    return () => clearInterval(timer)
  }, [])

  // 실제로 각 단계가 끝났는지로만 판정합니다 — 고정 시간으로 흉내 내지 않습니다.
  const doneFlags: Record<AnalysisStep['id'], boolean> = {
    extract: progress?.extractionDone ?? false,
    common: progress?.summaryDone ?? false,
    difference: progress?.researchDone ?? false,
    merge: progress?.reportDone ?? false,
    suggestions: progress?.suggestionsDone ?? false,
  }
  const stepStates: Record<AnalysisStep['id'], StepState> = useMemo(() => {
    const extractionDone = progress?.extractionDone ?? false
    const summaryDone = progress?.summaryDone ?? false
    const researchDone = progress?.researchDone ?? false
    const reportDone = progress?.reportDone ?? false
    const suggestionsDone = progress?.suggestionsDone ?? false
    return {
      extract: extractionDone ? 'done' : 'active',
      // 요약과 외부 검증은 추출 후 서로를 기다리지 않고 병렬 실행됩니다.
      common: summaryDone ? 'done' : extractionDone ? 'active' : 'waiting',
      difference: researchDone ? 'done' : extractionDone ? 'active' : 'waiting',
      merge: reportDone ? 'done' : summaryDone && researchDone ? 'active' : 'waiting',
      suggestions: suggestionsDone ? 'done' : reportDone ? 'active' : 'waiting',
    }
  }, [progress])

  const doneCount = STEP_ORDER.filter((id) => doneFlags[id]).length
  const allDocumentsSettled = progress?.extractionDone ?? false
  const isComplete =
    allDocumentsSettled &&
    doneFlags.common &&
    doneFlags.difference &&
    doneFlags.merge &&
    doneFlags.suggestions &&
    (progress?.resultDone ?? false)
  // 화면에 보이는 모든 단계가 끝나도 result API 검증이 남아 있으면 100%를
  // 노출하지 않습니다. 100%는 결과 페이지가 즉시 열릴 수 있다는 의미입니다.
  const calculatedPercent = Math.round((doneCount / STEP_ORDER.length) * 100)
  const percent = isComplete ? 100 : Math.min(99, calculatedPercent)
  const isFailed = progress?.sessionState === 'needs_attention'
  const parallelGenerationActive =
    stepStates.common === 'active' && stepStates.difference === 'active'
  const currentStep: AnalysisStep = parallelGenerationActive
    ? {
        id: 'common',
        label: '문서 요약 및 외부 검증',
        caption: '문서 요약과 외부 사실 검증을 동시에 진행하는 중',
      }
    : (analysisSteps.find((step) => stepStates[step.id] === 'active') ??
      analysisSteps[analysisSteps.length - 1]!)

  // 실제로 리포트가 준비됐을 때만 결과 페이지로 넘어갑니다.
  useEffect(() => {
    if (!isComplete) return
    const timer = setTimeout(() => navigate(`/projects/${projectId}/analysis/result`), 1600)
    return () => clearTimeout(timer)
  }, [isComplete, navigate, projectId])

  const documentCount = project?.documentCount ?? 5

  const unexpectedErrorMessage =
    isError && !isFailed
      ? error instanceof ApiError
        ? error.message
        : '분석 상태를 확인하지 못했어요.'
      : null

  return (
    <PageTransition className="space-y-6">
      <PageHeader
        breadcrumbs={[
          { label: '프로젝트', to: '/projects' },
          { label: project?.name ?? '프로젝트', to: `/projects/${projectId}` },
          { label: 'AI 분석' },
        ]}
        title={isFailed ? 'AI 분석 실패' : isComplete ? 'AI 분석 완료' : 'AI 분석 진행 중'}
        description={
          isFailed
            ? '일부 분석 작업이 계속 실패했어요. 다시 시도해 주세요.'
            : isComplete
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

      {(progress?.failedDocumentTitles.length ?? 0) > 0 && (
        <p className="flex items-start gap-2 rounded-lg bg-warning-soft px-3 py-2.5 text-[12.5px] font-semibold text-warning">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>
            {progress!.failedDocumentTitles.length}개 문서를 처리하지 못해 분석에서 제외했어요:{' '}
            {progress!.failedDocumentTitles.join(', ')}
          </span>
        </p>
      )}

      <Card className="overflow-hidden">
        <div className="brand-gradient h-1 w-full" />
        <div className="flex flex-col items-center px-5 py-10 sm:px-10">
          {isFailed ? (
            <>
              <span className="flex size-20 items-center justify-center rounded-full bg-danger-soft text-danger">
                <AlertTriangle className="size-9" />
              </span>
              <p className="mt-5 text-[19px] font-extrabold tracking-tight text-ink">
                분석 중 오류가 발생했어요
              </p>
              <p className="mt-1.5 max-w-md text-center text-[13.5px] text-ink-muted">
                일부 문서 분석이 반복적으로 실패했습니다. 다시 시도하거나, 문제가 되는 문서를
                제외하고 진행해 주세요.
              </p>
              <Button
                className="mt-6"
                variant="gradient"
                disabled={retryAnalysis.isPending}
                onClick={() => void retryAnalysis.mutateAsync()}
              >
                다시 시도
              </Button>
            </>
          ) : unexpectedErrorMessage ? (
            <>
              <span className="flex size-20 items-center justify-center rounded-full bg-danger-soft text-danger">
                <AlertTriangle className="size-9" />
              </span>
              <p className="mt-5 text-[19px] font-extrabold tracking-tight text-ink">
                분석 상태를 확인하지 못했어요
              </p>
              <p className="mt-1.5 max-w-md text-center text-[13.5px] text-ink-muted">
                {unexpectedErrorMessage}
              </p>
              <Button className="mt-6" variant="outline" onClick={() => void refetch()}>
                다시 확인
              </Button>
            </>
          ) : (
            <>
              <CircularProgress value={percent} size={200} strokeWidth={14} glow={!isComplete} tone="primary">
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
                        {percent}%
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
                    {isComplete ? '분석 결과 페이지에서 자세히 확인할 수 있어요.' : currentStep.caption}
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
                    <Link to={`/projects/${projectId}/analysis/result`}>
                      분석 결과 보기
                      <ArrowRight />
                    </Link>
                  </Button>
                </motion.div>
              )}

              <div className="mt-10 w-full max-w-3xl">
                <AnalysisStepper
                  stepStates={stepStates}
                  orientation={isMobile ? 'vertical' : 'horizontal'}
                />
              </div>
            </>
          )}
        </div>
      </Card>

      <SectionCard title="분석 정보">
        <dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <InfoTile icon={FileText} label="프로젝트" value={project?.name ?? '—'} />
          <InfoTile icon={Sparkles} label="분석 문서 수" value={`${documentCount}개`} />
          <InfoTile
            icon={Clock}
            label="경과 시간"
            value={isComplete ? '완료됨' : formatDuration(elapsedSeconds)}
          />
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
