import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  ApiError,
  get,
  getMeRequest,
  mutate,
  operationPath,
  queryKeys,
  uploadFiles,
} from './client'
import type {
  AuditEventPageResponse,
  AuditEventResponse,
  CommentCreateRequest,
  CommentDeleteRequest,
  CommentPageResponse,
  CommentUpdateRequest,
  EmailOutboxPageResponse,
  NotificationPageResponse,
  NotificationPreferencesResponse,
  NotificationPreferencesUpdateRequest,
  NotificationPreferencesUpdateResponse,
  ProfileResponse,
  ProfileUpdateRequest,
  ProfileUpdateResponse,
  ReadReceiptResponse,
} from '@axit/api-client'
import type {
  Activity,
  AiInsight,
  AiSuggestion,
  AnalysisResult,
  BlockTag,
  DashboardStats,
  DocBlock,
  DocumentBreakdown,
  DocumentFile,
  DocumentVersion,
  HistoryEntry,
  HistoryFeed,
  MergedDocument,
  MergedDocumentSummary,
  NotificationFeed,
  NotificationItem,
  Project,
  ProjectFilters,
  WeekdayCompletionPoint,
} from '@/types'

/* ── 도메인 DTO 타입 정의 (FastAPI Wire Models) ─────────────────── */


interface BackendUser {
  id: string
  email: string
  display_name: string
}

interface BackendRoom {
  id: string
  name: string
  owner_id: string
  role: 'host' | 'member'
}

interface BackendMember {
  user: BackendUser
  role: 'host' | 'member'
}

interface BackendSession {
  id: string
  room_id: string
  host_id: string
  topic: string
  description: string
  state: 'draft' | 'open' | 'closed' | 'processing' | 'ready' | 'needs_attention'
  deadline?: string | null
  generation_epoch: number
  created_at: string
  closed_at?: string | null
}

interface BackendSubmission {
  id: string
  session_id: string
  author_id: string
  current_revision_id: string
  title: string
  kind: 'text' | 'file'
  processing_state: 'uploaded' | 'queued' | 'extracting' | 'ready' | 'failed'
  byte_size?: number
  filename?: string
  mime_type?: string
  author?: BackendUser
  created_at: string
}

interface BackendReport {
  snapshot_id: string
  content_hash: string
  summary: {
    snapshot_id: string
    sections: Array<{
      heading: string
      items: Array<{
        text: string
        source_anchor_ids: string[]
        supports: Array<{
          citation_id: string
          source_anchor_id: string
          exact_quote: string
          start: number
          end: number
        }>
      }>
    }>
  }
  research: {
    snapshot_id: string
    topic_items?: Array<{ text: string; web_evidence_ids: string[] }>
    fact_checks?: Array<{
      source_claim_quote: string
      explanation: string
      verdict: 'supported' | 'refuted' | 'mixed' | 'unverifiable'
      source_anchor_id: string
      web_evidence_ids: string[]
    }>
  }
  rag_contributions: Array<{
    document_id: string
    revision_id: string
    title: string
    rag_unit_count: number
    used_rag_unit_count: number
    used_anchor_ids: string[]
  }>
  source_quality: {
    status: 'clean' | 'filtered'
    total_anchor_count: number
    accepted_anchor_count: number
    excluded_anchor_count: number
    reason_counts: Record<string, number>
  }
}

interface BackendMergedDocumentBlock {
  id: string
  type: 'heading' | 'paragraph'
  level?: 1 | 2 | 3
  text: string
  tag?: string | null
}

interface BackendMergedDocument {
  session_id: string
  snapshot_id: string
  version: number
  blocks: BackendMergedDocumentBlock[]
  updated_at: string | null
}

interface BackendMergedDocumentVersion {
  id: string
  label: string
  document_version: number
  created_by: string
  created_at: string
}

interface BackendSuggestion {
  id: string
  session_id: string
  snapshot_id: string
  author_id: string
  report_content_hash: string
  kind: 'add' | 'edit' | 'remove'
  origin: 'member' | 'automatic_comparison'
  suggested_text: string
  rationale: string
  status: 'open' | 'accepted' | 'rejected'
  created_at: string
  source_anchor_id?: string | null
  target_block_id?: string | null
}

/* ── 유틸리티 헬퍼 ────────────────────────────────────────── */

function mapSessionToProject(
  session: BackendSession,
  submissions: BackendSubmission[] = [],
  members: BackendMember[] = [],
  viewerRole?: BackendRoom['role'],
): Project {
  let status: Project['status'] = 'draft'
  let progress = 20

  if (session.state === 'closed' || session.state === 'processing') {
    status = 'analyzing'
    progress = 60
  } else if (session.state === 'ready') {
    status = 'completed'
    progress = 100
  } else if (session.state === 'needs_attention') {
    status = 'review'
    progress = 80
  } else if (submissions.length > 0) {
    status = 'uploading'
    progress = 40
  }

  const accents: Project['accent'][] = ['blue', 'mint', 'violet', 'amber', 'rose', 'slate']
  const hash = session.id.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0)
  const accent = accents[hash % accents.length]

  return {
    id: session.id,
    roomId: session.room_id,
    name: session.topic || '제목 없는 회의',
    description: session.description || '설명 없음',
    status,
    createdAt: session.created_at,
    updatedAt: session.closed_at ?? session.created_at,
    documentCount: submissions.length,
    memberCount: members.length || 1,
    progress,
    members: members.map((m) => ({
      id: m.user.id,
      name: m.user.display_name,
      email: m.user.email,
      color: '#0F73D8',
      role: m.role === 'host' ? 'owner' : 'editor',
      joinedAt: new Date().toISOString(),
    })),
    currentUserRole: viewerRole === 'host' ? 'owner' : viewerRole,
    accent,
  }
}

function makeActivity(
  session: BackendSession,
  kind: Activity['kind'],
  idSuffix: string,
  actor: string,
  message: string,
  createdAt: string = session.closed_at ?? session.created_at,
): Activity {
  return {
    id: `${session.id}-${idSuffix}`,
    kind,
    actor,
    message,
    target: session.id,
    createdAt,
  }
}

function monthBucketKey(iso: string) {
  const d = new Date(iso)
  return `${d.getFullYear()}-${d.getMonth()}`
}

const WEEKDAY_LABELS = ['월', '화', '수', '목', '금', '토', '일'] as const

function buildProjectCompletionByWeekday(projects: Project[]): WeekdayCompletionPoint[] {
  const buckets = WEEKDAY_LABELS.map((label) => ({ label, totalProgress: 0, projects: 0 }))

  for (const project of projects) {
    const day = new Date(project.updatedAt).getDay()
    if (Number.isNaN(day)) continue

    const weekdayIndex = (day + 6) % 7
    const bucket = buckets[weekdayIndex]!
    bucket.totalProgress += project.progress
    bucket.projects += 1
  }

  return buckets.map(({ label, totalProgress, projects: projectCount }) => ({
    label,
    progress: projectCount === 0 ? 0 : Math.round(totalProgress / projectCount),
    projects: projectCount,
  }))
}

