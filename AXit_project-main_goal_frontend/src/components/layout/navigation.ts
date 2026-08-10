import {
  Bell,
  FileStack,
  FolderKanban,
  History,
  LayoutDashboard,
  Settings,
  type LucideIcon,
} from 'lucide-react'

export interface NavItem {
  label: string
  to: string
  icon: LucideIcon
  /** `/projects/p-1` 같은 하위 경로에서도 활성 표시되도록 하는 판별 함수. */
  match?: (pathname: string) => boolean
  badge?: number
}

/** 사이드바 주 메뉴. */
export const primaryNav: NavItem[] = [
  { label: '대시보드', to: '/', icon: LayoutDashboard, match: (p) => p === '/' },
  {
    label: '프로젝트',
    to: '/projects',
    icon: FolderKanban,
    match: (p) => p.startsWith('/projects'),
  },
  {
    label: '통합 문서',
    to: '/documents',
    icon: FileStack,
    match: (p) => p.startsWith('/documents'),
  },
  { label: '히스토리', to: '/history', icon: History, match: (p) => p.startsWith('/history') },
  {
    label: '알림',
    to: '/notifications',
    icon: Bell,
    match: (p) => p.startsWith('/notifications'),
  },
]

/** 구분선 아래 보조 메뉴. */
export const secondaryNav: NavItem[] = [
  { label: '설정', to: '/settings', icon: Settings, match: (p) => p.startsWith('/settings') },
]

export function isActive(item: NavItem, pathname: string) {
  return item.match ? item.match(pathname) : pathname === item.to
}
