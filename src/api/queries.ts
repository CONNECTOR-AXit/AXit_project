import { useQuery } from '@tanstack/react-query'

import { queryKeys } from './client'
import { aiCredit, dashboardStats, trend, weeklyActivity } from '@/data/dashboard'
import { mergedDocuments } from '@/data/documents'
import { activities, projects } from '@/data/projects'
import { sleep } from '@/lib/utils'
import type { ProjectFilters } from '@/types'

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

/**
 * 프로젝트 목록. 검색·정렬·상태 필터를 서버 대신 여기서 처리합니다.
 * 실제 API 전환 시 이 조건들을 쿼리 파라미터로 넘기면 됩니다.
 */
export function useProjects(filters: ProjectFilters = {}) {
  const { search = '', sort = 'recent', status = 'all' } = filters

  return useQuery({
    queryKey: queryKeys.projects(`${search}|${sort}|${status}`),
    queryFn: () => {
      const keyword = search.trim().toLowerCase()

      const filtered = projects.filter((project) => {
        const matchesKeyword =
          !keyword ||
          project.name.toLowerCase().includes(keyword) ||
          project.description.toLowerCase().includes(keyword)
        const matchesStatus = status === 'all' || project.status === status
        return matchesKeyword && matchesStatus
      })

      const sorted = [...filtered].sort((a, b) => {
        if (sort === 'name') return a.name.localeCompare(b.name, 'ko')
        if (sort === 'progress') return b.progress - a.progress
        return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
      })

      return resolve(sorted)
    },
    // 검색어를 입력하는 동안 목록이 사라지지 않도록 이전 결과를 유지합니다.
    placeholderData: (previous) => previous,
  })
}
