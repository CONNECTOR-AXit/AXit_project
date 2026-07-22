import type { NotificationItem } from '@/types'

export const notifications: NotificationItem[] = [
  {
    id: 'n-1',
    kind: 'analysis',
    title: 'AI 분석이 완료되었습니다',
    body: "'마케팅 캠페인 기획안 통합' 프로젝트의 문서 5개 분석이 끝났어요.",
    createdAt: '2024-05-15T14:22:00',
    read: false,
    href: '/projects/p-1/result',
  },
  {
    id: 'n-2',
    kind: 'mention',
    title: '이영희님이 회원님을 언급했어요',
    body: "'예산 계획' 섹션에서 @김AXit 님, 예비비 비율 확인 부탁드려요.",
    createdAt: '2024-05-15T13:48:00',
    read: false,
    href: '/projects/p-1/editor',
  },
  {
    id: 'n-3',
    kind: 'invite',
    title: '새 프로젝트에 초대되었습니다',
    body: "최지우님이 '경쟁사 분석 자료 통합' 프로젝트에 초대했어요.",
    createdAt: '2024-05-15T11:02:00',
    read: false,
    href: '/projects/p-4',
  },
  {
    id: 'n-4',
    kind: 'comment',
    title: '새 댓글이 달렸어요',
    body: "박민수님: '채널 우선순위는 성과 보고 다시 정하는 게 좋겠습니다.'",
    createdAt: '2024-05-14T17:30:00',
    read: true,
    href: '/projects/p-1/editor',
  },
  {
    id: 'n-5',
    kind: 'system',
    title: '저장 용량 80% 사용 중',
    body: '팀 저장 용량이 8GB / 10GB 사용되었습니다. 정리하거나 플랜을 업그레이드하세요.',
    createdAt: '2024-05-14T09:00:00',
    read: true,
    href: '/settings',
  },
  {
    id: 'n-6',
    kind: 'analysis',
    title: 'AI 분석이 시작되었습니다',
    body: "'시장 조사 보고서 통합' 프로젝트 분석이 진행 중이에요.",
    createdAt: '2024-05-13T16:12:00',
    read: true,
    href: '/projects/p-3/analysis',
  },
]

/** 사이드바 · 헤더 배지에 쓰이는 안 읽은 알림 수. */
export const unreadCount = notifications.filter((item) => !item.read).length