function sessionAnalysisActivity(session: BackendSession): Activity | undefined {
  if (session.state === 'ready') {
    return makeActivity(session, 'analysis', 'analysis-ready', 'AXit AI', 'AI 분석과 통합 리포트 생성이 완료되었습니다.')
  }
  if (session.state === 'closed' || session.state === 'processing') {
    return makeActivity(session, 'analysis', 'analysis-running', 'AXit AI', 'AI 분석이 진행 중입니다.')
  }
  if (session.state === 'needs_attention') {
    return makeActivity(session, 'analysis', 'analysis-review', 'AXit AI', 'AI 분석 결과에 확인이 필요합니다.')
  }
  return undefined
}

function inferFileKind(filename?: string, mimeType?: string): DocumentFile['kind'] {
  const ext = filename?.split('.').pop()?.toLowerCase() ?? ''
  if (['pdf'].includes(ext) || mimeType?.includes('pdf')) return 'pdf'
  if (['docx', 'doc'].includes(ext) || mimeType?.includes('word')) return 'docx'
  if (['hwp', 'hwpx'].includes(ext) || mimeType?.includes('hwp')) return 'hwp'
  if (['pptx', 'ppt'].includes(ext) || mimeType?.includes('presentation')) return 'pptx'
  if (['xlsx', 'xls'].includes(ext) || mimeType?.includes('sheet')) return 'xlsx'
  if (['png', 'jpg', 'jpeg'].includes(ext) || mimeType?.startsWith('image/')) return 'image'
  return 'txt'
}

async function collectCursorPages<T>(
  load: (cursor?: string) => Promise<{ items: T[]; next_cursor: string | null }>,
  initialCursor?: string,
) {
  const items: T[] = []
  const seenCursors = new Set<string>()
  let cursor = initialCursor
  if (initialCursor) seenCursors.add(initialCursor)
  while (true) {
    const page = await load(cursor)
    items.push(...page.items)
    if (!page.next_cursor) return items
    if (seenCursors.has(page.next_cursor)) {
      throw new Error('서버가 반복되는 페이지 커서를 반환했습니다.')
    }
    seenCursors.add(page.next_cursor)
    cursor = page.next_cursor
  }
}

/* ── 쿼리 및 뮤테이션 훅 ───────────────────────────────────── */

/** 로그인한 현재 사용자 정보 */
export function useCurrentUser() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: getMeRequest,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })
}

/** 대시보드 데이터 조회 */
export function useDashboard() {
  return useQuery({
    queryKey: queryKeys.dashboard,
    queryFn: async () => {
      const rooms = await get<BackendRoom[]>('/rooms')
      const allSessions: BackendSession[] = []
      const allSubmissions: BackendSubmission[] = []
      const recentProjects: Project[] = []
      const runningProjects: Project[] = []
      const activities: Activity[] = []
      const mergedDocuments: MergedDocumentSummary[] = []

      const roomBundles = await Promise.all(
        rooms.map(async (room) => {
          const [sessions, members] = await Promise.all([
            get<BackendSession[]>(`/rooms/${room.id}/sessions`),
            get<BackendMember[]>(`/rooms/${room.id}/members`),
          ])
          const submissions = await Promise.all(
            sessions.map((session) =>
              get<BackendSubmission[]>(`/sessions/${session.id}/submissions`),
            ),
          )
          return { room, sessions, members, submissions }
        }),
      )

      for (const { room, sessions, members, submissions: submissionsBySession } of roomBundles) {
        allSessions.push(...sessions)
        const memberById = new Map(members.map((member) => [member.user.id, member.user]))

        for (const [index, session] of sessions.entries()) {
          const submissions = submissionsBySession[index] ?? []
          allSubmissions.push(...submissions)

          const project = mapSessionToProject(session, submissions, members, room.role)
          recentProjects.push(project)
          if (session.state !== 'ready') runningProjects.push(project)

          if (session.state === 'ready') {
            mergedDocuments.push({
              id: session.id,
              title: `${session.topic} 통합 리포트`,
              projectId: session.id,
              projectName: session.topic,
              updatedAt: session.closed_at ?? session.created_at,
              sourceCount: submissions.length,
              version: 'v1.0',
            })
          }

          activities.push(
            makeActivity(session, 'create', 'created', '호스트', `'${session.topic}' 프로젝트가 생성되었습니다.`),
            ...submissions.map((submission) => {
              const author = submission.author ?? memberById.get(submission.author_id)
              const label = submission.kind === 'file' ? '파일' : '텍스트'
              // 세션이 아니라 이 제출물 자체가 실제로 올라온 시각을 씁니다.
              return makeActivity(
                session,
                'upload',
                `submission-${submission.id}`,
                author?.display_name || '참여자',
                `${label} 자료 '${submission.title}'이(가) 제출되었습니다.`,
                submission.created_at,
              )
            }),
          )
          const analysisActivity = sessionAnalysisActivity(session)
          if (analysisActivity) activities.push(analysisActivity)
        }
      }

      const completedAnalyses = allSessions.filter((session) => session.state === 'ready').length

      // 활동 피드는 각 항목의 실제 시각으로 정렬해야 최신순이 맞습니다
      // (이전에는 방 순회 순서를 그냥 뒤집기만 해서 실제 최신순이 아니었습니다).
      const sortedActivities = activities
        .slice()
        .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
      const sortedMergedDocuments = mergedDocuments
        .slice()
        .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
      const sortedRecentProjects = recentProjects
        .slice()
        .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
      const sortedRunningProjects = runningProjects
        .slice()
        .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())

      // 최근 6개월을 실제 달력 기준으로 버킷화합니다 (제출·완료 시각은 백엔드가
      // 이미 내려주므로 순번 기반 "N구간" 표기를 쓸 이유가 없습니다).
      const now = new Date()
      const monthBuckets = Array.from({ length: 6 }, (_, i) => {
        const d = new Date(now.getFullYear(), now.getMonth() - (5 - i), 1)
        return { key: monthBucketKey(d.toISOString()), label: `${d.getMonth() + 1}월` }
      })
      const trendByKey = new Map(
        monthBuckets.map((bucket) => [bucket.key, { label: bucket.label, uploaded: 0, merged: 0 }]),
      )
      for (const submission of allSubmissions) {
        const bucket = trendByKey.get(monthBucketKey(submission.created_at))
        if (bucket) bucket.uploaded += 1
      }
      for (const session of allSessions) {
        if (session.state !== 'ready') continue
        const bucket = trendByKey.get(monthBucketKey(session.closed_at ?? session.created_at))
        if (bucket) bucket.merged += 1
      }
      const trend = monthBuckets.map((bucket) => trendByKey.get(bucket.key)!)

      // 직전 기간 데이터를 아직 별도로 비교하지 않으므로 delta는 생략합니다
      // (0으로 채우면 "변화 없음"이라는 잘못된 신호를 줍니다. Warning.md 참고).
      const stats: DashboardStats = {
        projects: { value: allSessions.length },
        documents: { value: allSubmissions.length },
        analyses: { value: completedAnalyses },
        merged: { value: mergedDocuments.length },
      }

      return {
        stats,
        aiCredit: { used: completedAnalyses, total: 50 },
        trend,
        projectCompletionByWeekday: buildProjectCompletionByWeekday(recentProjects),
        recentProjects: sortedRecentProjects.slice(0, 4),
        runningProjects: sortedRunningProjects.slice(0, 4),
        activities: sortedActivities.slice(0, 4),
        mergedDocuments: sortedMergedDocuments.slice(0, 6),
      }
    },
    refetchInterval: 10_000,
  })
}

