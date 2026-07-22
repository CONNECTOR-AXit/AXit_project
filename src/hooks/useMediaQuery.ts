import { useEffect, useState } from 'react'

/** 미디어 쿼리 구독. SSR 안전 — 하이드레이션 전에는 false 를 반환합니다. */
export function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() =>
    typeof window === 'undefined' ? false : window.matchMedia(query).matches,
  )

  useEffect(() => {
    const list = window.matchMedia(query)
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches)
    // query 가 바뀐 직후에도 값을 맞춰줍니다.
    setMatches(list.matches)
    list.addEventListener('change', onChange)
    return () => list.removeEventListener('change', onChange)
  }, [query])

  return matches
}

/* 반응형 목표치와 동일한 브레이크포인트 — Desktop 1440 / Tablet 1024 / Mobile 768 */
export const useIsDesktop = () => useMediaQuery('(min-width: 1024px)')
export const useIsTablet = () => useMediaQuery('(min-width: 768px) and (max-width: 1023px)')
export const useIsMobile = () => useMediaQuery('(max-width: 767px)')
