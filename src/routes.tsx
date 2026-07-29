import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter } from 'react-router-dom'

import { AppLayout } from '@/components/layout/AppLayout'
import { Skeleton } from '@/components/ui/skeleton'
import NotFound from '@/pages/NotFound'

/* 라우트 단위 코드 스플리팅 — 첫 진입 번들을 작게 유지합니다. */
const Dashboard = lazy(() => import('@/pages/Dashboard'))
const Projects = lazy(() => import('@/pages/Projects'))
const ProjectDetail = lazy(() => import('@/pages/ProjectDetail'))
const Upload = lazy(() => import('@/pages/Upload'))
const Analysis = lazy(() => import('@/pages/Analysis'))
const AnalysisResult = lazy(() => import('@/pages/AnalysisResult'))
const Editor = lazy(() => import('@/pages/Editor'))
const Documents = lazy(() => import('@/pages/Documents'))
const History = lazy(() => import('@/pages/History'))
const Notifications = lazy(() => import('@/pages/Notifications'))
const Pricing = lazy(() => import('@/pages/Pricing'))
const Settings = lazy(() => import('@/pages/Settings'))

/** lazy 페이지를 불러오는 동안 표시되는 스켈레톤. */
function RouteFallback() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-9 w-64" />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-[148px] rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-[320px] rounded-xl" />
    </div>
  )
}

function page(element: ReactNode) {
  return <Suspense fallback={<RouteFallback />}>{element}</Suspense>
}

/**
 * handle.title 은 AppLayout 이 헤더 제목으로 읽어갑니다.
 * 404 는 사이드바 없이 보여야 하므로 레이아웃 밖에 둡니다.
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: page(<Dashboard />), handle: { title: '대시보드' } },
      { path: 'projects', element: page(<Projects />), handle: { title: '프로젝트' } },
      {
        path: 'projects/:projectId',
        element: page(<ProjectDetail />),
        handle: { title: '프로젝트 상세' },
      },
      {
        path: 'projects/:projectId/analysis',
        element: page(<Analysis />),
        handle: { title: 'AI 분석' },
      },
      {
        path: 'projects/:projectId/result',
        element: page(<AnalysisResult />),
        handle: { title: '분석 결과' },
      },
      {
        path: 'projects/:projectId/editor',
        element: page(<Editor />),
        handle: { title: '통합 문서 편집' },
      },
      { path: 'upload', element: page(<Upload />), handle: { title: '문서 업로드' } },
      { path: 'documents', element: page(<Documents />), handle: { title: '통합 문서' } },
      { path: 'history', element: page(<History />), handle: { title: '히스토리' } },
      { path: 'notifications', element: page(<Notifications />), handle: { title: '알림' } },
      { path: 'pricing', element: page(<Pricing />), handle: { title: '이용요금' } },
      { path: 'settings', element: page(<Settings />), handle: { title: '설정' } },
    ],
  },
  { path: '*', element: <NotFound /> },
])
