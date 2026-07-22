import type { User } from '@/types'

/** 로그인한 계정. */
export const currentUser: User = {
  id: 'u-1',
  name: '김AXit',
  email: 'kim@axit.com',
  color: '#0F73D8',
}

/** AI가 작성한 버전·활동에도 아바타를 표시하기 위한 가상 사용자. */
export const aiUser: User = {
  id: 'u-ai',
  name: 'AXit AI',
  email: 'ai@axit.com',
  color: '#38D0B8',
}
