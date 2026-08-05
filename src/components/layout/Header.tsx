import { Bell, Command, HelpCircle, Menu, Plus, Search } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

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
import { Input } from '@/components/ui/input'
import { Tooltip } from '@/components/ui/tooltip'
import { DEMO_NOW } from '@/data/dashboard'
import { notifications } from '@/data/notifications'
import { currentUser } from '@/data/user'
import { useAuth } from '@/hooks/useAuth'
import { formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'

export interface HeaderProps {
  /** 좌측에 표시할 현재 페이지 제목. 라우트의 handle.title 에서 옵니다. */
  title: string
  onOpenMobileNav: () => void
}

/** 상단 고정 헤더 — 좌측 페이지 제목, 우측 검색 · 알림 · 프로필. */
export function Header({ title, onOpenMobileNav }: HeaderProps) {
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const displayUser = user ?? currentUser
  const [query, setQuery] = useState('')
  const searchRef = useRef<HTMLInputElement>(null)
  const unread = notifications.filter((item) => !item.read)

  const handleLogout = () => {
    logout()
    navigate('/landing')
  }

  // ⌘K / Ctrl+K 로 검색창 포커스 — 이 부류 앱의 관용적인 단축키
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const submitSearch = (event: FormEvent) => {
    event.preventDefault()
    navigate(query.trim() ? `/projects?q=${encodeURIComponent(query.trim())}` : '/projects')
  }

  return (
    <header className="sticky top-0 z-30 flex h-16 shrink-0 items-center gap-3 border-b border-line bg-white/85 px-4 backdrop-blur-md lg:px-8">
      <Button
        variant="ghost"
        size="icon-sm"
        className="lg:hidden"
        onClick={onOpenMobileNav}
        aria-label="메뉴 열기"
      >
        <Menu />
      </Button>

      <h2 className="min-w-0 flex-1 truncate text-[15px] font-bold tracking-tight text-ink lg:flex-none">
        {title}
      </h2>

      {/* 검색 — 모바일에서는 숨기고, 데스크톱에서는 중앙 정렬 */}
      <form onSubmit={submitSearch} className="ml-auto hidden md:block lg:mr-auto lg:ml-8">
        <div className="relative w-[240px] xl:w-[320px]">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-subtle" />
          <Input
            ref={searchRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="프로젝트, 문서 검색"
            className="h-9 pr-16 pl-9"
            aria-label="통합 검색"
          />
          <kbd className="pointer-events-none absolute top-1/2 right-2.5 flex -translate-y-1/2 items-center gap-0.5 rounded bg-white px-1.5 py-0.5 text-[10px] font-bold text-ink-subtle shadow-soft">
            <Command className="size-2.5" />K
          </kbd>
        </div>
      </form>

      <div className="flex shrink-0 items-center gap-1">
        <Button asChild variant="ghost" size="icon-sm" className="hidden sm:inline-flex">
          <Link to="/upload" aria-label="문서 업로드">
            <Plus />
          </Link>
        </Button>

        <Tooltip label="도움말">
          <Button variant="ghost" size="icon-sm" className="hidden sm:inline-flex">
            <HelpCircle />
          </Button>
        </Tooltip>

        {/* 알림 */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" className="relative" aria-label="알림">
              <Bell />
              {unread.length > 0 && (
                <span className="absolute top-1 right-1 size-2 rounded-full bg-danger ring-2 ring-white" />
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-[340px] p-0">
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <span className="text-[13px] font-bold text-ink">알림</span>
              <span className="text-[11px] font-semibold text-primary">
                읽지 않음 {unread.length}
              </span>
            </div>
            <div className="max-h-[320px] overflow-y-auto p-1.5">
              {notifications.slice(0, 4).map((item) => (
                <DropdownMenuItem key={item.id} asChild>
                  <Link to={item.href ?? '/notifications'} className="items-start gap-3">
                    <span
                      className={cn(
                        'mt-1.5 size-1.5 shrink-0 rounded-full',
                        item.read ? 'bg-line' : 'bg-primary',
                      )}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-bold text-ink">
                        {item.title}
                      </span>
                      <span className="mt-0.5 line-clamp-2 block text-[12px] leading-4 text-ink-muted">
                        {item.body}
                      </span>
                      <span className="mt-1 block text-[11px] text-ink-subtle">
                        {formatRelative(item.createdAt, DEMO_NOW)}
                      </span>
                    </span>
                  </Link>
                </DropdownMenuItem>
              ))}
            </div>
            <DropdownMenuSeparator className="mx-0 my-0" />
            <div className="p-1.5">
              <DropdownMenuItem asChild>
                <Link
                  to="/notifications"
                  className="justify-center text-[12px] font-bold text-primary"
                >
                  전체 알림 보기
                </Link>
              </DropdownMenuItem>
            </div>
          </DropdownMenuContent>
        </DropdownMenu>

        {/* 프로필 */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="ml-1 rounded-full outline-none focus-visible:ring-[3px] focus-visible:ring-primary/25"
              aria-label="프로필 메뉴"
            >
              <UserAvatar user={displayUser} size="sm" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-[210px]">
            <DropdownMenuLabel>{displayUser.email}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link to="/settings">계정 설정</Link>
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <Link to="/history">내 활동 기록</Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="danger" onSelect={handleLogout}>
              로그아웃
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
