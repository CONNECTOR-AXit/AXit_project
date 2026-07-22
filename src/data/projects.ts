import type { Activity, Project } from '@/types'
import { membersOf } from './members'

export const projects: Project[] = [
  {
    id: 'p-1',
    name: '마케팅 캠페인 기획안 통합',
    description:
      '여러 팀에서 작성한 마케팅 캠페인 기획안을 통합하여 하나의 완성된 문서로 만듭니다.',
    status: 'review',
    createdAt: '2024-05-15T09:12:00',
    updatedAt: '2024-05-15T14:30:00',
    documentCount: 5,
    memberCount: 4,
    progress: 65,
    accent: 'blue',
    starred: true,
    members: membersOf([
      { id: 'u-1', role: 'owner' },
      { id: 'u-2', role: 'editor' },
      { id: 'u-3', role: 'editor' },
      { id: 'u-4', role: 'viewer' },
    ]),
  },
  {
    id: 'p-2',
    name: '제품 요구사항 정리',
    description: '기획·디자인·개발 3개 팀의 요구사항 문서를 하나의 PRD로 정리했습니다.',
    status: 'completed',
    createdAt: '2024-05-14T10:04:00',
    updatedAt: '2024-05-16T11:20:00',
    documentCount: 5,
    memberCount: 3,
    progress: 100,
    accent: 'mint',
    members: membersOf([
      { id: 'u-1', role: 'owner' },
      { id: 'u-5', role: 'editor' },
      { id: 'u-6', role: 'viewer' },
    ]),
  },
  {
    id: 'p-3',
    name: '시장 조사 보고서 통합',
    description: '외부 리서치 기관 3곳과 내부 조사 자료의 결론을 비교합니다.',
    status: 'analyzing',
    createdAt: '2024-05-13T13:40:00',
    updatedAt: '2024-05-15T16:02:00',
    documentCount: 4,
    memberCount: 3,
    progress: 40,
    accent: 'amber',
    members: membersOf([
      { id: 'u-2', role: 'owner' },
      { id: 'u-3', role: 'editor' },
      { id: 'u-1', role: 'editor' },
    ]),
  },
  {
    id: 'p-4',
    name: '경쟁사 분석 자료 통합',
    description: '분기별 경쟁사 분석 리포트 6건을 한 문서로 합쳐 변화 추이를 확인합니다.',
    status: 'completed',
    createdAt: '2024-05-12T08:55:00',
    updatedAt: '2024-05-14T17:45:00',
    documentCount: 6,
    memberCount: 5,
    progress: 100,
    accent: 'violet',
    members: membersOf([
      { id: 'u-4', role: 'owner' },
      { id: 'u-1', role: 'editor' },
      { id: 'u-2', role: 'editor' },
      { id: 'u-5', role: 'viewer' },
      { id: 'u-6', role: 'viewer' },
    ]),
  },
  {
    id: 'p-5',
    name: '고객 피드백 정리',
    description: 'CS 인입 채널별 고객 피드백을 주제별로 묶어 정리하는 중입니다.',
    status: 'draft',
    createdAt: '2024-05-11T15:22:00',
    updatedAt: '2024-05-11T15:22:00',
    documentCount: 0,
    memberCount: 2,
    progress: 0,
    accent: 'slate',
    members: membersOf([
      { id: 'u-3', role: 'owner' },
      { id: 'u-1', role: 'viewer' },
    ]),
  },
  {
    id: 'p-6',
    name: '신규 서비스 기획안 통합',
    description: '신규 서비스 아이디어 제안서를 통합해 우선순위를 정리합니다.',
    status: 'uploading',
    createdAt: '2024-05-09T11:10:00',
    updatedAt: '2024-05-13T09:30:00',
    documentCount: 3,
    memberCount: 3,
    progress: 20,
    accent: 'rose',
    members: membersOf([
      { id: 'u-5', role: 'owner' },
      { id: 'u-6', role: 'editor' },
      { id: 'u-1', role: 'viewer' },
    ]),
  },
]

/** 프로젝트 단위 활동 피드. target 에 프로젝트 id 가 담깁니다. */
export const activities: Activity[] = [
  {
    id: 'a-1',
    kind: 'upload',
    actor: '이영희',
    message: "문서 '채널별 홍보 전략.docx'를 업로드했어요.",
    target: 'p-1',
    createdAt: '2024-05-15T14:20:00',
  },
  {
    id: 'a-2',
    kind: 'analysis',
    actor: 'AXit AI',
    message: 'AI 분석이 완료되었습니다.',
    target: 'p-1',
    createdAt: '2024-05-15T14:15:00',
  },
  {
    id: 'a-3',
    kind: 'create',
    actor: '김AXit',
    message: '프로젝트를 생성했습니다.',
    target: 'p-1',
    createdAt: '2024-05-15T10:30:00',
  },
  {
    id: 'a-4',
    kind: 'comment',
    actor: '박민수',
    message: "'예산 계획' 섹션에 댓글을 남겼어요.",
    target: 'p-1',
    createdAt: '2024-05-15T09:48:00',
  },
  {
    id: 'a-5',
    kind: 'invite',
    actor: '김AXit',
    message: '최지우님을 뷰어로 초대했어요.',
    target: 'p-1',
    createdAt: '2024-05-14T18:02:00',
  },
  {
    id: 'a-6',
    kind: 'edit',
    actor: '이영희',
    message: "통합 문서의 '타겟 분석' 문단을 수정했어요.",
    target: 'p-1',
    createdAt: '2024-05-14T16:20:00',
  },
]

export function projectById(id: string) {
  return projects.find((project) => project.id === id)
}

export function activitiesOf(projectId: string) {
  return activities.filter((activity) => activity.target === projectId)
}
