import { useQuery } from '@tanstack/react-query'

import { queryKeys } from './client'
import { aiCredit, dashboardStats, trend, weeklyActivity } from '@/data/dashboard'
import { mergedDocuments } from '@/data/documents'
import { activities, projects } from '@/data/projects'
import { sleep } from '@/lib/utils'

/** 로딩 상태를 실제로 확인할 수 있도록 지연을 흉내냅니다. */
const LATENCY = 260

async function resolve<T>(value: T, ms = LATENCY): Promise<T> {
  await sleep(ms)
  return value
}

/** 대시보드에 필요한 데이터를 한 번에 가져옵니다. */
export function useDashboard() {
  return useQuery({
    queryKey: queryKeys.dashboard,
    queryFn: () =>
      resolve({
        stats: dashboardStats,
        trend,
        weeklyActivity,
        aiCredit,
        // 최근 업데이트 순으로 4건
        recentProjects: [...projects]
          .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
          .slice(0, 4),
        // 진행 중인 프로젝트만 AI 현황 패널에 표시
        runningProjects: projects.filter((project) => project.progress < 100),
        activities: activities.slice(0, 4),
        mergedDocuments: mergedDocuments.slice(0, 6),
      }),
  })
}
