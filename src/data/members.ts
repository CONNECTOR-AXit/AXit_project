import type { MemberRole, ProjectMember, User } from '@/types'
import { aiUser, currentUser } from './user'

/** 워크스페이스 전체 사용자. */
export const users: User[] = [
  currentUser,
  { id: 'u-2', name: '이영희', email: 'younghee@axit.com', color: '#38D0B8' },
  { id: 'u-3', name: '박민수', email: 'minsu@axit.com', color: '#F59E0B' },
  { id: 'u-4', name: '최지우', email: 'jiwoo@axit.com', color: '#8B5CF6' },
  { id: 'u-5', name: '정하늘', email: 'haneul@axit.com', color: '#EF4444' },
  { id: 'u-6', name: '한서준', email: 'seojun@axit.com', color: '#22C55E' },
]

export function userById(id: string): User {
  return users.find((user) => user.id === id) ?? currentUser
}

export function userByName(name: string): User {
  if (name === aiUser.name) return aiUser
  return users.find((user) => user.name === name) ?? currentUser
}

/** 사용자 id + 권한 목록으로 멤버 배열을 만듭니다. */
export function membersOf(
  entries: { id: string; role: MemberRole }[],
  baseDate = '2024-05-01',
): ProjectMember[] {
  return entries.map(({ id, role }, index) => {
    const user = userById(id)
    const joined = new Date(baseDate)
    joined.setDate(joined.getDate() + index * 2)
    return { ...user, role, joinedAt: joined.toISOString() }
  })
}

/** 권한별 표시 라벨. */
export const roleLabel: Record<MemberRole, string> = {
  owner: '관리자',
  editor: '편집자',
  viewer: '뷰어',
}
