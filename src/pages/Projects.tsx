import { motion } from 'framer-motion'
import { FolderOpen } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { useProjects } from '@/api/queries'
import { MiniRing } from '@/components/common/CircularProgress'
import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { ProjectStatusBadge } from '@/components/common/StatusBadge'
import { AvatarGroup } from '@/components/common/UserAvatar'
import { PageTransition, staggerContainer, staggerItem } from '@/components/layout/PageTransition'
import { NewProjectDialog } from '@/components/project/NewProjectDialog'
import { ProjectCard } from '@/components/project/ProjectCard'
import { ProjectToolbar } from '@/components/project/ProjectToolbar'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate } from '@/lib/format'
import type { Project, ProjectSortKey, ProjectStatusFilter, ProjectViewMode } from '@/types'

export default function Projects() {
  const [searchParams, setSearchParams] = useSearchParams()
  // 헤더 검색에서 넘어온 ?q= 값을 초기값으로 받습니다.
  const [search, setSearch] = useState(searchParams.get('q') ?? '')
  const [sort, setSort] = useState<ProjectSortKey>('recent')
  const [status, setStatus] = useState<ProjectStatusFilter>('all')
  const [view, setView] = useState<ProjectViewMode>('grid')

  const { data: projects, isLoading } = useProjects({ search, sort, status })

  // 검색어를 URL 에 반영해 새로고침이나 공유에도 조건이 유지됩니다.
  useEffect(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (search) next.set('q', search)
        else next.delete('q')
        return next
      },
      { replace: true },
    )
  }, [search, setSearchParams])

  const hasFilters = Boolean(search) || status !== 'all'
  const showSkeleton = isLoading && !projects

  return (
    <PageTransition className="space-y-6">
      <PageHeader
        title="프로젝트"
        description="모든 문서 통합 프로젝트를 관리하세요."
        actions={<NewProjectDialog />}
      />

      <ProjectToolbar
        search={search}
        onSearchChange={setSearch}
        sort={sort}
        onSortChange={setSort}
        status={status}
        onStatusChange={setStatus}
        view={view}
        onViewChange={setView}
      />

      {showSkeleton ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-[228px] rounded-xl" />
          ))}
        </div>
      ) : !projects || projects.length === 0 ? (
        <EmptyState
          icon={FolderOpen}
          title={hasFilters ? '조건에 맞는 프로젝트가 없어요' : '아직 프로젝트가 없어요'}
          description={
            hasFilters
              ? '검색어나 필터를 바꿔서 다시 찾아보세요.'
              : '첫 프로젝트를 만들고 통합할 문서를 업로드해보세요.'
          }
          action={
            hasFilters ? (
              <Button
                variant="outline"
                onClick={() => {
                  setSearch('')
                  setStatus('all')
                }}
              >
                필터 초기화
              </Button>
            ) : (
              <NewProjectDialog />
            )
          }
        />
      ) : (
        <>
          {/* key 를 바꿔 보기 전환 시 stagger 애니메이션이 다시 실행됩니다. */}
          <motion.div
            key={view}
            variants={staggerContainer}
            initial="hidden"
            animate="show"
            className={
              view === 'grid' ? 'grid gap-4 md:grid-cols-2 xl:grid-cols-3' : 'space-y-2'
            }
          >
            {projects.map((project) =>
              view === 'grid' ? (
                <ProjectCard key={project.id} project={project} />
              ) : (
                <ProjectRow key={project.id} project={project} />
              ),
            )}
          </motion.div>

          <p className="text-center text-[12px] text-ink-subtle">
            총 {projects.length}개의 프로젝트를 표시하고 있어요.
          </p>
        </>
      )}
    </PageTransition>
  )
}

/** 목록 보기용 한 줄 행. */
function ProjectRow({ project }: { project: Project }) {
  return (
    <motion.div variants={staggerItem}>
      <Card className="transition-all duration-200 hover:border-primary-200 hover:shadow-lift">
        <Link
          to={`/projects/${project.id}`}
          className="flex flex-wrap items-center gap-4 px-5 py-4 focus-visible:ring-[3px] focus-visible:ring-primary/25 focus-visible:outline-none"
        >
          <div className="min-w-[200px] flex-1">
            <p className="truncate text-[14px] font-bold text-ink">{project.name}</p>
            <p className="mt-0.5 truncate text-[12px] text-ink-subtle">
              생성일 {formatDate(project.createdAt)} · 문서 {project.documentCount}개 · 멤버{' '}
              {project.memberCount}명
            </p>
          </div>
          <ProjectStatusBadge status={project.status} />
          <AvatarGroup users={project.members} max={4} size="xs" />
          <MiniRing value={project.progress} complete={project.progress >= 100} />
        </Link>
      </Card>
    </motion.div>
  )
}
