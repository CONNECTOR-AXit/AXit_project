/** 포매팅 헬퍼 — 출력은 모두 한국어 로케일 기준입니다. */

const KO = 'ko-KR'

/** 1,234 */
export function formatNumber(value: number) {
  return new Intl.NumberFormat(KO).format(value)
}

/** 87% */
export function formatPercent(value: number, digits = 0) {
  return `${value.toFixed(digits)}%`
}

/** 2024.05.15 */
export function formatDate(iso: string) {
  const d = new Date(iso)
  return `${d.getFullYear()}.${pad(d.getMonth() + 1)}.${pad(d.getDate())}`
}

/** 2024.05.15 14:30 */
export function formatDateTime(iso: string) {
  const d = new Date(iso)
  return `${formatDate(iso)} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 14:30 */
export function formatTime(iso: string) {
  const d = new Date(iso)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * 방금 전 · 3분 전 · 5시간 전 · 2일 전 · 2024.05.15
 * 더미 데이터의 날짜가 고정되어 있으므로 기준 시각을 주입할 수 있게 했습니다.
 */
export function formatRelative(iso: string, now: Date = new Date()) {
  const diff = now.getTime() - new Date(iso).getTime()
  const minute = 60_000
  const hour = 60 * minute
  const day = 24 * hour

  if (diff < minute) return '방금 전'
  if (diff < hour) return `${Math.floor(diff / minute)}분 전`
  if (diff < day) return `${Math.floor(diff / hour)}시간 전`
  if (diff < 7 * day) return `${Math.floor(diff / day)}일 전`
  return formatDate(iso)
}

/** 1.2MB */
export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes}B`
  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(0)}KB`
  const mb = kb / 1024
  if (mb < 1024) return `${mb.toFixed(1)}MB`
  return `${(mb / 1024).toFixed(1)}GB`
}

/** 약 2분 · 약 1시간 20분 */
export function formatDuration(seconds: number) {
  if (seconds < 60) return `약 ${Math.max(1, Math.round(seconds))}초`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `약 ${minutes}분`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `약 ${hours}시간 ${rest}분` : `약 ${hours}시간`
}

/** 아바타 대체 텍스트 — 김AXit → 김, John Doe → JD */
export function initials(name: string) {
  const trimmed = name.trim()
  if (!trimmed) return '?'
  // 한글 이름은 첫 글자가, 영문 이름은 두 단어의 이니셜이 가장 읽기 좋습니다.
  if (/[가-힣]/.test(trimmed[0]!)) return trimmed[0]!
  return trimmed
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join('')
}

function pad(n: number) {
  return String(n).padStart(2, '0')
}