/** 완료된 모든 프로젝트의 통합 문서 목록 조회 */
export function useMergedDocuments() {
  return useQuery({
    queryKey: ['merged-documents'],
    queryFn: async () => {
      const rooms = await get<BackendRoom[]>('/rooms')
      const mergedDocuments: MergedDocumentSummary[] = []

      await Promise.all(
        rooms.map(async (room) => {
          const sessions = await get<BackendSession[]>(`/rooms/${room.id}/sessions`)
          await Promise.all(
            sessions
              .filter((session) => session.state === 'ready')
              .map(async (session) => {
                const submissions = await get<BackendSubmission[]>(
                  `/sessions/${session.id}/submissions`,
                ).catch(() => [])
                mergedDocuments.push({
                  id: session.id,
                  title: `${session.topic} 통합 리포트`,
                  projectId: session.id,
                  projectName: session.topic,
                  updatedAt: session.closed_at ?? session.created_at,
                  sourceCount: submissions.length,
                  version: 'v1.0',
                })
              }),
          )
        }),
      )

      return mergedDocuments
    },
  })
}

/** 프로젝트 목록 조회 */
export function useProjects(filters: ProjectFilters = {}) {
  const { search = '', sort = 'recent', status = 'all' } = filters

  return useQuery({
    queryKey: queryKeys.projects(`${search}|${sort}|${status}`),
    queryFn: async () => {
      const rooms = await get<BackendRoom[]>('/rooms')
      const projectsList: Project[] = []

      for (const room of rooms) {
        try {
          const sessions = await get<BackendSession[]>(`/rooms/${room.id}/sessions`)
          const members = await get<BackendMember[]>(`/rooms/${room.id}/members`).catch(() => [])

          for (const session of sessions) {
            const subs = await get<BackendSubmission[]>(`/sessions/${session.id}/submissions`).catch(
              () => [],
            )
            projectsList.push(mapSessionToProject(session, subs, members, room.role))
          }
        } catch {
          // ignore room fetch error
        }
      }

      const keyword = search.trim().toLowerCase()
      const filtered = projectsList.filter((project) => {
        const matchesKeyword =
          !keyword ||
          project.name.toLowerCase().includes(keyword) ||
          project.description.toLowerCase().includes(keyword)
        const matchesStatus = status === 'all' || project.status === status
        return matchesKeyword && matchesStatus
      })

      filtered.sort((a, b) => {
        if (sort === 'name') return a.name.localeCompare(b.name, 'ko')
        // The list endpoints are creation-ordered; reverse that stable source
        // order for the recent view without inventing a client timestamp.
        return projectsList.indexOf(b) - projectsList.indexOf(a)
      })

      return filtered
    },
    placeholderData: (previous) => previous,
  })
}

export function useProjectMembershipActions() {
  const queryClient = useQueryClient()
  const refreshProjects = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['projects'] }),
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard }),
      queryClient.invalidateQueries({ queryKey: queryKeys.rooms }),
    ])
  }

  const remove = useMutation({
    mutationFn: (projectId: string) =>
      mutate(
        'delete',
        operationPath('archiveTalkSession', { session_id: projectId }),
        {},
      ),
    onSuccess: refreshProjects,
  })
  const leave = useMutation({
    mutationFn: (roomId: string) =>
      mutate('delete', operationPath('leaveRoom', { room_id: roomId }), {}),
    onSuccess: refreshProjects,
  })

  return { remove, leave }
}

/** 프로젝트 상세 정보 조회 */
export function useProject(projectId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.project(projectId ?? ''),
    enabled: Boolean(projectId),
    queryFn: async () => {
      if (!projectId) throw new Error('프로젝트 ID가 필요합니다.')

      const session = await get<BackendSession>(`/sessions/${projectId}`)
      const members = await get<BackendMember[]>(`/rooms/${session.room_id}/members`).catch(() => [])
      const submissions = await get<BackendSubmission[]>(`/sessions/${projectId}/submissions`).catch(
        () => [],
      )

      const project = mapSessionToProject(session, submissions, members)

      const documents: DocumentFile[] = submissions.map((sub, idx) => ({
        id: sub.id,
        projectId: session.id,
        name: sub.title || sub.filename || `문서_${idx + 1}`,
        kind: inferFileKind(sub.filename, sub.mime_type),
        size: sub.byte_size ?? 0,
        status:
          sub.processing_state === 'ready'
            ? 'analyzed'
            : sub.processing_state === 'failed'
              ? 'failed'
              : 'queued',
        // 처리 중(업로드됨/큐/추출)에 곧바로 100%를 보여주면, 잠시 뒤 실패로
        // 바뀔 때 "다 됐다가 갑자기 실패"처럼 보여 혼란스럽습니다. 결과가
        // 아직 정해지지 않은 동안은 50%로 두고, 서버 처리가 끝나야만 100%(성공)
        // 또는 0%(실패)로 오르내리게 합니다.
        progress:
          sub.processing_state === 'ready' ? 100 : sub.processing_state === 'failed' ? 0 : 50,
        uploadedAt: sub.created_at,
        uploadedBy: sub.author?.display_name || '참여자',
        contribution: Math.round(100 / Math.max(1, submissions.length)),
        revisionId: sub.current_revision_id,
        mimeType: sub.mime_type || 'application/octet-stream',
        submissionKind: sub.kind,
      }))

      const activities: Activity[] = [
        {
          id: `act-${session.id}`,
          kind: 'create',
          actor: '호스트',
          message: `'${session.topic}' 프로젝트가 생성되었습니다.`,
          target: session.id,
          createdAt: new Date().toISOString(),
        },
      ]

      return { project, documents, activities }
    },
    refetchInterval: (query) => {
      const state = query.state.data?.project.status
      const hasProcessingDocuments = query.state.data?.documents.some(
        (document) => document.status === 'queued' || document.status === 'uploading',
      )
      return state === 'analyzing' || state === 'uploading' || hasProcessingDocuments ? 3000 : false
    },
  })
}

