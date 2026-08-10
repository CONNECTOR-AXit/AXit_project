import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

import type { Project } from '@/types'

/**
 * 조건부 클래스명을 합치고 Tailwind 충돌은 뒤쪽 값이 이기도록 정리합니다.
 * 예) cn('p-2', condition && 'p-4') → condition 이 true 면 'p-4'
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 값을 [min, max] 범위로 제한합니다. */
export function clamp(value: number, min = 0, max = 100) {
  return Math.min(max, Math.max(min, value))
}

/** 지연 — 더미 데이터 레이어에서 네트워크 지연을 흉내낼 때 사용합니다. */
export function sleep(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms))
}

/**
 * 프로젝트 카드를 눌렀을 때 이동할 경로.
 * 통합 문서가 이미 있는 상태(review·completed)면 편집기로, 그 외에는
 * 그 프로젝트의 업로드 화면으로 보냅니다.
 */
export function projectEntryPath(project: Project) {
  if (project.status === 'review' || project.status === 'completed') {
    return `/projects/${project.id}/editor`
  }
  return `/projects/${project.id}/upload`
}

/**
 * 특정 프로젝트 맥락이 없는 곳(헤더의 빠른 업로드 버튼, 대시보드 등)에서
 * 쓰는 업로드 바로가기. 업로드는 이제 프로젝트별로만 존재하므로, 최근에
 * 보던 프로젝트가 있으면 그 프로젝트의 업로드 화면으로, 없으면 프로젝트를
 * 먼저 고르도록 목록으로 보냅니다.
 */
export function activeUploadPath() {
  const activeProjectId =
    typeof window === 'undefined' ? null : sessionStorage.getItem('axit:active-project-id')
  return activeProjectId ? `/projects/${activeProjectId}/upload` : '/projects'
}
