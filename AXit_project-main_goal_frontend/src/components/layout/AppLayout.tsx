import { AnimatePresence, motion } from 'framer-motion'
import { X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Navigate, Outlet, useLocation, useMatches } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { useIsDesktop } from '@/hooks/useMediaQuery'
import { useAuth } from '@/hooks/useAuth'
import { Header } from './Header'
import { Sidebar } from './Sidebar'

/** 라우트 정의에서 handle 로 전달하는 메타데이터. */
export interface RouteHandle {
  title?: string
}

/** 앱 셸 — 좌측 고정 사이드바 + 상단 고정 헤더 + 애니메이션 Outlet. */
export function AppLayout() {
  const { pathname } = useLocation()
  const matches = useMatches()
  const isDesktop = useIsDesktop()
  const [collapsed, setCollapsed] = useState(false)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const { user, isInitializing } = useAuth()

  // 가장 깊은 라우트의 title 을 헤더에 표시합니다.
  const activeMatch = [...matches]
    .reverse()
    .find((match) => (match.handle as RouteHandle | undefined)?.title)
  const title = (activeMatch?.handle as RouteHandle | undefined)?.title ?? 'AXit'

  // 경로가 바뀌거나 데스크톱으로 넘어가면 드로어를 닫습니다.
  useEffect(() => setMobileNavOpen(false), [pathname])
  useEffect(() => {
    if (isDesktop) setMobileNavOpen(false)
  }, [isDesktop])

  // 드로어가 열려 있는 동안 본문 스크롤을 잠급니다.
  useEffect(() => {
    document.body.style.overflow = mobileNavOpen ? 'hidden' : ''
    return () => {
      document.body.style.overflow = ''
    }
  }, [mobileNavOpen])

  if (isInitializing) {
    return <div className="flex min-h-screen items-center justify-center bg-canvas text-sm text-ink-muted">로그인 상태를 확인하는 중입니다.</div>
  }
  if (!user) return <Navigate to="/login" replace state={{ from: pathname }} />

  return (
    <div className="flex min-h-screen bg-canvas">
      {/* 데스크톱 사이드바 */}
      <div className="sticky top-0 hidden h-screen shrink-0 lg:block">
        <Sidebar collapsed={collapsed} onToggleCollapse={() => setCollapsed((v) => !v)} />
      </div>

      {/* 모바일 · 태블릿 드로어 */}
      <AnimatePresence>
        {mobileNavOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              onClick={() => setMobileNavOpen(false)}
              className="fixed inset-0 z-40 bg-ink/30 backdrop-blur-[2px] lg:hidden"
            />
            <motion.div
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ type: 'spring', stiffness: 380, damping: 38 }}
              className="fixed inset-y-0 left-0 z-50 shadow-pop lg:hidden"
            >
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => setMobileNavOpen(false)}
                aria-label="메뉴 닫기"
                className="absolute top-4 -right-11 bg-white shadow-card"
              >
                <X />
              </Button>
              <Sidebar
                collapsed={false}
                onToggleCollapse={() => setMobileNavOpen(false)}
                onNavigate={() => setMobileNavOpen(false)}
              />
            </motion.div>
          </>
        )}
      </AnimatePresence>

      <div className="flex min-w-0 flex-1 flex-col">
        <Header title={title} onOpenMobileNav={() => setMobileNavOpen(true)} />
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <div className="mx-auto w-full max-w-[1440px]">
            {/* key 를 경로로 주어 페이지가 바뀔 때 전환 애니메이션이 실행됩니다. */}
            <AnimatePresence mode="wait">
              <Outlet key={pathname} />
            </AnimatePresence>
          </div>
        </main>
      </div>
    </div>
  )
}