export interface AnalysisProgressSnapshot {
  sessionState: BackendSession['state']
  /** 문서가 하나라도 있고, 전부 추출이 끝났거나(성공/실패) 상태입니다. */
  extractionDone: boolean
  /** 추출에 실패해 분석에서 빠진 문서 제목들 — 조용히 넘어가지 않고 사용자에게 알립니다. */
  failedDocumentTitles: string[]
  summaryDone: boolean
  researchDone: boolean
  /** RAG 초안 검토를 거친 최종 통합 문서가 실제 저장된 상태. */
  reportDone: boolean
  /** 통합 보고서를 바탕으로 자동 수정 추천안이 생성된 상태. */
  suggestionsDone: boolean
  /** summary/research/report와 같은 snapshot의 result API까지 읽을 수 있는 상태. */
  resultDone: boolean
}

function replaceRevisionIdsWithTitles(text: string, submissions: BackendSubmission[]) {
  return submissions.reduce((result, submission) => {
    const revisionId = submission.current_revision_id.toLowerCase()
    const title = submission.title || submission.filename || '이름 없는 문서'
    const readable = `문서 '${title}'`
    return result
      .replaceAll(submission.current_revision_id, readable)
      .replaceAll(revisionId, readable)
      .replace(new RegExp(`\\brevision(?:_id)?\\s+${revisionId.slice(0, 8)}\\b`, 'gi'), readable)
      .replace(new RegExp(`\\b${revisionId.slice(0, 8)}\\b`, 'gi'), readable)
  }, text)
}

/**
 * AI 분석 진행 상태를 실제 백엔드 작업(추출 → 요약 → 리서치 → 리포트) 기준으로 조회합니다.
 * 고정 시간으로 진행률을 흉내 내지 않고, 각 단계가 실제로 끝났는지 폴링합니다.
 */
export function useAnalysisProgress(projectId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.analysisProgress(projectId ?? ''),
    enabled: Boolean(projectId),
    queryFn: async (): Promise<AnalysisProgressSnapshot> => {
      if (!projectId) throw new Error('프로젝트 ID가 필요합니다.')
      const [session, submissions] = await Promise.all([
        get<BackendSession>(`/sessions/${projectId}`),
        get<BackendSubmission[]>(`/sessions/${projectId}/submissions`).catch(() => []),
      ])
      const extractionDone =
        submissions.length > 0 &&
        submissions.every((sub) => sub.processing_state === 'ready' || sub.processing_state === 'failed')
      const failedDocumentTitles = submissions
        .filter((sub) => sub.processing_state === 'failed')
        .map((sub) => sub.title || sub.filename || '이름 없는 문서')

      // 세션이 실패 상태로 확정됐으면 이후 단계 조회는 의미가 없습니다.
      if (session.state === 'needs_attention') {
        return {
          sessionState: session.state,
          extractionDone,
          failedDocumentTitles,
          summaryDone: false,
          researchDone: false,
          reportDone: false,
          suggestionsDone: false,
          resultDone: false,
        }
      }

      const [summarySnapshot, researchSnapshot, reportSnapshot, resultSnapshot, suggestions] = await Promise.all([
        _probeSnapshot(`/sessions/${projectId}/summary`),
        _probeSnapshot(`/sessions/${projectId}/research`),
        _probeGeneratedMergedSnapshot(`/sessions/${projectId}/merged-document`),
        _probeSnapshot(`/sessions/${projectId}/report`),
        get<BackendSuggestion[]>(`/sessions/${projectId}/suggestions`).catch(() => []),
      ])

      // 이전 generation의 성공 산출물이 남아 있어도 현재 분석 완료로 계산하지
      // 않습니다. 모든 결과가 정확히 같은 snapshot일 때만 다음 단계가 끝납니다.
      const generationSnapshot =
        summarySnapshot !== null && summarySnapshot === researchSnapshot ? summarySnapshot : null
      const summaryDone = summarySnapshot !== null
      const researchDone = researchSnapshot !== null
      const reportDone = generationSnapshot !== null && reportSnapshot === generationSnapshot
      const resultDone = reportDone && resultSnapshot === generationSnapshot
      const suggestionsDone =
        resultDone &&
        suggestions.some(
          (suggestion) =>
            suggestion.origin === 'automatic_comparison' &&
            suggestion.snapshot_id === generationSnapshot,
        )

      return {
        sessionState: session.state,
        extractionDone,
        failedDocumentTitles,
        summaryDone,
        researchDone,
        reportDone,
        suggestionsDone,
        resultDone,
      }
    },
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data) return 2000
      if (data.suggestionsDone || data.sessionState === 'needs_attention') return false
      return 2000
    },
  })
}

