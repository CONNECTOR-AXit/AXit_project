import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Tooltip } from '@/components/ui/tooltip'
import { initials } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { User } from '@/types'

const sizeClass = {
  xs: 'size-6 text-[10px]',
  sm: 'size-8 text-[11px]',
  md: 'size-9 text-[12px]',
  lg: 'size-11 text-[14px]',
} as const

export type AvatarSize = keyof typeof sizeClass

export interface UserAvatarProps {
  user: Pick<User, 'name' | 'color'>
  size?: AvatarSize
  className?: string
  /** 흰색 링 제거. 겹치지 않는 단독 배치에 사용합니다. */
  ring?: boolean
}

/**
 * 이니셜 아바타.
 * 사용자 색상을 배경(12% 알파)과 글자색으로 함께 사용해
 * 별도 이미지 없이도 사람마다 구분됩니다.
 */
export function UserAvatar({ user, size = 'md', className, ring = true }: UserAvatarProps) {
  return (
    <Avatar className={cn(sizeClass[size], !ring && 'ring-0', className)}>
      <AvatarFallback
        className="font-bold"
        style={{ backgroundColor: `${user.color}1f`, color: user.color }}
      >
        {initials(user.name)}
      </AvatarFallback>
    </Avatar>
  )
}

export interface AvatarGroupProps {
  users: Pick<User, 'id' | 'name' | 'color'>[]
  /** 표시할 최대 인원. 초과분은 +N 으로 묶입니다. */
  max?: number
  size?: AvatarSize
  className?: string
}

/** 겹쳐진 아바타 스택 + `+N` 오버플로 칩. */
export function AvatarGroup({ users, max = 4, size = 'sm', className }: AvatarGroupProps) {
  const shown = users.slice(0, max)
  const overflow = users.length - shown.length

  return (
    <div className={cn('flex items-center -space-x-2', className)}>
      {shown.map((user) => (
        <Tooltip key={user.id} label={user.name}>
          <span className="transition-transform duration-200 hover:z-10 hover:-translate-y-0.5">
            <UserAvatar user={user} size={size} />
          </span>
        </Tooltip>
      ))}
      {overflow > 0 && (
        <span
          className={cn(
            'flex items-center justify-center rounded-full bg-line-soft font-bold text-ink-muted ring-2 ring-white',
            sizeClass[size],
          )}
        >
          +{overflow}
        </span>
      )}
    </div>
  )
}
