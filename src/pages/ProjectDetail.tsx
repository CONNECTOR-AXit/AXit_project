import {
  Download,
  FileText,
  MoreHorizontal,
  Pencil,
  Settings2,
  Share2,
  Sparkles,
  Trash2,
  Upload,
  UserPlus,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'

import { useProject } from '@/api/queries'
import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { ProjectStatusBadge } from '@/components/common/StatusBadge'
import { PageTransition } from '@/components/layout/PageTransition'
import { ActivityFeed } from '@/components/project/ActivityFeed'
import { DocumentTable } from '@/components/project/DocumentTable'
import { MemberList } from '@/components/project/MemberList'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatDate, formatDateTime } from '@/lib/format'

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>()
  const { data, isLoading, isError } = useProject(projectId)

  // 없는 프로젝트는 목록으로 돌려보냅니다.
  if (isError) return <Navigate to="/projects" replace />

  if (isLoading || !data) {
    return (
      <PageTransition className="space-y-6">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-10 w-full max-w-md" />
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
          <Skeleton className="h-[320px] rounded-xl" />
          <Skeleton className="h-[320px] rounded-xl" />
        </div>
      </PageTransition>
    )
  }

  const { project, documents, activities } = data

  return (
    <PageTransition className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: '프로젝트', to: '/projects' }, { label: project.name }]}
        title={
          <span className="flex items-center gap-2">
            {project.name}
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="프로젝트 이름 수정"
              className="shrink-0 text-ink-subtle"
            >
              <Pencil className="size-3.5" />
            </Button>
          </span>
        }
        actions={
          <>
            <Button asChild variant="gradient">
              <Link to={`/projects/${project.id}/analysis`}>
                <Sparkles />
                AI 분석 시작
              </Link>
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label="프로젝트 메뉴">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem>
                  <Share2 />
                  공유하기
                </DropdownMenuItem>
                <DropdownMenuItem>
                  <Download />
                  전체 다운로드
                </DropdownMenuItem>
                <DropdownMenuItem>
                  <Settings2 />
                  프로젝트 설정
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="danger">
                  <Trash2 />
                  프로젝트 삭제
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        }
      />

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">개요</TabsTrigger>
          <TabsTrigger value="documents">문서</TabsTrigger>
          <TabsTrigger value="members">멤버</TabsTrigger>
          <TabsTrigger value="settings">설정</TabsTrigger>
        </TabsList>

        {/* ── 개요 ─────────────────────────────────────────── */}
        <TabsContent value="overview" className="space-y-5">
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
            <SectionCard title="프로젝트 개요" description={project.description}>
              <dl className="divide-y divide-line-soft">
                <InfoRow label="상태">
                  <ProjectStatusBadge status={project.status} />
                </InfoRow>
                <InfoRow label="생성일">{formatDate(project.createdAt)}</InfoRow>
                <InfoRow label="최근 업데이트">{formatDateTime(project.updatedAt)}</InfoRow>
                <InfoRow label="문서 수">{project.documentCount}개</InfoRow>
                <InfoRow label="멤버 수">{project.memberCount}명</InfoRow>
              </dl>

              <div className="mt-5 rounded-xl border border-line bg-line-soft/50 p-4">
                <div className="flex items-baseline justify-between">
                  <span className="text-[12.5px] font-bold text-ink">통합 완료율</span>
                  <span className="text-[18px] font-extrabold text-ink tabular-nums">
                    {project.progress}%
                  </span>
                </div>
                <Progress value={project.progress} tone="gradient" className="mt-2.5 h-2" />
                <p className="mt-2 text-[11.5px] text-ink-subtle">
                  {project.progress >= 100
                    ? '통합 문서가 완성되었습니다.'
                    : '남은 문서를 업로드하면 통합이 완료됩니다.'}
                </p>
              </div>
            </SectionCard>

            <SectionCard
              title="참여 멤버"
              action={
                <Button variant="ghost" size="sm" className="-mt-1 -mr-2 text-primary">
                  <UserPlus />
                  멤버 초대
                </Button>
              }
            >
              <MemberList members={project.members} />
            </SectionCard>
          </div>

          <SectionCard title="최근 활동" description="프로젝트에서 일어난 변화입니다.">
            {activities.length > 0 ? (
              <ActivityFeed activities={activities} />
            ) : (
              <p className="py-6 text-center text-[13px] text-ink-muted">
                아직 기록된 활동이 없습니다.
              </p>
            )}
          </SectionCard>

          <SectionCard
            title="업로드된 문서"
            description={`총 ${documents.length}개의 문서가 이 프로젝트에 있습니다.`}
            action={
              <Button asChild variant="outline" size="sm" className="-mt-1">
                <Link to="/upload">
                  <Upload />
                  문서 추가
                </Link>
              </Button>
            }
            contentClassName="px-2 pb-3"
          >
            {documents.length > 0 ? (
              <DocumentTable documents={documents} />
            ) : (
              <NoDocuments />
            )}
          </SectionCard>
        </TabsContent>

        {/* ── 문서 ─────────────────────────────────────────── */}
        <TabsContent value="documents">
          <Card className="px-2 py-3">
            {documents.length > 0 ? <DocumentTable documents={documents} /> : <NoDocuments />}
          </Card>
        </TabsContent>

        {/* ── 멤버 ─────────────────────────────────────────── */}
        <TabsContent value="members">
          <SectionCard
            title={`참여 멤버 ${project.members.length}명`}
            description="권한별로 문서 열람 및 편집 범위가 달라집니다."
            action={
              <Button variant="primary" size="sm" className="-mt-1">
                <UserPlus />
                멤버 초대
              </Button>
            }
          >
            <MemberList members={project.members} />
          </SectionCard>
        </TabsContent>

        {/* ── 설정 ─────────────────────────────────────────── */}
        <TabsContent value="settings" className="space-y-5">
          <SectionCard title="프로젝트 정보" description="이름과 설명을 변경할 수 있습니다.">
            <dl className="divide-y divide-line-soft">
              <InfoRow label="프로젝트 ID">
                <code className="rounded bg-line-soft px-1.5 py-0.5 font-mono text-[12px]">
                  {project.id}
                </code>
              </InfoRow>
              <InfoRow label="공개 범위">초대한 멤버만</InfoRow>
              <InfoRow label="자동 분석">업로드 후 자동 시작</InfoRow>
            </dl>
          </SectionCard>

          <Card className="border-danger/25 p-5">
            <h3 className="text-[14px] font-bold text-danger">프로젝트 삭제</h3>
            <p className="mt-1.5 text-[13px] leading-5 text-ink-muted">
              삭제하면 업로드된 문서와 생성된 통합 문서가 모두 사라집니다. 이 작업은 되돌릴 수
              없습니다.
            </p>
            <Button variant="danger" size="sm" className="mt-4">
              <Trash2 />
              프로젝트 삭제
            </Button>
          </Card>
        </TabsContent>
      </Tabs>
    </PageTransition>
  )
}

function NoDocuments() {
  return (
    <EmptyState
      icon={FileText}
      title="업로드된 문서가 없어요"
      description="통합할 문서를 2개 이상 업로드하면 AI 분석을 시작할 수 있어요."
      action={
        <Button asChild variant="primary">
          <Link to="/upload">
            <Upload />
            문서 업로드
          </Link>
        </Button>
      }
      className="border-0 bg-transparent"
    />
  )
}

function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5 first:pt-0 last:pb-0">
      <dt className="shrink-0 text-[12.5px] font-medium text-ink-muted">{label}</dt>
      <dd className="min-w-0 truncate text-[13px] font-semibold text-ink">{children}</dd>
    </div>
  )
}