/** AI 분석 결과 조회 */
export function useAnalysis(projectId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.analysis(projectId ?? ''),
    enabled: Boolean(projectId),
    // 증강 분석이 새 snapshot을 만들면 이전 성공 응답을 재사용하지 않고 현재
    // snapshot의 RAG 단위 분포를 다시 받아 두 화면의 비율을 함께 갱신합니다.
    refetchOnMount: 'always',
    queryFn: async () => {
      if (!projectId) throw new Error('프로젝트 ID가 필요합니다.')
      const [report, submissions] = await Promise.all([
        get<BackendReport>(`/sessions/${projectId}/report`),
        get<BackendSubmission[]>(`/sessions/${projectId}/submissions`).catch(() => []),
      ])

      // severity: refuted/unverifiable(검증 의심)는 확인 전까지 주의가 필요하다는 뜻으로
      // 다룹니다 — "차이"가 아니라 "얼마나 신뢰할 수 있는지"를 보여줍니다.
      const severityByVerdict = {
        supported: 'low',
        refuted: 'high',
        mixed: 'medium',
        unverifiable: 'medium',
      } as const

      const factChecks = report.research?.fact_checks ?? []
      const differences = factChecks.map((fc, idx) => {
        const readableClaim = replaceRevisionIdsWithTitles(fc.source_claim_quote, submissions)
        const readableExplanation = replaceRevisionIdsWithTitles(fc.explanation, submissions)
        const referencedDocuments = submissions
          .filter((submission) => {
            const revisionId = submission.current_revision_id.toLowerCase()
            const source = `${fc.source_claim_quote} ${fc.explanation}`.toLowerCase()
            return source.includes(revisionId) || source.includes(revisionId.slice(0, 8))
          })
          .map((submission) => submission.title || submission.filename || '이름 없는 문서')

        return {
          id: `diff-${idx + 1}`,
          label:
            readableClaim.length > 48 ? `${readableClaim.slice(0, 48)}…` : readableClaim,
          severity: severityByVerdict[fc.verdict],
          verdict: fc.verdict,
          summary: readableExplanation,
          clusters: [
            { documents: ['원문 주장'], stance: readableClaim },
            {
              documents: referencedDocuments.length > 0 ? referencedDocuments : ['외부 검증'],
              stance: readableExplanation,
            },
          ],
        }
      })

      const totalUsedRagUnits = report.rag_contributions.reduce(
        (total, document) => total + document.used_rag_unit_count,
        0,
      )
      const summaryItems = report.summary.sections.flatMap((section) => section.items)
      const breakdown: DocumentBreakdown[] = report.rag_contributions.map((document) => {
        const usedAnchorIds = new Set(document.used_anchor_ids)
        const highlights = summaryItems
          .filter((item) => item.source_anchor_ids.some((anchorId) => usedAnchorIds.has(anchorId)))
          .map((item) => item.text)
          .filter((value, index, values) => values.indexOf(value) === index)
          .slice(0, 6)
        return {
          documentId: document.document_id,
          name: document.title,
          contribution:
            totalUsedRagUnits > 0
              ? Math.round((document.used_rag_unit_count / totalUsedRagUnits) * 100)
              : 0,
          uniqueSections: document.used_rag_unit_count,
          overlapRate: 0,
          ragUnits: document.rag_unit_count,
          usedRagUnits: document.used_rag_unit_count,
          sentiment: '중립적' as const,
          highlights,
        }
      })

      // 실제 검증/기여도 데이터에서만 인사이트를 계산합니다 — 문서 내용을
      // 지어내는 대신, 없으면 정직하게 "아직 없다"고 말합니다.
      const supportedCount = differences.filter((d) => d.verdict === 'supported').length
      const cautionItems = differences.filter(
        (d) => d.verdict === 'refuted' || d.verdict === 'unverifiable' || d.verdict === 'mixed',
      )
      const topCaution = cautionItems.find((d) => d.verdict === 'refuted') ?? cautionItems[0]
      const topDocument = [...breakdown].sort((a, b) => b.contribution - a.contribution)[0]

      const oneLineInsight =
        differences.length === 0
          ? '아직 외부 검증 결과가 없어요.'
          : cautionItems.length > 0
            ? `외부 검증 결과 ${supportedCount}건은 사실로 확인됐고, ${cautionItems.length}건은 주의가 필요해요` +
              (topCaution ? ` — 특히 "${topCaution.label}"을 확인해 주세요.` : '.')
            : `외부 검증 결과 ${supportedCount}건 모두 사실로 확인됐어요.`

      const insights: AiInsight[] = []
      if (differences.length > 0) {
        insights.push({
          id: 'insight-verification',
          tone: cautionItems.length > 0 ? 'caution' : 'positive',
          title: cautionItems.length > 0 ? '주의가 필요한 항목이 있어요' : '외부 검증을 모두 통과했어요',
          body: oneLineInsight,
        })
      }
      if (topDocument) {
        insights.push({
          id: 'insight-contribution',
          tone: 'neutral',
          title: '통합 문서 기여도',
          body: `'${topDocument.name}' 문서가 통합 문서에 가장 많이 반영됐어요 (기여도 ${topDocument.contribution}%).`,
        })
      }

      const result: AnalysisResult = {
        projectId,
        documentCount: submissions.length,
        differenceCount: differences.length,
        completedAt: new Date().toISOString(),
        headline: report.summary?.sections[0]?.heading || '문서 분석 및 외부검증 결과',
        oneLineInsight,
        sourceQuality: {
          status: report.source_quality.status,
          totalAnchorCount: report.source_quality.total_anchor_count,
          acceptedAnchorCount: report.source_quality.accepted_anchor_count,
          excludedAnchorCount: report.source_quality.excluded_anchor_count,
        },
        differences,
        breakdown,
        keywords: [],
        insights,
      }
      return result;
    },
    // 보고서 생성이 아직 끝나지 않았으면 실패로 끝내지 않고 준비될 때까지 주기적으로 재시도합니다.
    retry: false,
    refetchInterval: (query) => (query.state.status === 'error' ? 4_000 : false),
  })
}

function _blockFromBackend(block: BackendMergedDocumentBlock): DocBlock {
  const tag = _blockTag(block.tag)
  if (block.type === 'heading') {
    return { id: block.id, type: 'heading', level: block.level ?? 1, text: block.text, tag }
  }
  return { id: block.id, type: 'paragraph', text: block.text, tag }
}

