import axios from 'axios'

/**
 * 공용 axios 인스턴스.
 *
 * 현재 빌드는 모든 데이터를 src/data 의 더미 레이어에서 가져오므로
 * 실제 요청은 발생하지 않습니다. queries.ts 의 queryFn 을
 * `api.get(...)` 으로 바꾸기만 하면 실제 백엔드로 전환됩니다.
 */
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api',
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
})

// 에러 형태를 Error 하나로 통일해 화면에서 분기하지 않도록 합니다.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const message =
      error?.response?.data?.message ?? error?.message ?? '알 수 없는 오류가 발생했습니다.'
    return Promise.reject(new Error(message))
  },
)

/** TanStack Query 캐시 키. 문자열 오타를 막기 위해 한곳에 모읍니다. */
export const queryKeys = {
  dashboard: ['dashboard'] as const,
  projects: (filter?: string) => ['projects', filter ?? 'all'] as const,
  project: (id: string) => ['project', id] as const,
  analysis: (projectId: string) => ['analysis', projectId] as const,
  merged: (projectId: string) => ['merged', projectId] as const,
  notifications: ['notifications'] as const,
  history: ['history'] as const,
}
