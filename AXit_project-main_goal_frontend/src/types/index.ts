/**
 * AXit 도메인 모델.
 * data 레이어와 모든 기능 모듈이 이 타입을 공유합니다.
 */

/* ── 공통 유니온 ─────────────────────────────────────────── */

export type ProjectStatus = 'draft' | 'uploading' | 'analyzing' | 'review' | 'completed'

export const INTEGRATION_PROGRESS_STEPS = [20, 40, 60, 80, 100] as const

export type DocumentStatus = 'queued' | 'uploading' | 'analyzed' | 'failed'

export type FileKind = 'pdf' | 'docx' | 'txt' | 'hwp' | 'pptx' | 'xlsx' | 'image'

export type MemberRole = 'owner' | 'editor' | 'viewer'

export type AnalysisStage = 'upload' | 'extract' | 'common' | 'difference' | 'merge' | 'done'

export type ActivityKind =
  | 'upload'
  | 'analysis'
  | 'create'
  | 'comment'
  | 'edit'
  | 'invite'
  | 'export'
  | 'settings'
  | 'system'

export type NotificationKind = 'analysis' | 'mention' | 'invite' | 'comment' | 'member'

/* ── 사용자 ──────────────────────────────────────────────── */

export interface User {
  id: string
  name: string
  email: string
  /** 아바타 배경/글자색 생성에 쓰이는 HEX 값 */
  color: string
  role?: MemberRole
}

export interface ProjectMember extends User {
  role: MemberRole
  joinedAt: string
}

/* ── 문서 ────────────────────────────────────────────────── */

export interface DocumentFile {
  id: string
  projectId: string
  name: string
  kind: FileKind
  /** 원본 바이트 크기 — 화면에서 formatBytes 로 변환 */
  size: number
  status: DocumentStatus
  progress: number
  uploadedAt: string
  uploadedBy: string
  /** 통합 문서에서 이 파일이 차지하는 비중 (0–100) */
  contribution?: number
  pages?: number
  /** 원문 조회/다운로드에 쓰는 리비전 ID. */
  revisionId: string
  mimeType: string
  /** 직접 작성 문서는 `/source-revisions/{revisionId}/viewer`에서 원문을 읽습니다. */
  submissionKind: 'text' | 'file'
}

/* ── 프로젝트 ────────────────────────────────────────────── */

export interface Project {
  id: string
  roomId: string
  name: string
  description: string
  status: ProjectStatus
  createdAt: string
  updatedAt: string
  documentCount: number
  memberCount: number
  /** 통합 완료율 0–100 */
  progress: number
  members: ProjectMember[]
  currentUserRole?: 'owner' | 'member'
  /** 폴더 아이콘 색상 — 카드 그리드에 시각적 변화를 줍니다 */
  accent: 'blue' | 'mint' | 'amber' | 'violet' | 'rose' | 'slate'
  starred?: boolean
}

export interface Activity {
  id: string
  kind: ActivityKind
  actor: string
  message: string
  /** 소속 프로젝트 id */
  target?: string
  createdAt: string
}

/* ── 프로젝트 목록 필터 ──────────────────────────────────── */

export type ProjectSortKey = 'recent' | 'name' | 'progress'

/** `all` 은 상태 필터를 걸지 않음을 뜻합니다. */
export type ProjectStatusFilter = ProjectStatus | 'all'

export type ProjectViewMode = 'grid' | 'list'

export interface ProjectFilters {
  search?: string
  sort?: ProjectSortKey
  status?: ProjectStatusFilter
}

/* ── AI 분석 결과 ────────────────────────────────────────── */

export type VerificationVerdict = 'supported' | 'refuted' | 'mixed' | 'unverifiable'

export interface DifferenceGroup {
  id: string
  label: string
  severity: 'high' | 'medium' | 'low'
  /** 외부 검증(사실 확인) 판정. 문서 간 순수 상충 비교인 경우도 있어 없을 수 있습니다. */
  verdict?: VerificationVerdict
  summary: string
  /** 같은 입장을 취한 문서끼리 묶은 그룹 */
  clusters: { documents: string[]; stance: string }[]
}

export interface DocumentBreakdown {
  documentId: string
  name: string
  contribution: number
  uniqueSections: number
  overlapRate: number
  ragUnits: number
  usedRagUnits: number
  sentiment: '적극적' | '중립적' | '보수적'
  highlights: string[]
}