async function _probeSnapshot(url: string): Promise<string | null> {
  try {
    const payload = await get<Record<string, unknown>>(url)
    return typeof payload.snapshot_id === 'string' ? payload.snapshot_id : null
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

async function _probeGeneratedMergedSnapshot(url: string): Promise<string | null> {
  try {
    const payload = await get<Record<string, unknown>>(url)
    // version=0 is the legacy summary-derived editor preview. The approved
    // pipeline writes the Grok RAG final document as version 1, so progress
    // must not mark 통합 문서 생성 complete for the preview fallback.
    return typeof payload.snapshot_id === 'string' &&
      typeof payload.version === 'number' &&
      payload.version >= 1
      ? payload.snapshot_id
      : null
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

/** RAG 인용 태그 — 서버가 보내는 실제 원본 문서명을 그대로 받습니다. */
function _blockTag(value: string | null | undefined): BlockTag | undefined {
  return value && value.trim() ? value : undefined
}

/** 서버가 저장을 받아들이는 블록 형태만 왕복시킵니다 — 조용히 내용을 버리지 않습니다. */
function _blockToBackend(block: DocBlock): BackendMergedDocumentBlock {
  if (block.type === 'heading') {
    return { id: block.id, type: 'heading', level: block.level, text: block.text, tag: block.tag ?? null }
  }
  if (block.type === 'paragraph') {
    return { id: block.id, type: 'paragraph', text: block.text, tag: block.tag ?? null }
  }
  throw new Error(`이 블록 종류(${block.type})는 아직 저장할 수 없습니다.`)
}

export interface UseMergedDocumentData {
  document: MergedDocument
  suggestions: AiSuggestion[]
  versions: DocumentVersion[]
}

/** 통합 문서 및 에디터 데이터 조회 */
export function useMergedDocument(projectId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.merged(projectId ?? ''),
    enabled: Boolean(projectId),
    queryFn: async () => {
      if (!projectId) throw new Error('프로젝트 ID가 필요합니다.')

      const [mergedDocumentPayload, suggestions, versionPayload] = await Promise.all([
        get<BackendMergedDocument>(`/sessions/${projectId}/merged-document`),
        get<BackendSuggestion[]>(`/sessions/${projectId}/suggestions`).catch(() => []),
        get<{ items: BackendMergedDocumentVersion[] }>(
          `/sessions/${projectId}/merged-document/versions`,
        ).catch(() => ({ items: [] })),
      ])

      const blocks: MergedDocument['blocks'] = mergedDocumentPayload.blocks.map(_blockFromBackend)

      const mergedDoc: MergedDocument = {
        id: `merged-${projectId}`,
        projectId,
        title: '통합 보고서',
        updatedAt: mergedDocumentPayload.updated_at ?? new Date().toISOString(),
        wordCount: blocks.reduce((sum, b) => {
          if ('text' in b && typeof b.text === 'string') return sum + b.text.length
          if ('items' in b && Array.isArray(b.items)) return sum + b.items.join(' ').length
          return sum
        }, 0),
        version: 'v1.0',
        saveVersion: mergedDocumentPayload.version,
        blocks,
      }

      const formattedSuggestions: AiSuggestion[] = suggestions.filter((s) => s.status === 'open').map((s) => ({
        id: s.id,
        kind: s.kind,
        origin: s.origin,
        sourceAnchorId: s.source_anchor_id ?? undefined,
        targetBlockId: s.target_block_id ?? undefined,
        title: s.rationale || 'AI 제안',
        detail: s.suggested_text,
        targetSection: s.source_anchor_id
          ? `통합 문서 본문 · 근거 ${s.source_anchor_id.slice(0, 8)}`
          : '통합 문서 본문',
      }))

      // author는 실제 멤버 이름이 아니라 사용자 ID입니다 — 멤버 목록은 이 훅이
      // 모르는 프로젝트(useProject) 쪽 데이터라, 컴포넌트에서 실제 이름으로 바꿔줍니다.
      // document_version은 저장 전(baseline)에 0부터 시작하는 내부 낙관적 동시성
      // 값이라, 사용자에게는 최초 생성본이 v1이 되도록 1을 더해서 보여줍니다.
      const versions: DocumentVersion[] = versionPayload.items.map((item, index) => ({
        id: item.id,
        label: item.label,
        versionNumber: item.document_version + 1,
        author: item.created_by,
        createdAt: item.created_at,
        current: index === 0,
      }))

      return {
        document: mergedDoc,
        suggestions: formattedSuggestions,
        versions,
      }
    },
    // 통합 보고서가 아직 생성 중이면 실패로 끝내지 않고 준비될 때까지 주기적으로 재시도합니다.
    retry: false,
    refetchInterval: (query) => (query.state.status === 'error' ? 4_000 : false),
  })
}

/** 통합 문서 편집 내용을 실제로 서버에 저장합니다 (낙관적 동시성: expected_version 불일치 시 409). */
export function useSaveMergedDocument(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: { blocks: DocBlock[]; expectedVersion: number }) => {
      const result = await mutate<BackendMergedDocument>(
        'put',
        `/sessions/${projectId}/merged-document`,
        {
          expected_version: payload.expectedVersion,
          blocks: payload.blocks.map(_blockToBackend),
        },
      )
      return { result, blocks: payload.blocks }
    },
    onSuccess: ({ result, blocks }) => {
      queryClient.setQueryData(queryKeys.merged(projectId), (old: UseMergedDocumentData | undefined) =>
        old
          ? {
              ...old,
              document: {
                ...old.document,
                saveVersion: result.version,
                updatedAt: result.updated_at ?? old.document.updatedAt,
                blocks,
              },
            }
          : old,
      )
    },
  })
}

/** 현재 문서를 "변경 내역" 탭에 영구적인 이름 붙은 버전으로 저장합니다. */
export function useCreateMergedDocumentVersion(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: { label: string }) =>
      mutate<BackendMergedDocumentVersion>(
        'post',
        `/sessions/${projectId}/merged-document/versions`,
        { label: payload.label },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.merged(projectId) })
    },
  })
}

/** 과거 버전 하나의 전체 내용(블록 포함)을 읽기 전용으로 미리 봅니다. */
export function useMergedDocumentVersion(projectId: string, versionId: string | null) {
  return useQuery({
    queryKey: ['merged-document-version', projectId, versionId ?? ''],
    enabled: Boolean(versionId),
    queryFn: async () => {
      const payload = await get<{
        id: string
        label: string
        document_version: number
        created_by: string
        created_at: string
        blocks: BackendMergedDocumentBlock[]
      }>(`/sessions/${projectId}/merged-document/versions/${versionId}`)
      return {
        id: payload.id,
        label: payload.label,
        documentVersion: payload.document_version,
        createdBy: payload.created_by,
        createdAt: payload.created_at,
        blocks: payload.blocks.map(_blockFromBackend),
      }
    },
  })
}

/** 서버 감사 이벤트를 사용자 문구로 바꿉니다. 원문/secret metadata는 표시하지 않습니다. */
const auditCopy: Record<string, { action: string; detail: string; kind: HistoryEntry['kind'] }> = {
  'account.registered': { action: '계정 생성', detail: '계정이 생성되었습니다.', kind: 'create' },
  'profile.updated': { action: '프로필 변경', detail: '프로필 정보가 변경되었습니다.', kind: 'settings' },
  'notification_preferences.updated': { action: '알림 설정 변경', detail: '알림 수신 설정이 변경되었습니다.', kind: 'settings' },
  'friendship.requested': { action: '친구 요청', detail: '친구 요청을 보냈습니다.', kind: 'invite' },
  'friendship.accepted': { action: '친구 요청 수락', detail: '친구 요청을 수락했습니다.', kind: 'invite' },
  'friendship.rejected': { action: '친구 요청 거절', detail: '친구 요청을 거절했습니다.', kind: 'invite' },
  'room.created': { action: '프로젝트 공간 생성', detail: '프로젝트 공간이 생성되었습니다.', kind: 'create' },
  'room.member_added': { action: '멤버 추가', detail: '프로젝트 공간에 멤버가 추가되었습니다.', kind: 'invite' },
  'room.member_left': { action: '프로젝트 탈퇴', detail: '참여자가 프로젝트에서 탈퇴했습니다.', kind: 'edit' },
  'session.created': { action: '회의 생성', detail: '회의 프로젝트가 생성되었습니다.', kind: 'create' },
  'session.archived': { action: '프로젝트 제거', detail: '프로젝트가 목록에서 제거되었습니다.', kind: 'edit' },
  'session.closed': { action: '회의 마감', detail: '자료 제출이 마감되었습니다.', kind: 'edit' },
  'session.retry_requested': { action: '분석 재시도', detail: '분석 재시도가 요청되었습니다.', kind: 'analysis' },
  'session.processing': { action: '분석 시작', detail: '분석 처리가 시작되었습니다.', kind: 'analysis' },
  'session.ready': { action: '분석 완료', detail: '분석 결과가 준비되었습니다.', kind: 'analysis' },
  'session.needs_attention': { action: '분석 확인 필요', detail: '분석 결과에 확인이 필요합니다.', kind: 'analysis' },
  'submission.created': { action: '자료 제출', detail: '회의 자료가 제출되었습니다.', kind: 'upload' },
  'submission.revised': { action: '자료 수정', detail: '제출 자료가 수정되었습니다.', kind: 'edit' },
  'source_revision.ready': { action: '자료 처리 완료', detail: '제출 자료 처리가 완료되었습니다.', kind: 'upload' },
  'source_revision.failed': { action: '자료 처리 실패', detail: '제출 자료 처리에 실패했습니다.', kind: 'upload' },
  'suggestion.created': { action: '제안 생성', detail: '보고서 제안이 생성되었습니다.', kind: 'edit' },
  'suggestion.accepted': { action: '제안 수락', detail: '보고서 제안이 수락되었습니다.', kind: 'edit' },
  'suggestion.rejected': { action: '제안 거절', detail: '보고서 제안이 거절되었습니다.', kind: 'edit' },
  'comment.created': { action: '댓글 작성', detail: '댓글이 작성되었습니다.', kind: 'comment' },
  'comment.updated': { action: '댓글 수정', detail: '댓글이 수정되었습니다.', kind: 'comment' },
  'comment.deleted': { action: '댓글 삭제', detail: '댓글이 삭제되었습니다.', kind: 'comment' },
}

