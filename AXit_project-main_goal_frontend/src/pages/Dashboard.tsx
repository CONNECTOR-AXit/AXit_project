import { motion } from 'framer-motion'
import {
  AlertCircle,
  ArrowRight,
  FileCheck2,
  FileText,
  FolderKanban,
  Plus,
  RefreshCw,
  Sparkles,
} from 'lucide-react'
import { Link } from 'react-router-dom'

import { useDashboard } from '@/api/queries'
import { ChartLegend } from '@/components/charts/ChartTooltip'
import { SERIES_MERGED, SERIES_UPLOADED } from '@/components/charts/palette'
import { ProjectCompletionBarChart } from '@/components/charts/ProjectCompletionBarChart'
import { TrendAreaChart } from '@/components/charts/TrendAreaChart'
import { PageHeader } from '@/components/common/PageHeader'
import { EmptyState } from '@/components/common/EmptyState'
import { SectionCard } from '@/components/common/SectionCard'
import { AiProgressPanel } from '@/components/dashboard/AiProgressPanel'
import { KpiCard } from '@/components/dashboard/KpiCard'
import { MergedDocumentList } from '@/components/dashboard/MergedDocumentList'
import { PageTransition, staggerContainer } from '@/components/layout/PageTransition'
import { ActivityFeed } from '@/components/project/ActivityFeed'
import { NewProjectDialog } from '@/components/project/NewProjectDialog'
import { ProjectCard } from '@/components/project/ProjectCard'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/hooks/useAuth'

