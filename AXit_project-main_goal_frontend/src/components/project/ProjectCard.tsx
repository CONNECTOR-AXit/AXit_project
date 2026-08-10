import { motion } from 'framer-motion'
import { FileText, Folder, LogOut, MoreHorizontal, Pencil, Share2, Trash2, Users } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Link } from 'react-router-dom'

import { MiniRing } from '@/components/common/CircularProgress'
import { ProjectStatusBadge } from '@/components/common/StatusBadge'
import { AvatarGroup } from '@/components/common/UserAvatar'
import { staggerItem } from '@/components/layout/PageTransition'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { formatDate } from '@/lib/format'
import { cn, projectEntryPath } from '@/lib/utils'
import type { Project } from '@/types'

/** 폴더 글리프 색상. 상태와 무관한 장식 요소라 회색으로 통일합니다. */
const accentClass: Record<Project['accent'], string> = {
  blue: 'bg-line-soft text-ink-muted',
  mint: 'bg-line-soft text-ink-muted',
  amber: 'bg-line-soft text-ink-muted',
  violet: 'bg-line-soft text-ink-muted',
  rose: 'bg-line-soft text-ink-muted',
  slate: 'bg-line-soft text-ink-muted',
}

export interface ProjectCardProps {
  project: Project
  className?: string
  onRemove?: (project: Project) => void
  onLeave?: (project: Project) => void
}

export function ProjectCard({ project, className, onRemove, onLeave }: ProjectCardProps) {
  const complete = project.progress >= 100

  return (
    <motion.div variants={staggerItem} className={className}>
      <Card className="group relative flex h-full flex-col border border-line transition-all duration-200 hover:-translate-y-1 hover:shadow-lift">
        {/*
          카드 전체를 링크로 덮고, 드롭다운 같은 조작 요소는 z-index 로 위에 둡니다.
          중첩 링크가 되지 않으면서 카드 어디를 눌러도 이동합니다.
        */}
        <Link
          to={projectEntryPath(project)}
          onClick={() => sessionStorage.setItem('axit:active-project-id', project.id)}
          className="absolute inset-0 z-20 rounded-xl focus-visible:ring-[3px] focus-visible:ring-primary/25 focus-visible:outline-none"
          aria-label={`${project.name} 프로젝트 열기`}
        />

        <div className="relative flex items-start gap-3 px-5 pt-5">
          <span
            className={cn(
              'flex size-10 shrink-0 items-center justify-center rounded-xl',
              accentClass[project.accent],
            )}
          >
            <Folder className="size-[18px]" strokeWidth={2} />
          </span>

          <div className="min-w-0 flex-1">
            <h3 className="truncate text-[15px] leading-6 font-bold tracking-tight text-ink transition-colors group-hover:text-primary">
              {project.name}
            </h3>
            <p className="mt-0.5 text-[12px] text-ink-subtle">
              생성일 {formatDate(project.createdAt)}
            </p>
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                className="relative z-30 -mt-1 -mr-1 shrink-0 text-ink-subtle"
                aria-label={`${project.name} 메뉴`}
              >
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem>
                <Pencil />
                이름 변경
              </DropdownMenuItem>
              <DropdownMenuItem disabled>
                <Share2 />
                공유 · 범위 외
              </DropdownMenuItem>
              {project.currentUserRole === 'owner' && onRemove ? (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem variant="danger" onSelect={() => onRemove(project)}>
                    <Trash2 />
                    프로젝트 제거하기
                  </DropdownMenuItem>
                </>
              ) : project.currentUserRole === 'member' && onLeave ? (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem variant="danger" onSelect={() => onLeave(project)}>
                    <LogOut />
                    프로젝트 탈퇴
                  </DropdownMenuItem>
                </>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <p className="relative z-10 mt-3 line-clamp-2 px-5 text-[13px] leading-5 text-ink-muted">
          {project.description}
        </p>

        <div className="relative z-10 mt-auto flex items-center gap-2 px-5 pt-4">
          <ProjectStatusBadge status={project.status} />
          <AvatarGroup users={project.members} max={3} size="xs" className="ml-auto" />
        </div>

        <div className="relative z-10 mt-4 flex items-center gap-2 border-t border-line px-5 py-3.5">
          <Meta icon={FileText} label={`문서 ${project.documentCount}개`} />
          <Meta icon={Users} label={`멤버 ${project.memberCount}명`} />
          <span className="ml-auto flex items-center gap-2">
            <span className="hidden text-[11px] font-semibold text-ink-subtle sm:inline">
              통합 완료율
            </span>
            <MiniRing value={project.progress} complete={complete} />
          </span>
        </div>
      </Card>
    </motion.div>
  )
}

function Meta({ icon: Icon, label }: { icon: LucideIcon; label: string }) {
  return (
    <span className="flex items-center gap-1.5 rounded-md bg-line-soft px-2 py-1 text-[11.5px] font-semibold text-ink-muted">
      <Icon className="size-3.5 text-ink-subtle" />
      {label}
    </span>
  )
}
