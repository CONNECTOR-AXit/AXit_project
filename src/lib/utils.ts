import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

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