export default function Dashboard() {
  const { data, isLoading, isError, isFetching, refetch } = useDashboard()
  const { user } = useAuth()
  const pending = isLoading || !data

  if (isError && !data) {
    return (
      <PageTransition className="space-y-6">
        <PageHeader
          title={`안녕하세요, ${user?.name ?? '사용자'}님 👋`}
          description="오늘의 문서 통합 현황을 한눈에 확인하세요."
        />
        <EmptyState
          icon={AlertCircle}
          title="대시보드 정보를 불러오지 못했어요"
          description="연결 상태를 확인한 뒤 다시 시도해주세요."
          action={
            <Button variant="primary" onClick={() => void refetch()} disabled={isFetching}>
              <RefreshCw className={isFetching ? 'animate-spin' : undefined} />
              {isFetching ? '다시 불러오는 중...' : '다시 불러오기'}
            </Button>
          }
        />
      </PageTransition>
    )
  }

  return (
    <PageTransition className="space-y-6">
      <PageHeader
        title={`안녕하세요, ${user?.name ?? '사용자'}님 👋`}
        description="오늘의 문서 통합 현황을 한눈에 확인하세요."
        actions={
          <>
            <NewProjectDialog
              trigger={
                <Button variant="outline">
                  <Plus />
                  새 프로젝트
                </Button>
              }
            />
            <Button asChild variant="gradient">
              <Link to="/projects">
                <Sparkles />
                프로젝트 보기
              </Link>
            </Button>
          </>
        }
      />

      {/* ── 상단 KPI ─────────────────────────────────────── */}
      {pending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-[148px] rounded-xl" />
          ))}
        </div>
      ) : (
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
        >
          <KpiCard
            label="전체 프로젝트"
            value={data.stats.projects.value}
            delta={data.stats.projects.delta}
            icon={FolderKanban}
            tone="primary"
            caption="현재 등록된 프로젝트 기준"
          />
          <KpiCard
            label="업로드 문서"
            value={data.stats.documents.value}
            delta={data.stats.documents.delta}
            icon={FileText}
            tone="mint"
            caption="현재 처리된 문서 기준"
          />
          <KpiCard
            label="AI 분석 완료"
            value={data.stats.analyses.value}
            delta={data.stats.analyses.delta}
            icon={Sparkles}
            tone="violet"
            unit="건"
            caption="완료된 분석 기준"
          />
          <KpiCard
            label="통합 문서"
            value={data.stats.merged.value}
            delta={data.stats.merged.delta}
            icon={FileCheck2}
            tone="amber"
            caption="생성된 통합 문서 기준"
          />
        </motion.div>
      )}

      {/* ── 추이 차트 + AI 진행 현황 ─────────────────────── */}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <SectionCard
          title="문서 처리 현황"
          description="현재 등록된 자료의 업로드·통합 분포입니다."
          action={
            <ChartLegend
              items={[
                { label: '업로드', color: SERIES_UPLOADED },
                { label: '통합', color: SERIES_MERGED },
              ]}
            />
          }
        >
          {pending ? (
            <Skeleton className="h-[45vh] max-h-[560px] min-h-[260px] w-full" />
          ) : (
            <TrendAreaChart data={data.trend} />
          )}
        </SectionCard>

        <SectionCard
          title="AI 진행 현황"
          description="분석이 진행 중인 프로젝트입니다."
          contentClassName="pb-4"
        >
          {pending ? (
            <div className="space-y-4">
              {Array.from({ length: 3 }).map((_, index) => (
                <Skeleton key={index} className="h-14" />
              ))}
            </div>
          ) : (
            <AiProgressPanel projects={data.runningProjects} credit={data.aiCredit} />
          )}
        </SectionCard>
      </div>

      {/* ── 최근 프로젝트 + 활동 · 요일별 처리량 ─────────── */}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <SectionCard
          title="최근 프로젝트"
          description="가장 최근에 업데이트된 프로젝트입니다."
          action={
            <Button asChild variant="ghost" size="sm" className="-mt-1 -mr-2">
              <Link to="/projects">
                전체 보기
                <ArrowRight />
              </Link>
            </Button>
          }
        >
          {pending ? (
            <div className="grid gap-4 md:grid-cols-2">
              {Array.from({ length: 4 }).map((_, index) => (
                <Skeleton key={index} className="h-[228px] rounded-xl" />
              ))}
            </div>
          ) : data.recentProjects.length > 0 ? (
            <motion.div
              variants={staggerContainer}
              initial="hidden"
              animate="show"
              className="grid gap-4 md:grid-cols-2"
            >
              {data.recentProjects.map((project) => (
                <ProjectCard key={project.id} project={project} />
              ))}
            </motion.div>
          ) : (
            <EmptyState
              icon={FolderKanban}
              title="아직 프로젝트가 없어요"
              description="프로젝트를 만들고 문서를 업로드하면 여기에 표시됩니다."
              action={
                <Button asChild variant="primary" size="sm">
                  <Link to="/projects">프로젝트 만들기</Link>
                </Button>
              }
              className="py-10"
            />
          )}
        </SectionCard>

        <div className="space-y-5">
          <SectionCard title="최근 활동">
            {pending ? (
              <div className="space-y-3">
                {Array.from({ length: 4 }).map((_, index) => (
                  <Skeleton key={index} className="h-11" />
                ))}
              </div>
            ) : data.activities.length > 0 ? (
              <ActivityFeed activities={data.activities} />
            ) : (
              <EmptyState
                icon={Sparkles}
                title="아직 활동이 없어요"
                description="프로젝트 활동이 생기면 여기에 표시됩니다."
                className="border-0 py-8"
              />
            )}
          </SectionCard>

          <SectionCard
            title="프로젝트 통합 완료율"
            description="프로젝트 최종 수정 요일별 평균 통합 완료율입니다."
          >
            {pending ? (
              <Skeleton className="h-[200px]" />
            ) : data.projectCompletionByWeekday.some((point) => point.projects > 0) ? (
              <ProjectCompletionBarChart data={data.projectCompletionByWeekday} />
            ) : (
              <p className="py-8 text-center text-[12.5px] text-ink-subtle">
                표시할 프로젝트가 없습니다.
              </p>
            )}
          </SectionCard>
        </div>
      </div>

      {/* ── 최근 생성된 통합 문서 ────────────────────────── */}
      <SectionCard
        title="최근 생성된 통합 문서"
        description="AI가 여러 문서를 하나로 합쳐 만든 결과물입니다."
        action={
          <Button asChild variant="ghost" size="sm" className="-mt-1 -mr-2">
            <Link to="/documents">
              전체 보기
              <ArrowRight />
            </Link>
          </Button>
        }
      >
        {pending ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-[104px] rounded-xl" />
            ))}
          </div>
        ) : data.mergedDocuments.length > 0 ? (
          <MergedDocumentList documents={data.mergedDocuments} />
        ) : (
          <EmptyState
            icon={FileCheck2}
            title="아직 통합 문서가 없어요"
            description="AI 분석이 완료되면 생성된 통합 문서가 여기에 표시됩니다."
            className="py-10"
          />
        )}
      </SectionCard>
    </PageTransition>
  )
}
