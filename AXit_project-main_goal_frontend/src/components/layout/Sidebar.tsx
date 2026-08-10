import { motion } from 'framer-motion'
import { ChevronsLeft, ChevronsRight, LogOut, UserRound } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'

import { useNotifications } from '@/api/queries'
import { Logo } from '@/components/common/Logo'
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
import { Tooltip } from '@/components/ui/tooltip'
import { useAuth } from '@/hooks/useAuth'
import { cn } from '@/lib/utils'
import { isActive, primaryNav, secondaryNav, type NavItem } from './navigation'

export interface SidebarProps {
  collapsed: boolean
  onToggleCollapse: () => void
  /** 이동 후 호출. 모바일 드로어가 스스로 닫히도록 합니다. */
  onNavigate?: () => void
}

/** 좌측 고정 사이드바. 데스크톱에서 248px ↔ 76px 로 접고 펼칩니다. */
export function Sidebar({ collapsed, onToggleCollapse, onNavigate }: SidebarProps) {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const { data: notificationFeed } = useNotifications()
  const unreadCount = notificationFeed?.unreadCount ?? 0
  const [hovering, setHovering] = useState(false)

  const handleLogout = () => {
    logout()
    onNavigate?.()
    navigate('/landing')
  }

  return (
    <aside
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
      className={cn(
        'flex h-full flex-col border-r border-line bg-white transition-[width] duration-300 ease-out',
        collapsed ? 'w-[76px]' : 'w-[248px]',
      )}
    >
      {/* 브랜드 — 홈으로 이동합니다. 접힌 상태에서 마우스를 올리면 펼치기
          버튼으로 바뀝니다. */}
      <div
        className={cn(
          'flex h-16 shrink-0 items-center border-b border-line',
          collapsed ? 'justify-center px-3' : 'justify-between px-5',
        )}
      >
        {collapsed && hovering ? (
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onToggleCollapse}
            aria-label="사이드바 펼치기"
          >
            <ChevronsRight />
          </Button>
        ) : (
          <Link
            to="/"
            onClick={onNavigate}
            aria-label="AXit 홈으로 이동"
            className="rounded-lg focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-primary/25"
          >
            <Logo compact={collapsed} />
          </Link>
        )}
        {!collapsed && (
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onToggleCollapse}
            className="hidden lg:inline-flex"
            aria-label="사이드바 접기"
          >
            <ChevronsLeft />
          </Button>
        )}
      </div>

      {/* 메뉴 */}
      <nav className="scrollbar-none flex-1 space-y-1 overflow-y-auto px-3 py-4">
        {!collapsed && (
          <p className="px-3 pt-1 pb-2 text-[11px] font-bold tracking-wider text-ink-subtle">
            워크스페이스
          </p>
        )}
        {primaryNav.map((item) => (
          <SidebarLink
            key={item.to}
            item={item.to === '/notifications' ? { ...item, badge: unreadCount } : item}
            collapsed={collapsed}
            active={isActive(item, pathname)}
            onNavigate={onNavigate}
          />
        ))}

        <div className="!my-3 h-px bg-line" />

        {secondaryNav.map((item) => (
          <SidebarLink
            key={item.to}
            item={item}
            collapsed={collapsed}
            active={isActive(item, pathname)}
            onNavigate={onNavigate}
          />
        ))}
      </nav>

      {/* 계정 */}
      <div className={cn('border-t border-line p-3', collapsed && 'flex justify-center')}>
        {collapsed ? (
          <Tooltip label={user?.name ?? '내 계정'} side="right">
            <button type="button" className="rounded-full">
              {user && <UserAvatar user={user} size="sm" />}
            </button>
          </Tooltip>
        ) : (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="flex w-full items-center gap-2.5 rounded-lg p-2 text-left transition-colors hover:bg-line-soft"
              >
                {user && <UserAvatar user={user} size="sm" />}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-bold text-ink">
                    {user?.name}
                  </span>
                  <span className="block truncate text-[11px] text-ink-subtle">
                    {user?.email}
                  </span>
                </span>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side="top" className="w-[218px]">
              <DropdownMenuLabel>내 계정</DropdownMenuLabel>
              <DropdownMenuItem>
                <UserRound />
                프로필 설정
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="danger" onSelect={handleLogout}>
                <LogOut />
                로그아웃
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </aside>
  )
}

interface SidebarLinkProps {
  item: NavItem
  collapsed: boolean
  active: boolean
  onNavigate?: () => void
}

function SidebarLink({ item, collapsed, active, onNavigate }: SidebarLinkProps) {
  const { icon: Icon, label, badge } = item

  const link = (
    <NavLink
      to={item.to}
      onClick={onNavigate}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'group relative flex h-10 items-center gap-3 rounded-lg px-3 text-[13.5px] font-semibold transition-colors',
        collapsed && 'justify-center px-0',
        active ? 'bg-primary-50 text-primary' : 'text-ink-muted hover:bg-line-soft hover:text-ink',
      )}
    >
      {/* layoutId 로 활성 표시가 메뉴 사이를 미끄러지듯 이동합니다. */}
      {active && (
        <motion.span
          layoutId="sidebar-active"
          className="absolute top-1/2 left-0 h-5 w-1 -translate-y-1/2 rounded-r-full bg-primary"
          transition={{ type: 'spring', stiffness: 400, damping: 32 }}
        />
      )}
      <Icon className={cn('size-[18px] shrink-0', active && 'text-primary')} strokeWidth={2} />
      {!collapsed && <span className="flex-1 truncate">{label}</span>}
      {!collapsed && badge !== undefined && badge > 0 && (
        <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-danger px-1.5 text-[10px] font-bold text-white">
          {badge}
        </span>
      )}
      {/* 접힌 상태에서는 숫자 대신 점으로 표시 */}
      {collapsed && badge !== undefined && badge > 0 && (
        <span className="absolute top-1.5 right-3 size-2 rounded-full bg-danger ring-2 ring-white" />
      )}
    </NavLink>
  )

  return collapsed ? (
    <Tooltip label={label} side="right">
      {link}
    </Tooltip>
  ) : (
    link
  )
}