function auditHref(item: AuditEventResponse) {
  if (item.session_id) return `/projects/${item.session_id}`
  if (item.room_id) return `/projects`
  return undefined
}

/** 서버 감사 원장의 전체 visible scope. ledger_sequence 순서를 그대로 유지합니다. */
export function useHistory() {
  return useQuery({
    queryKey: queryKeys.history,
    queryFn: async (): Promise<HistoryFeed> => {
      const firstPage = await get<AuditEventPageResponse>(operationPath('listAuditEvents'), {
        params: { scope: 'all', limit: 100 },
      })
      const remaining = firstPage.next_cursor
        ? await collectCursorPages<AuditEventResponse>(
            (cursor) =>
              get<AuditEventPageResponse>(operationPath('listAuditEvents'), {
                params: { scope: 'all', limit: 100, cursor },
              }),
            firstPage.next_cursor,
          )
        : []
      return {
        coverageStartedAt: firstPage.coverage_started_at,
        nextCursor: null,
        items: [...firstPage.items, ...remaining].map((item) => {
          const copy = auditCopy[item.event_type] ?? {
            action: '시스템 활동',
            detail: '시스템 활동이 기록되었습니다.',
            kind: 'system' as const,
          }
          return {
            id: item.id,
            projectId: item.session_id ?? item.room_id ?? '',
            projectName: item.scope_type === 'personal' ? '내 계정' : item.entity_type,
            action: copy.action,
            detail: copy.detail,
            actor: item.actor_display_name?.trim() || (item.actor_id ? '삭제된 사용자' : '시스템'),
            createdAt: item.created_at,
            kind: copy.kind,
            href: auditHref(item),
            ledgerSequence: item.ledger_sequence,
          }
        }),
      }
    },
  })
}

function mapNotification(item: NotificationPageResponse['items'][number]): NotificationItem {
  const kind: NotificationItem['kind'] =
    item.kind === 'analysis_completed'
      ? 'analysis'
      : item.kind === 'friend_request'
        ? 'invite'
        : item.kind === 'room_member_added'
          ? 'member'
          : item.kind
  return {
    id: item.id,
    kind,
    title: item.title,
    body: item.body,
    createdAt: item.created_at,
    read: item.read_at !== null,
    href: item.href,
    actionKind: item.action_kind,
    resourceType: item.resource_type,
    resourceId: item.resource_id,
  }
}

/** 수신자 본인의 서버 알림 page가 목록과 badge의 단일 source입니다. */
export function useNotifications() {
  return useQuery({
    queryKey: queryKeys.notifications,
    queryFn: async (): Promise<NotificationFeed> => {
      const firstPage = await get<NotificationPageResponse>(operationPath('listNotifications'), {
        params: { limit: 100 },
      })
      const remaining = firstPage.next_cursor
        ? await collectCursorPages<NotificationPageResponse['items'][number]>(
            (cursor) =>
              get<NotificationPageResponse>(operationPath('listNotifications'), {
                params: { limit: 100, cursor },
              }),
            firstPage.next_cursor,
          )
        : []
      return {
        items: [...firstPage.items, ...remaining].map(mapNotification),
        unreadCount: firstPage.unread_count,
        nextCursor: null,
      }
    },
  })
}

export function useNotificationReadActions() {
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.notifications })
  return {
    markRead: useMutation({
      mutationFn: (id: string) =>
        mutate<ReadReceiptResponse>('post', operationPath('readNotification', { notification_id: id }), {}),
      onSuccess: refresh,
    }),
    markAllRead: useMutation({
      mutationFn: () => mutate<ReadReceiptResponse>('post', operationPath('readAllNotifications'), {}),
      onSuccess: refresh,
    }),
  }
}

export function useFriendRequestActions() {
  const queryClient = useQueryClient()
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.notifications })
    void queryClient.invalidateQueries({ queryKey: queryKeys.friends })
  }
  return {
    accept: useMutation({
      mutationFn: (requestId: string) => mutate('post', `/friend-requests/${requestId}/accept`, {}),
      onSuccess: refresh,
    }),
    reject: useMutation({
      mutationFn: (requestId: string) => mutate('post', `/friend-requests/${requestId}/reject`, {}),
      onSuccess: refresh,
    }),
  }
}

export function useMyProfile() {
  return useQuery({
    queryKey: queryKeys.profile,
    queryFn: () => get<ProfileResponse>(operationPath('getMyProfile')),
  })
}

export function useUpdateMyProfile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ProfileUpdateRequest) =>
      mutate<ProfileUpdateResponse>('put', operationPath('updateProfile'), payload),
    onSuccess: (profile) => {
      queryClient.setQueryData(queryKeys.profile, profile)
      void queryClient.invalidateQueries({ queryKey: queryKeys.me })
    },
  })
}

export function useMyPreferences() {
  return useQuery({
    queryKey: queryKeys.preferences,
    queryFn: () => get<NotificationPreferencesResponse>(operationPath('getMyNotificationPreferences')),
  })
}

export function useUpdateMyPreferences() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: NotificationPreferencesUpdateRequest) =>
      mutate<NotificationPreferencesUpdateResponse>('put', operationPath('updateNotificationPreferences'), payload),
    onSuccess: (preferences) => queryClient.setQueryData(queryKeys.preferences, preferences),
  })
}

export function useMyEmailOutbox() {
  return useQuery({
    queryKey: queryKeys.outbox,
    queryFn: async (): Promise<EmailOutboxPageResponse> => ({
      items: await collectCursorPages((cursor) =>
        get<EmailOutboxPageResponse>(operationPath('listMyEmailOutbox'), {
          params: { limit: 100, ...(cursor ? { cursor } : {}) },
        }),
      ),
      next_cursor: null,
    }),
  })
}

export function useComments(sessionId: string) {
  return useQuery({
    queryKey: queryKeys.comments(sessionId),
    queryFn: async (): Promise<CommentPageResponse> => ({
      items: await collectCursorPages((cursor) =>
        get<CommentPageResponse>(operationPath('listSessionComments', { session_id: sessionId }), {
          params: { limit: 100, ...(cursor ? { cursor } : {}) },
        }),
      ),
      next_cursor: null,
    }),
    enabled: Boolean(sessionId),
  })
}

