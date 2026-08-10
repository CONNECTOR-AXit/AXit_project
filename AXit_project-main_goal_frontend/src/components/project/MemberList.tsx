import { Crown, Eye, MoreHorizontal, ShieldCheck, UserMinus, type LucideIcon } from 'lucide-react'

import { UserAvatar } from '@/components/common/UserAvatar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useAuth } from '@/hooks/useAuth'
import { cn } from '@/lib/utils'
import type { MemberRole, ProjectMember } from '@/types'

/** 권한별 아이콘과 색. 라벨은 members.ts 의 roleLabel 과 짝을 이룹니다. */
const roleMeta: Record<MemberRole, { label: string; icon: LucideIcon; className: string }> = {
  owner: { label: '관리자', icon: Crown, className: 'text-warning' },
  editor: { label: '편집자', icon: ShieldCheck, className: 'text-primary' },
  viewer: { label: '뷰어', icon: Eye, className: 'text-ink-subtle' },
}

export interface MemberListProps {
  members: ProjectMember[]
  className?: string
}

/** 참여 멤버 목록. 권한은 아이콘과 텍스트를 함께 표시합니다. */
export function MemberList({ members, className }: MemberListProps) {
  const { user } = useAuth()
  return (
    <ul className={cn('divide-y divide-line-soft', className)}>
      {members.map((member) => {
        const meta = roleMeta[member.role]
        return (
          <li key={member.id} className="group flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
            <UserAvatar user={member} size="sm" />

            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-bold text-ink">
                {member.name}
                {member.id === user?.id && (
                  <span className="ml-1 text-[11px] font-semibold text-ink-subtle">(나)</span>
                )}
              </p>
              <p className="truncate text-[11.5px] text-ink-subtle">{member.email}</p>
            </div>

            <span
              className={cn(
                'flex shrink-0 items-center gap-1 text-[12px] font-semibold',
                meta.className,
              )}
            >
              <meta.icon className="size-3.5" />
              {meta.label}
            </span>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
                  aria-label={`${member.name} 권한 메뉴`}
                >
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuLabel>권한 변경</DropdownMenuLabel>
                <DropdownMenuItem>
                  <ShieldCheck />
                  편집자로 변경
                </DropdownMenuItem>
                <DropdownMenuItem>
                  <Eye />
                  뷰어로 변경
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="danger">
                  <UserMinus />
                  프로젝트에서 제외
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </li>
        )
      })}
    </ul>
  )
}

export { roleMeta }
