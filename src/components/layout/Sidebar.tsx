import { AnimatePresence, motion } from 'framer-motion'
import { ChevronsLeft, ChevronsRight, LogOut, Sparkles, UserRound } from 'lucide-react'
import { Link, NavLink, useLocation } from 'react-router-dom'

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
import { currentUser } from '@/data/user'
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

  return (
    <aside
      className={cn(
        'flex h-full flex-col border-r border-line bg-white transition-[width] duration-300 ease-out',
        collapsed ? 'w-[76px]' : 'w-[248px]',
      )}
    >
      {/* 브랜드 */}
      <div
        className={cn(
          'flex h-16 shrink-0 items-center border-b border-line',
          collapsed ? 'justify-center px-3' : 'justify-between px-5',
        )}
      >
        {/* 브랜드는 네비게이션 항목이 아니므로 Link 를 씁니다.
            NavLink 로 두면 / 경로에서 aria-current=page 가 중복으로 붙습니다. */}
        <Link to="/" onClick={onNavigate} aria-label="AXit 홈">
          <Logo compact={collapsed} />
        </Link>
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
            item={item}
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

      {/* 업그레이드 배너 — 접힌 상태에서는 숨겨 레일을 깔끔하게 유지 */}
      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden px-3"
          >
            <div className="brand-gradient mb-3 rounded-xl p-3.5 text-white">
              <span className="flex items-center gap-1.5 text-[13px] font-bold">
                <Sparkles className="size-3.5" />
                AXit Pro
              </span>
              <p className="mt-1 text-[12px] leading-4 text-white/85">
                무제한 AI 분석과 팀 협업 기능을 사용해보세요.
              </p>
              <Button
                size="sm"
                variant="outline"
                className="mt-2.5 h-7 w-full border-white/0 bg-white/95 text-primary hover:bg-white"
              >
                업그레이드
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 계정 */}
      <div className={cn('border-t border-line p-3', collapsed && 'flex justify-center')}>
        {collapsed ? (
          <div className="flex flex-col items-center gap-2">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onToggleCollapse}
              aria-label="사이드바 펼치기"
            >
              <ChevronsRight />
            </Button>
            <Tooltip label={currentUser.name} side="right">
              <button type="button" className="rounded-full">
                <UserAvatar user={currentUser} size="sm" />
              </button>
            </Tooltip>
          </div>
        ) : (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="flex w-full items-center gap-2.5 rounded-lg p-2 text-left transition-colors hover:bg-line-soft"
              >
                <UserAvatar user={currentUser} size="sm" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-bold text-ink">
                    {currentUser.name}
                  </span>
                  <span className="block truncate text-[11px] text-ink-subtle">
                    {currentUser.email}
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
              <DropdownMenuItem>
                <Sparkles />
                플랜 관리
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="danger">
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