export function useCommentActions(sessionId: string) {
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.comments(sessionId) })
  return {
    create: useMutation({
      mutationFn: (payload: CommentCreateRequest) =>
        mutate('post', operationPath('createComment', { session_id: sessionId }), payload),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: ({ id, payload }: { id: string; payload: CommentUpdateRequest }) =>
        mutate('put', operationPath('updateComment', { comment_id: id }), payload),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: ({ id, payload }: { id: string; payload: CommentDeleteRequest }) =>
        mutate('delete', operationPath('deleteComment', { comment_id: id }), payload),
      onSuccess: refresh,
    }),
  }
}

/* ── 프로젝트 생성 및 문서 업로드 뮤테이션 ───────────────────── */

export function useCreateProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ name, description }: { name: string; description: string }) => {
      const targetRoom = await mutate<BackendRoom>('post', '/rooms', { name })
      const session = await mutate<BackendSession>('post', `/rooms/${targetRoom.id}/sessions`, {
        topic: name,
        description,
      })
      return session
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboard })
      void queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
  })
}

export interface DescriptionInterviewTurn {
  question: string
  answer: string
}

export interface DescriptionSuggestionQuestion {
  question: string
  options: string[]
  /** OMX deep-interview 방식의 명확도 자가 채점 — 0.0(모호함)~1.0(명확함). */
  clarity: number
}

export type DescriptionSuggestionStep =
  | { step: 'question'; question: DescriptionSuggestionQuestion }
  | { step: 'final'; description: string }

/**
 * "설명 구체화" 버튼 — 한 번에 완성본을 던지지 않고, AI가 질문을 1개씩 물어보며
 * (정보가 충분해질 때까지) 답변을 이어붙여 기존 초안을 확장한 설명 하나를 만듭니다.
 */
export function useSuggestDescriptions() {
  return useMutation({
    mutationFn: async ({
      title,
      draft,
      history,
      forceFinal,
    }: {
      title: string
      draft: string
      history: DescriptionInterviewTurn[]
      /** "그만 묻고 지금까지 답변으로 정리해줘" — 질문 라운드를 건너뛰고 바로 확정 후보를 받습니다. */
      forceFinal?: boolean
    }) =>
      mutate<DescriptionSuggestionStep>(
        'post',
        '/projects/description-suggestions',
        { title, draft, history, force_final: forceFinal ?? false },
        // AI가 명확도를 채점하며 답하는 라운드라 20초 기본 타임아웃보다 오래
        // 걸릴 수 있습니다. 웹 프록시의 유휴 타임아웃(INTERNAL_API_TIMEOUT_MS,
        // 1분)보다 여유를 두어, 정말 느릴 때도 클라이언트가 먼저 끊지 않고
        // 프록시의 정상적인 504 오류 응답을 받게 합니다.
        { timeout: 65_000 },
      ),
  })
}

/** 제출 직후 응답의 최소 형태 — 업로드 큐 항목에 리비전 ID를 바로 연결하는 데 씁니다. */
interface CreatedSubmission {
  id: string
  current_revision_id: string
}

export function useUploadDocuments(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      title,
      files,
      text,
      onProgress,
      onFileProgress,
      onFileSettled,
    }: {
      title?: string
      files?: File[]
      text?: string
      onProgress?: (percent: number) => void
      onFileProgress?: (index: number, percent: number) => void
      onFileSettled?: (index: number, result: { ok: true } | { ok: false; error: string }) => void
    }) => {
      if (text) {
        const textResult = await mutate<CreatedSubmission>(
          'post',
          `/sessions/${projectId}/submissions/text`,
          { title: title || '텍스트 제출', text },
        )
        return { textResult, fileResults: [] as CreatedSubmission[] }
      }
      if (files && files.length > 0) {
        const fileResults = await uploadFiles<CreatedSubmission>(
          `/sessions/${projectId}/submissions/files`,
          title || '파일 제출',
          files,
          { onProgress, onFileProgress, onFileSettled },
        )
        return { textResult: null, fileResults }
      }
      return { textResult: null, fileResults: [] as CreatedSubmission[] }
    },
    // 일부 파일만 성공해도 실제로 저장된 개수를 반영해야 하므로 성공/실패 모두 새로고침합니다.
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) })
      void queryClient.invalidateQueries({ queryKey: ['projects'] })
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboard })
    },
  })
}

export function useDeleteSubmission(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (submissionId: string) => {
      // 서버는 스냅샷 provenance를 보호하기 위해 open 세션에서만 문서 삭제를
      // 허용합니다. 분석 완료 화면(ready/needs_attention)에서 삭제를 누른 경우
      // 명시적으로 세션을 편집 상태로 되돌린 뒤 같은 제출물을 삭제합니다.
      const session = await get<BackendSession>(`/sessions/${projectId}`)
      if (session.state === 'ready' || session.state === 'needs_attention') {
        await mutate('post', `/sessions/${projectId}/reopen`)
      }
      await mutate('delete', `/submissions/${submissionId}`, {})
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.analysis(projectId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.analysisProgress(projectId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.merged(projectId) }),
      ])
    },
  })
}

/** 이미 분석된(ready/needs_attention) 프로젝트를 다시 open 상태로 되돌립니다 — 재분석/증강의 첫 단계. */
export function useReopenSession(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      await mutate('post', `/sessions/${projectId}/reopen`)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) })
    },
  })
}

export function useStartAnalysis(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (excludedRevisionIds: string[] = []) => {
      await mutate('post', `/sessions/${projectId}/close`, {
        exclusions: excludedRevisionIds.map((revisionId) => ({
          revision_id: revisionId,
          reason: '문서 처리에 실패해 분석에서 제외했습니다.',
        })),
      })
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.analysis(projectId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.analysisProgress(projectId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.merged(projectId) })
    },
  })
}

export function useRetryExtraction(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (revisionId: string) => {
      await mutate('post', `/source-revisions/${revisionId}/retry-extraction`)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) })
    },
  })
}

export function useRetryAnalysis(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      await mutate('post', `/sessions/${projectId}/retry`, {})
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.analysis(projectId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.analysisProgress(projectId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.merged(projectId) })
    },
  })
}

export function useResolveSuggestion(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      suggestionId,
      decision,
    }: {
      suggestionId: string
      decision: 'accepted' | 'rejected'
    }) => {
      await mutate('post', `/suggestions/${suggestionId}/resolve`, { decision })
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.merged(projectId) })
    },
  })
}

/** 업로드 문서의 RAG anchor를 다시 확인해 Grok 편집 제안을 생성합니다. */
export function useRunGrokEditTask(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (instruction: string) =>
      mutate<BackendSuggestion[]>(
        'post',
        `/sessions/${projectId}/grok-edit-suggestions`,
        { instruction },
        { timeout: 60_000 },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.merged(projectId) })
    },
  })
}