export interface Keyword {
  term: string
  weight: number
  documents: number
  trend: 'up' | 'down' | 'flat'
}

export interface AiInsight {
  id: string
  tone: 'positive' | 'caution' | 'neutral'
  title: string
  body: string
}

export interface AnalysisResult {
  projectId: string
  documentCount: number
  differenceCount: number
  completedAt: string
  headline: string
  /** 외부검증·기여도 데이터에서 실제로 계산한 한 줄 인사이트. */
  oneLineInsight: string
  sourceQuality: {
    status: 'clean' | 'filtered'
    totalAnchorCount: number
    acceptedAnchorCount: number
    excludedAnchorCount: number
  }
  differences: DifferenceGroup[]
  breakdown: DocumentBreakdown[]
  keywords: Keyword[]
  insights: AiInsight[]
}

/* ── 통합 문서 / 에디터 ──────────────────────────────────── */

/** 에디터에서 블록 옆에 표시되는 RAG 출처 태그 — 이 블록이 실제로 참고한 원본 문서명(들). */
export type BlockTag = string

export type DocBlock =
  | { id: string; type: 'heading'; level: 1 | 2 | 3; text: string; tag?: BlockTag }
  | { id: string; type: 'paragraph'; text: string; tag?: BlockTag }
  | { id: string; type: 'list'; items: string[]; tag?: BlockTag }
  | { id: string; type: 'table'; columns: string[]; rows: string[][]; tag?: BlockTag }
  | { id: string; type: 'callout'; text: string; tag?: BlockTag }

export interface MergedDocument {
  id: string
  projectId: string
  title: string
  updatedAt: string
  wordCount: number
  version: string
  /** 서버의 낙관적 동시성 버전 — 저장할 때 반드시 이 값을 함께 보내야 합니다. */
  saveVersion: number
  blocks: DocBlock[]
}

export interface AiSuggestion {
  id: string
  kind: 'add' | 'edit' | 'remove'
  origin?: 'member' | 'automatic_comparison'
  sourceAnchorId?: string
  targetBlockId?: string
  title: string
  detail: string
  targetSection: string
}

export interface DocumentVersion {
  id: string
  label: string
  /** 표시용 버전 번호 — 최초 생성본이 v1이 되도록 1부터 시작합니다. */
  versionNumber: number
  author: string
  createdAt: string
  current?: boolean
}

export interface DocumentComment {
  id: string
  author: string
  section: string
  body: string
  createdAt: string
}

/** 대시보드 · 통합 문서 목록에 표시되는 카드 데이터 */
export interface MergedDocumentSummary {
  id: string
  title: string
  projectId: string
  projectName: string
  updatedAt: string
  sourceCount: number
  version: string
}

/* ── 알림 / 히스토리 ─────────────────────────────────────── */

export interface NotificationItem {
  id: string
  kind: NotificationKind
  title: string
  body: string
  createdAt: string
  read: boolean
  href?: string
  actionKind: 'respond_friend_request' | 'open_room' | 'open_session' | 'open_comment' | 'none'
  resourceType: 'friend_request' | 'room' | 'session' | 'comment'
  resourceId: string
}

export interface NotificationFeed {
  items: NotificationItem[]
  unreadCount: number
  nextCursor: string | null
}

export interface HistoryEntry {
  id: string
  projectId: string
  projectName: string
  action: string
  detail: string
  actor: string
  createdAt: string
  kind: ActivityKind
  href?: string
  ledgerSequence: number
}

export interface HistoryFeed {
  coverageStartedAt: string
  items: HistoryEntry[]
  nextCursor: string | null
}

/* ── 대시보드 ────────────────────────────────────────────── */

export interface StatDelta {
  value: number
  /**
   * 직전 기간 대비 증감률 (%). 비교할 과거 데이터가 없으면 배지를 아예
   * 숨기도록 undefined로 둡니다 — 0으로 채우면 "변화 없음"이라는 잘못된
   * 신호를 주기 때문입니다.
   */
  delta?: number
}

export interface DashboardStats {
  projects: StatDelta
  documents: StatDelta
  analyses: StatDelta
  merged: StatDelta
}

export interface TrendPoint {
  label: string
  uploaded: number
  merged: number
}

export interface WeekdayCompletionPoint {
  label: string
  progress: number
  projects: number
}
