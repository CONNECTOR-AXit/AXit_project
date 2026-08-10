import { motion } from 'framer-motion'
import { AlertCircle, FolderOpen, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { ApiError } from '@/api/client'
import { useProjectMembershipActions, useProjects } from '@/api/queries'
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate } from '@/lib/format'
import { projectEntryPath } from '@/lib/utils'
import type { Project, ProjectSortKey, ProjectStatusFilter, ProjectViewMode } from '@/types'

export default function Projects() {
  const [searchParams, setSearchParams] = useSearchParams()
  // 헤더 검색에서 넘어온 ?q= 값을 초기값으로 받습니다.
  const [search, setSearch] = useState(searchParams.get('q') ?? '')
  const [sort, setSort] = useState<ProjectSortKey>('recent')
  const [status, setStatus] = useState<ProjectStatusFilter>('all')
  const [view, setView] = useState<ProjectViewMode>('grid')
  const [membershipAction, setMembershipAction] = useState<{
    project: Project
    kind: 'remove' | 'leave'
  } | null>(null)

  const { data: projects, isLoading } = useProjects({ search, sort, status })
  const projectActions = useProjectMembershipActions()

  const openMembershipAction = (project: Project, kind: 'remove' | 'leave') => {
    projectActions.remove.reset()
    projectActions.leave.reset()
    setMembershipAction({ project, kind })
  }

  const confirmMembershipAction = async () => {
    if (!membershipAction) return
    try {
      if (membershipAction.kind === 'remove') {
        await projectActions.remove.mutateAsync(membershipAction.project.id)
      } else {
        await projectActions.leave.mutateAsync(membershipAction.project.roomId)
      }
      setMembershipAction(null)
    } catch {
      // Mutation state renders the normalized API error inside the dialog.
    }
  }

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
              view === 'grid'
                ? 'grid auto-rows-fr gap-4 md:grid-cols-2 xl:grid-cols-3'
                : 'space-y-2'
            }
          >
            {projects.map((project) =>
              view === 'grid' ? (
                <ProjectCard
                  key={project.id}
                  project={project}
                  onRemove={(selected) => openMembershipAction(selected, 'remove')}
                  onLeave={(selected) => openMembershipAction(selected, 'leave')}
                />
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

      <ProjectMembershipActionDialog
        action={membershipAction}
        pending={projectActions.remove.isPending || projectActions.leave.isPending}
        error={projectActions.remove.error ?? projectActions.leave.error}
        onCancel={() => setMembershipAction(null)}
        onConfirm={() => void confirmMembershipAction()}
      />
    </PageTransition>
  )
}

function ProjectMembershipActionDialog({
  action,
  pending,
  error,
  onCancel,
  onConfirm,
}: {
  action: { project: Project; kind: 'remove' | 'leave' } | null
  pending: boolean
  error: Error | null
  onCancel: () => void
  onConfirm: () => void
}) {
  const removing = action?.kind === 'remove'
  const errorMessage = error instanceof ApiError ? error.message : error?.message

  return (
    <Dialog open={Boolean(action)} onOpenChange={(open) => !open && !pending && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{removing ? '프로젝트를 제거할까요?' : '프로젝트에서 탈퇴할까요?'}</DialogTitle>
          <DialogDescription>
            {removing
              ? `'${action?.project.name ?? ''}' 프로젝트가 모든 참여자의 목록에서 제거됩니다. 원본 데이터는 보존됩니다.`
              : `'${action?.project.name ?? ''}' 프로젝트에 더 이상 접근할 수 없게 됩니다.`}
          </DialogDescription>
        </DialogHeader>
        {errorMessage && (
          <p className="flex items-start gap-2 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] font-medium text-danger">
            <AlertCircle className="mt-0.5 size-4 shrink-0" />
            {errorMessage}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={pending}>
            취소
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={pending}>
            {pending && <Loader2 className="animate-spin" />}
            {removing ? '프로젝트 제거하기' : '프로젝트 탈퇴'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** 목록 보기용 한 줄 행. */
function ProjectRow({ project }: { project: Project }) {
  return (
    <motion.div variants={staggerItem}>
      <Card className="transition-all duration-200 hover:shadow-lift">
        <Link
          to={projectEntryPath(project)}
          onClick={() => sessionStorage.setItem('axit:active-project-id', project.id)}
          className="flex flex-wrap items-center gap-4 px-5 py-4 focus-visible:ring-[3px] focus-visible:ring-primary/25 focus-visible:outline-none"
        >
          <div className="min-w-0 flex-1 sm:flex-none sm:basis-[240px]">
            <p className="truncate text-[14px] font-bold text-ink">{project.name}</p>
            <p className="mt-0.5 truncate text-[12px] text-ink-subtle">
              생성일 {formatDate(project.createdAt)} · 문서 {project.documentCount}개 · 멤버{' '}
              {project.memberCount}명
            </p>
          </div>
          <ProjectStatusBadge status={project.status} />
          <AvatarGroup users={project.members} max={4} size="xs" className="ml-auto" />
          <MiniRing value={project.progress} complete={project.progress >= 100} />
        </Link>
      </Card>
    </motion.div>
  )
}
