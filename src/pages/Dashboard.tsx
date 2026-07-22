import { motion } from 'framer-motion'
import { ArrowRight, FileCheck2, FileText, FolderKanban, Sparkles, Upload } from 'lucide-react'
import { Link } from 'react-router-dom'

import { useDashboard } from '@/api/queries'
import { ChartLegend } from '@/components/charts/ChartTooltip'
import { SERIES_MERGED, SERIES_UPLOADED } from '@/components/charts/palette'
import { TrendAreaChart } from '@/components/charts/TrendAreaChart'
import { WeeklyBarChart } from '@/components/charts/WeeklyBarChart'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { AiProgressPanel } from '@/components/dashboard/AiProgressPanel'
import { KpiCard } from '@/components/dashboard/KpiCard'
import { MergedDocumentList } from '@/components/dashboard/MergedDocumentList'
import { PageTransition, staggerContainer } from '@/components/layout/PageTransition'
import { ActivityFeed } from '@/components/project/ActivityFeed'
import { ProjectCard } from '@/components/project/ProjectCard'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { DEMO_NOW } from '@/data/dashboard'
import { currentUser } from '@/data/user'

export default function Dashboard() {
  const { data, isLoading } = useDashboard()
  const pending = isLoading || !data

  return (
    <PageTransition className="space-y-6">
      <PageHeader
        title={`안녕하세요, ${currentUser.name}님 👋`}
        description="오늘의 문서 통합 현황을 한눈에 확인하세요."
        actions={
          <>
            <Button asChild variant="outline">
              <Link to="/upload">
                <Upload />
                문서 업로드
              </Link>
            </Button>
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
            caption="이번 달 신규 2개"
          />
          <KpiCard
            label="업로드 문서"
            value={data.stats.documents.value}
            delta={data.stats.documents.delta}
            icon={FileText}
            tone="mint"
            caption="총 용량 3.2GB"
          />
          <KpiCard
            label="AI 분석 완료"
            value={data.stats.analyses.value}
            delta={data.stats.analyses.delta}
            icon={Sparkles}
            tone="violet"
            unit="건"
            caption="평균 소요 2분 12초"
          />
          <KpiCard
            label="통합 문서"
            value={data.stats.merged.value}
            delta={data.stats.merged.delta}
            icon={FileCheck2}
            tone="amber"
            caption="이번 주 4개 생성"
          />
        </motion.div>
      )}

      {/* ── 추이 차트 + AI 진행 현황 ─────────────────────── */}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <SectionCard
          title="문서 통합 추이"
          description="월별 업로드 문서와 생성된 통합 문서 수입니다."
          action={
            <ChartLegend
              items={[
                { label: '업로드', color: SERIES_UPLOADED },
                { label: '통합', color: SERIES_MERGED },
              ]}
            />
          }
        >
          {pending ? <Skeleton className="h-[260px]" /> : <TrendAreaChart data={data.trend} />}
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
          ) : (
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
            ) : (
              <ActivityFeed activities={data.activities} />
            )}
          </SectionCard>

          <SectionCard
            title="요일별 처리량"
            description="최근 7일간 AI 분석 · 통합 건수"
            action={
              <ChartLegend
                items={[
                  { label: '분석', color: SERIES_UPLOADED },
                  { label: '통합', color: SERIES_MERGED },
                ]}
              />
            }
          >
            {pending ? (
              <Skeleton className="h-[200px]" />
            ) : (
              <WeeklyBarChart data={data.weeklyActivity} />
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
        ) : (
          <MergedDocumentList documents={data.mergedDocuments} now={DEMO_NOW} />
        )}
      </SectionCard>
    </PageTransition>
  )
}
