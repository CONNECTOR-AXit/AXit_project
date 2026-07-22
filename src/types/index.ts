/**
 * AXit 도메인 모델.
 * data 레이어와 모든 기능 모듈이 이 타입을 공유합니다.
 */

/* ── 공통 유니온 ─────────────────────────────────────────── */

export type ProjectStatus = 'draft' | 'uploading' | 'analyzing' | 'review' | 'completed'

export type DocumentStatus = 'queued' | 'uploading' | 'uploaded' | 'analyzed' | 'failed'

export type FileKind = 'pdf' | 'docx' | 'txt' | 'hwp' | 'pptx' | 'xlsx'

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

export type NotificationKind = 'analysis' | 'mention' | 'invite' | 'system' | 'comment'

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
}

/* ── 프로젝트 ────────────────────────────────────────────── */

export interface Project {
  id: string
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

/* ── AI 분석 결과 ────────────────────────────────────────── */

export interface CommonTopic {
  id: string
  label: string
  /** 이 주제를 포함한 원본 문서 수 */
  matched: number
  total: number
  summary: string
  excerpts: { document: string; text: string }[]
}

export interface DifferenceGroup {
  id: string
  label: string
  severity: 'high' | 'medium' | 'low'
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
  commonCount: number
  differenceCount: number
  /** 문서 간 평균 중복률 (0–100) */
  overlapRate: number
  completedAt: string
  headline: string
  commonTopics: CommonTopic[]
  differences: DifferenceGroup[]
  breakdown: DocumentBreakdown[]
  keywords: Keyword[]
  insights: AiInsight[]
}

/* ── 통합 문서 / 에디터 ──────────────────────────────────── */

/** 에디터에서 블록 옆에 표시되는 출처 배지 */
export type BlockTag = '공통' | '통합' | 'AI 보완' | '차이 조정'

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
  blocks: DocBlock[]
}

export interface AiSuggestion {
  id: string
  kind: 'add' | 'edit' | 'remove'
  title: string
  detail: string
  targetSection: string
}

export interface DocumentVersion {
  id: string
  label: string
  author: string
  createdAt: string
  summary: string
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
}

/* ── 대시보드 ────────────────────────────────────────────── */

export interface StatDelta {
  value: number
  /** 직전 기간 대비 증감률 (%) */
  delta: number
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

export interface WeeklyPoint {
  label: string
  분석: number
  통합: number
}
