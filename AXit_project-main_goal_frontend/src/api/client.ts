import axios, { type AxiosRequestConfig } from 'axios'
import type { operations as GeneratedOperations } from '@axit/api-client'

const originalHost =
  import.meta.env.VITE_PUBLIC_HOST ||
  (typeof window === 'undefined' ? 'localhost:3000' : window.location.host)

export class ApiError extends Error {
  readonly status?: number
  readonly code?: string

  constructor(message: string, status?: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

/**
 * 공용 axios 인스턴스.
 *
 * 백엔드와의 안전한 통신을 위해 HttpOnly 세션 쿠키, CSRF 토큰, Original Host 헤더를 처리합니다.
 */
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api',
  timeout: 20_000,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
    'X-Original-Host': originalHost,
    'X-AXit-Original-Host': originalHost,
  },
})

// 에러 형태를 ApiError 로 통일해 화면에서 직관적으로 분기할 수 있게 합니다.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail =
      error?.response?.data?.detail ??
      error?.response?.data?.message ??
      error?.message ??
      '요청 처리 중 오류가 발생했습니다.'
    return Promise.reject(
      new ApiError(detail, error?.response?.status, error?.response?.data?.code),
    )
  },
)

let csrfToken: string | null = null

export function clearCsrf() {
  csrfToken = null
}

export function clearUserScopedClientState() {
  clearCsrf()
  if (typeof window !== 'undefined') {
    window.localStorage.removeItem('axit.read-notification-ids')
  }
}

export async function fetchCsrfToken(): Promise<string> {
  if (!csrfToken) {
    const response = await api.get<{ csrf_token: string }>('/csrf')
    csrfToken = response.data.csrf_token
  }
  return csrfToken
}

export async function get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const response = await api.get<T>(url, config)
  return response.data
}

export async function mutate<T>(
  method: 'post' | 'put' | 'delete',
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig,
): Promise<T> {
  const token = await fetchCsrfToken()
  const response = await api.request<T>({
    ...config,
    method,
    url,
    data,
    headers: { ...config?.headers, 'X-CSRF-Token': token },
  })
  return response.data
}

export async function uploadFile<T>(
  url: string,
  title: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<T> {
  const token = await fetchCsrfToken()
  const formData = new FormData()
  formData.append('title', title)
  formData.append('file', file)
  const response = await api.post<T>(url, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
      'X-CSRF-Token': token,
    },
    timeout: 120_000,
    onUploadProgress: (event) => {
      if (!event.total) return
      onProgress?.(Math.min(100, Math.round((event.loaded / event.total) * 100)))
    },
  })
  return response.data
}

export interface UploadFilesCallbacks {
  /** 전체 배치의 평균 진행률(%). */
  onProgress?: (percent: number) => void
  /** 파일 하나의 진행률(%)이 바뀔 때마다 호출됩니다. */
  onFileProgress?: (index: number, percent: number) => void
  /** 파일 하나가 성공/실패로 확정될 때마다 호출됩니다. */
  onFileSettled?: (index: number, result: { ok: true } | { ok: false; error: string }) => void
}

export async function uploadFiles<T>(
  url: string,
  title: string,
  files: File[],
  callbacks: UploadFilesCallbacks = {},
): Promise<T[]> {
  const { onProgress, onFileProgress, onFileSettled } = callbacks
  const progressArr = files.map(() => 0)
  const results: T[] = []
  // 한 파일이 실패해도 나머지 파일은 계속 올려야 "일부만 업로드됨" 같은 조용한 유실이 없습니다.
  const failed: { name: string; error: unknown }[] = []
  for (let index = 0; index < files.length; index++) {
    const file = files[index]
    try {
      const res = await uploadFile<T>(url, title, file, (percent) => {
        progressArr[index] = percent
        onFileProgress?.(index, percent)
        const avg = Math.round(progressArr.reduce((a, b) => a + b, 0) / files.length)
        onProgress?.(avg)
      })
      results.push(res)
      onFileSettled?.(index, { ok: true })
    } catch (error) {
      failed.push({ name: file.name, error })
      const message = error instanceof ApiError ? error.message : '업로드에 실패했습니다.'
      onFileSettled?.(index, { ok: false, error: message })
    }
  }
  if (failed.length > 0) {
    const names = failed.map((item) => item.name).join(', ')
    const detail = failed[0].error instanceof ApiError ? failed[0].error.message : undefined
    throw new ApiError(
      `${names} 업로드에 실패했습니다.${detail ? ` (${detail})` : ''}`,
      undefined,
      'partial_upload_failure',
    )
  }
  return results
}

export async function loginRequest(email: string, password: string) {
  clearUserScopedClientState()
  const response = await api.post('/auth/login', { email, password })
  return response.data
}

export async function registerRequest(email: string, password: string, displayName: string) {
  const response = await api.post<{ id: string; email: string; display_name: string }>(
    '/auth/register',
    { email, password, display_name: displayName },
  )
  return response.data
}

export async function logoutRequest() {
  const token = await fetchCsrfToken()
  await api.post('/auth/logout', null, { headers: { 'X-CSRF-Token': token } })
  clearUserScopedClientState()
}

export async function getMeRequest() {
  const response = await api.get<{ id: string; email: string; display_name: string }>('/me')
  return response.data
}

/** Generated OpenAPI operation paths, normalized for this client's `/api` base URL. */
type GeneratedOperation = keyof typeof GeneratedOperations

const operationPaths = {
  listAuditEvents: '/audit-events',
  deleteComment: '/comments/{comment_id}',
  updateComment: '/comments/{comment_id}',
  listMyEmailOutbox: '/me/email-outbox',
  getMyNotificationPreferences: '/me/preferences',
  updateNotificationPreferences: '/me/preferences',
  getMyProfile: '/me/profile',
  updateProfile: '/me/profile',
  listNotifications: '/notifications',
  readAllNotifications: '/notifications/read-all',
  readNotification: '/notifications/{notification_id}/read',
  listSessionComments: '/sessions/{session_id}/comments',
  createComment: '/sessions/{session_id}/comments',
  archiveTalkSession: '/sessions/{session_id}',
  leaveRoom: '/rooms/{room_id}/membership',
} as const satisfies Partial<Record<GeneratedOperation, string>>

export function operationPath(
  operation: keyof typeof operationPaths,
  params: Record<string, string> = {},
) {
  let path: string = operationPaths[operation]
  for (const [key, value] of Object.entries(params)) {
    path = path.replace(`{${key}}`, encodeURIComponent(value))
  }
  return path
}

/** TanStack Query 캐시 키. 문자열 오타를 막기 위해 한곳에 모읍니다. */
export const queryKeys = {
  me: ['me'] as const,
  dashboard: ['dashboard'] as const,
  projects: (filter?: string) => ['projects', filter ?? 'all'] as const,
  project: (id: string) => ['project', id] as const,
  analysis: (projectId: string) => ['analysis', projectId] as const,
  analysisProgress: (projectId: string) => ['analysis-progress', projectId] as const,
  merged: (projectId: string) => ['merged', projectId] as const,
  notifications: ['notifications'] as const,
  outbox: ['email-outbox'] as const,
  history: ['history'] as const,
  profile: ['me', 'profile'] as const,
  preferences: ['me', 'preferences'] as const,
  comments: (sessionId: string) => ['sessions', sessionId, 'comments'] as const,
  rooms: ['rooms'] as const,
  friends: ['friends'] as const,
}
