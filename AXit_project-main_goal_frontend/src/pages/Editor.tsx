import { AnimatePresence, motion } from 'framer-motion'
import {
  AlertCircle,
  BarChart3,
  Check,
  Cloud,
  Download,
  Eye,
  FilePlus2,
  History,
  Loader2,
  MessageSquare,
  Pencil,
  RotateCcw,
  Save,
  Sparkles,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api, ApiError } from '@/api/client'
import {
  useCommentActions,
  useComments,
  useAnalysis,
  useCreateMergedDocumentVersion,
  useMergedDocument,
  useProject,
  useReopenSession,
  useResolveSuggestion,
  useSaveMergedDocument,
} from '@/api/queries'
import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { UserAvatar } from '@/components/common/UserAvatar'
import { AiSuggestionPanel } from '@/components/editor/AiSuggestionPanel'
import { CreateVersionDialog } from '@/components/editor/CreateVersionDialog'
import { DocumentCanvas } from '@/components/editor/DocumentCanvas'
import { EditorToolbar } from '@/components/editor/EditorToolbar'
import { GrokEditAgent } from '@/components/editor/GrokEditAgent'
import { OutlinePanel } from '@/components/editor/OutlinePanel'
import { RagEvidenceDialog } from '@/components/editor/RagEvidenceDialog'
import { VersionHistory } from '@/components/editor/VersionHistory'
import { VersionPreviewDialog } from '@/components/editor/VersionPreviewDialog'
import { PageTransition } from '@/components/layout/PageTransition'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsListPill, TabsTriggerPill } from '@/components/ui/tabs'
import {
  DocumentPreviewDialog,
  type PreviewTarget,
} from '@/components/upload/DocumentPreviewDialog'
import { useAutosave } from '@/hooks/useAutosave'
import { useAuth } from '@/hooks/useAuth'
import { formatTime } from '@/lib/format'
import { downloadMergedDocument } from '@/lib/markdown'
import { applySuggestionToBlocks, suggestionTargetBlockId } from '@/lib/suggestionChanges'
import type { AiSuggestion, DocBlock, DocumentVersion } from '@/types'

export default function Editor() {
  const { projectId = 'p-1' } = useParams<{ projectId: string }>()
  const mergedDocumentQuery = useMergedDocument(projectId)
  const { data, isLoading, isError } = mergedDocumentQuery
  const projectQuery = useProject(projectId)
  const analysisQuery = useAnalysis(projectId)
  const resolveSuggestion = useResolveSuggestion(projectId)
  const comments = useComments(projectId)
  const commentActions = useCommentActions(projectId)
  const { user } = useAuth()
  const project = projectQuery.data?.project
  const projectDocuments = projectQuery.data?.documents ?? []
  const contributionByDocumentId = useMemo(
    () =>
      new Map(
        (analysisQuery.data?.breakdown ?? []).map((document) => [
          document.documentId,
          document.contribution,
        ]),
      ),
    [analysisQuery.data?.breakdown],
  )
  const navigate = useNavigate()
  const reopenSession = useReopenSession(projectId)
  const [reopenError, setReopenError] = useState<string | null>(null)
  const refreshGrokSuggestions = () => void mergedDocumentQuery.refetch()

  // 재분석/증강 둘 다 먼저 세션을 다시 열어야(reopen) 새 자료를 받을 수
  // 있습니다 — 이미 분석이 끝난 세션은 재오픈 전까지 제출을 받지 않습니다.
  const reopenThenGo = async (to: string) => {
    setReopenError(null)
    try {
      await reopenSession.mutateAsync()
      navigate(to)
    } catch (error) {
      setReopenError(error instanceof ApiError ? error.message : '세션을 다시 열지 못했습니다.')
    }
  }

  const [dismissed, setDismissed] = useState<string[]>([])
  const [reviewingSuggestionIds, setReviewingSuggestionIds] = useState<string[]>([])
  const [resolvingSuggestionId, setResolvingSuggestionId] = useState<string>()
  const [suggestionErrorId, setSuggestionErrorId] = useState<string>()
  const [suggestionError, setSuggestionError] = useState<string | null>(null)
  const [activeBlockId, setActiveBlockId] = useState<string>()
  const [previewMode, setPreviewMode] = useState(false)
  const [selectedRagAnchorId, setSelectedRagAnchorId] = useState<string | null>(null)
  const [originalPreview, setOriginalPreview] = useState<PreviewTarget | null>(null)
  const [ragAnchorLabels, setRagAnchorLabels] = useState<Record<string, string>>({})
  const [commentBody, setCommentBody] = useState('')
  const [mentionedUserId, setMentionedUserId] = useState('')
  const [commentRequestId, setCommentRequestId] = useState(() => crypto.randomUUID())
  const [editingCommentId, setEditingCommentId] = useState<string>()
  const [editingBody, setEditingBody] = useState('')
  const mentionCandidates = (project?.members ?? []).filter((member) => member.id !== user?.id)

  // 편집 중인 블록 — 서버에서 새 버전을 받았을 때만(예: 저장 성공, 다른 사람의
  // 수정) 동기화합니다. 그 외에는 타이핑 중인 내용을 그대로 유지합니다.
  const [blocks, setBlocks] = useState<DocBlock[]>([])
  const blocksRef = useRef<DocBlock[]>(blocks)
  blocksRef.current = blocks
  const syncedVersionRef = useRef<number | null>(null)
  useEffect(() => {
    if (!data) return
    if (syncedVersionRef.current === data.document.saveVersion) return
    syncedVersionRef.current = data.document.saveVersion
    setBlocks(data.document.blocks)
  }, [data])

  useEffect(() => {
    if (!data) return
    const anchorIds = extractDocumentRagAnchorIds(data.document.blocks)
    if (anchorIds.length === 0) {
      setRagAnchorLabels({})
      return
    }
    let cancelled = false
    const documents = projectQuery.data?.documents ?? []
    void Promise.all(
      anchorIds.map(async (anchorId) => {
        try {
          const response = await api.get<{
            source_anchor_id: string
            source_revision_id: string
            exact_quote: string
          }>(`/source-anchors/${anchorId}/resolve`)
          const source = documents.find(
            (document) => document.revisionId === response.data.source_revision_id,
          )
          return [anchorId, source?.name ?? '원본 문서'] as const
        } catch {
          return [anchorId, '근거 문서'] as const
        }
      }),
    ).then((entries) => {
      if (!cancelled) setRagAnchorLabels(Object.fromEntries(entries))
    })
    return () => {
      cancelled = true
    }
  }, [data, projectQuery.data?.documents])

  const saveMergedDocument = useSaveMergedDocument(projectId)
  const { state: saveState, savedAt, errorMessage: saveErrorMessage, touch, saveNow } = useAutosave({
    enabled: Boolean(data),
    save: async () => {
      if (!data) return
      try {
        await saveMergedDocument.mutateAsync({
          blocks: blocksRef.current,
          expectedVersion: data.document.saveVersion,
        })
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          throw new Error('다른 사람이 방금 이 문서를 수정했어요. 새로고침 후 다시 편집해 주세요.')
        }
        throw error instanceof ApiError ? new Error(error.message) : error
      }
    },
  })

  const onBlockTextChange = (blockId: string, text: string) => {
    setBlocks((prev) =>
      prev.map((block) => {
        if (block.id !== blockId) return block
        if (block.type === 'heading' || block.type === 'paragraph') return { ...block, text }
        return block
      }),
    )
    touch()
  }

  // 자동 저장(디바운스)에 더해, Ctrl/Cmd+S로 항상 즉시 저장할 수 있게 합니다.
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        saveNow()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [saveNow])

  const createVersion = useCreateMergedDocumentVersion(projectId)
  const [versionError, setVersionError] = useState<string | null>(null)
  const [isVersionDialogOpen, setIsVersionDialogOpen] = useState(false)
  const [previewVersion, setPreviewVersion] = useState<DocumentVersion | null>(null)
  const defaultVersionLabel = `버전 · ${new Date().toLocaleString('ko-KR', {
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })}`
  const handleAddVersion = () => {
    if (!data) return
    setVersionError(null)
    setIsVersionDialogOpen(true)
  }
  const handleConfirmVersion = async (label: string) => {
    if (!data) return
    setVersionError(null)
    try {
      // "현재 문서"가 실제로 화면에 보이는 내용을 뜻하도록, 저장되지 않은
      // 변경사항이 있으면 버전을 남기기 전에 먼저 저장합니다.
      if (saveState === 'pending' || saveState === 'error') {
        await saveMergedDocument.mutateAsync({
          blocks: blocksRef.current,
          expectedVersion: data.document.saveVersion,
        })
      }
      await createVersion.mutateAsync({ label })
      setIsVersionDialogOpen(false)
    } catch (error) {
      setVersionError(error instanceof ApiError ? error.message : '버전을 저장하지 못했습니다.')
    }
  }

  const changeCommentDraft = (next: { body?: string; mentionedUserId?: string }) => {
    if (commentActions.create.isError) {
      commentActions.create.reset()
      setCommentRequestId(crypto.randomUUID())
    }
    if (next.body !== undefined) setCommentBody(next.body)
    if (next.mentionedUserId !== undefined) setMentionedUserId(next.mentionedUserId)
  }

  const suggestions = useMemo(
    () => (data?.suggestions ?? []).filter((item) => !dismissed.includes(item.id)),
    [data?.suggestions, dismissed],
  )

  const applySuggestion = async (suggestion: AiSuggestion) => {
    if (!data || resolvingSuggestionId) return
    setResolvingSuggestionId(suggestion.id)
    setSuggestionErrorId(undefined)
    setSuggestionError(null)
    try {
      const nextBlocks = applySuggestionToBlocks(blocksRef.current, suggestion)
      if (nextBlocks === blocksRef.current && suggestion.kind !== 'add') {
        throw new Error('이 제안이 가리키는 본문을 찾지 못했습니다. 문서를 새로고침한 뒤 다시 시도해 주세요.')
      }
      if (nextBlocks !== blocksRef.current) {
        setBlocks(nextBlocks)
        blocksRef.current = nextBlocks
        await saveMergedDocument.mutateAsync({
          blocks: nextBlocks,
          expectedVersion: data.document.saveVersion,
        })
      }
      await resolveSuggestion.mutateAsync({ suggestionId: suggestion.id, decision: 'accepted' })
      setDismissed((prev) => [...prev, suggestion.id])
      setReviewingSuggestionIds((prev) => prev.filter((id) => id !== suggestion.id))
    } catch (error) {
      setSuggestionErrorId(suggestion.id)
      setSuggestionError(
        error instanceof ApiError
          ? error.message
          : error instanceof Error
            ? error.message
            : '제안을 통합문서에 반영하지 못했습니다.',
      )
    } finally {
      setResolvingSuggestionId(undefined)
    }
  }

  const rejectSuggestion = async (suggestion: AiSuggestion) => {
    if (resolvingSuggestionId) return
    setResolvingSuggestionId(suggestion.id)
    setSuggestionErrorId(undefined)
    setSuggestionError(null)
    try {
      await resolveSuggestion.mutateAsync({ suggestionId: suggestion.id, decision: 'rejected' })
      setDismissed((prev) => [...prev, suggestion.id])
      setReviewingSuggestionIds((prev) => prev.filter((id) => id !== suggestion.id))
    } catch (error) {
      setSuggestionErrorId(suggestion.id)
      setSuggestionError(error instanceof ApiError ? error.message : '제안 거절 결과를 저장하지 못했습니다.')
    } finally {
      setResolvingSuggestionId(undefined)
    }
  }

  const reviewSuggestion = (suggestion: AiSuggestion) => {
    setReviewingSuggestionIds((prev) =>
      prev.includes(suggestion.id) ? prev : [...prev, suggestion.id],
    )
    const blockId = suggestionTargetBlockId(blocks, suggestion)
    if (blockId) setActiveBlockId(blockId)
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        document
          .getElementById(`suggestion-${suggestion.id}`)
          ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      })
    })
  }

  const scrollToBlock = (id: string) => {
    setActiveBlockId(id)
    document.getElementById(`block-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  if (isError) {
    return (
      <PageTransition className="space-y-5">
        <EmptyState
          icon={Loader2}
          title="통합 문서가 아직 준비되지 않았어요"
          description="AI가 문서를 통합하는 중일 수 있어요. 잠시 후 자동으로 다시 확인합니다."
        />
      </PageTransition>
    )
  }

  if (isLoading || !data) {
    return (
      <PageTransition className="space-y-5">
        <Skeleton className="h-9 w-96" />
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px_240px]">
          <Skeleton className="h-[600px] rounded-xl" />
          <Skeleton className="h-[600px] rounded-xl" />
          <Skeleton className="hidden h-[600px] rounded-xl xl:block" />
        </div>
      </PageTransition>
    )
  }

  const { document: doc, versions } = data

  return (
    <PageTransition className="space-y-5">
      <PageHeader
        breadcrumbs={[
          { label: '프로젝트', to: '/projects' },
          { label: project?.name ?? '프로젝트', to: `/projects/${projectId}` },
          { label: '통합 문서 편집' },
        ]}
        title={
          <span className="flex flex-wrap items-center gap-2">
            {doc.title}
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="문서 제목 수정"
              className="shrink-0 text-ink-subtle"
            >
              <Pencil className="size-3.5" />
            </Button>
            <SaveIndicator
              state={saveState}
              savedAt={savedAt}
              errorMessage={saveErrorMessage}
              onRetry={saveNow}
            />
          </span>
        }
        actions={
          <>
            <div className="mr-1 hidden items-center -space-x-2 sm:flex">
              {(project?.members ?? []).slice(0, 3).map((member) => (
                <UserAvatar key={member.id} user={member} size="sm" />
              ))}
            </div>
            <Button
              variant="outline"
              disabled={saveState === 'saving' || saveState === 'idle' || saveState === 'saved'}
              onClick={saveNow}
            >
              {saveState === 'saving' ? <Loader2 className="animate-spin" /> : <Save />}
              저장
            </Button>
            <Button variant="ghost" onClick={() => setPreviewMode((v) => !v)}>
              <Eye />
              {previewMode ? '편집 모드' : '미리보기'}
            </Button>
            <Button asChild variant="outline">
              <Link to={`/projects/${projectId}/analysis/result`}>
                <BarChart3 />
                분석 결과
              </Link>
            </Button>
            <Button
              variant="outline"
              disabled={reopenSession.isPending}
              onClick={() => void reopenThenGo(`/projects/${projectId}/upload`)}
            >
              <RotateCcw />
              재분석
            </Button>
            <Button
              variant="outline"
              disabled={reopenSession.isPending}
              onClick={() => void reopenThenGo(`/projects/${projectId}/augment`)}
            >
              <FilePlus2 />
              증강
            </Button>
            <Button variant="outline" onClick={() => downloadMergedDocument(doc)}>
              <Download />
              내보내기
            </Button>
          </>
        }
      />
      {reopenError && (
        <p className="flex items-center gap-2 rounded-lg bg-danger-soft px-3 py-2.5 text-[12.5px] font-semibold text-danger">
          <AlertCircle className="size-4 shrink-0" />
          {reopenError}
        </p>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_330px] 2xl:grid-cols-[minmax(0,1fr)_330px_232px]">
        {/* 편집 표면 */}
        <Card className="flex min-w-0 flex-col overflow-hidden p-0">
          {!previewMode && <EditorToolbar onCommand={touch} />}
          <div className="max-h-[calc(100vh-260px)] min-h-[520px] flex-1 overflow-y-auto bg-canvas/40">
            <div className="my-6 rounded-xl bg-white shadow-soft sm:mx-6">
              <DocumentCanvas
                blocks={blocks}
                activeBlockId={activeBlockId}
                onSelectBlock={setActiveBlockId}
                onSelectRagAnchor={setSelectedRagAnchorId}
                ragAnchorLabels={ragAnchorLabels}
                ragTitleOrder={projectDocuments.map((document) => document.name)}
                suggestions={
                  previewMode
                    ? []
                    : suggestions.filter((suggestion) =>
                        reviewingSuggestionIds.includes(suggestion.id),
                      )
                }
                resolvingSuggestionId={resolvingSuggestionId}
                suggestionErrorId={suggestionErrorId}
                suggestionError={suggestionError}
                onAcceptSuggestion={(suggestion) => void applySuggestion(suggestion)}
                onRejectSuggestion={(suggestion) => void rejectSuggestion(suggestion)}
                onBlockTextChange={onBlockTextChange}
                editable={!previewMode}
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3 border-t border-line px-4 py-2.5 text-[11.5px] text-ink-subtle">
            <span>{doc.wordCount.toLocaleString('ko-KR')}자</span>
            <span>·</span>
            <span>원본 문서 {projectDocuments.length}개</span>
            <span>·</span>
            <span>버전 {doc.version}</span>
            <Badge variant="neutral" className="ml-auto">
              AI 통합 문서
            </Badge>
          </div>
        </Card>

        {/* AI 레일 */}
        <Card className="flex min-w-0 flex-col overflow-hidden p-0">
          <Tabs defaultValue="ai" className="flex min-h-0 flex-1 flex-col gap-0">
            <div className="border-b border-line p-2">
              <TabsListPill className="w-full">
                <TabsTriggerPill value="ai" className="flex-1">
                  AI 추천
                </TabsTriggerPill>
                <TabsTriggerPill value="source" className="flex-1">
                  문서 출처
                </TabsTriggerPill>
                <TabsTriggerPill value="comments" className="flex-1">
                  댓글 ({comments.data?.items.length ?? 0})
                </TabsTriggerPill>
                <TabsTriggerPill value="history" className="flex-1">
                  변경 내역
                </TabsTriggerPill>
              </TabsListPill>
            </div>

            <div className="max-h-[calc(100vh-260px)] min-h-[520px] flex-1 overflow-hidden">
              <TabsContent value="ai" className="h-full">
                <AiSuggestionPanel
                  suggestions={suggestions}
                  reviewingSuggestionIds={reviewingSuggestionIds}
                  onReview={reviewSuggestion}
                  className="h-full"
                />
              </TabsContent>

              <TabsContent value="source" className="h-full overflow-y-auto p-4">
                <p className="text-[12px] leading-5 text-ink-muted">
                  이 통합 문서는 아래 {projectDocuments.length}개 문서에서 만들어졌습니다.
                </p>
                <ul className="mt-3 space-y-2">
                  {projectDocuments.map((source) => (
                    <li
                      key={source.id}
                      className="flex items-center gap-2 rounded-lg bg-line-soft px-3 py-2.5"
                    >
                      <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold text-ink">
                        {source.name}
                      </span>
                      <span className="shrink-0 text-[12px] font-bold text-primary tabular-nums">
                        {contributionByDocumentId.get(source.id) ?? 0}%
                      </span>
                    </li>
                  ))}
                </ul>
              </TabsContent>

              <TabsContent value="comments" className="h-full overflow-y-auto p-4">
                <form
                  className="mb-4 space-y-2 border-b border-line-soft pb-4"
                  onSubmit={(event) => {
                    event.preventDefault()
                    if (!commentBody.trim()) return
                    commentActions.create.mutate({
                      body: commentBody.trim(),
                      client_request_id: commentRequestId,
                      mentioned_user_ids: mentionedUserId ? [mentionedUserId] : [],
                    }, { onSuccess: () => { setCommentBody(''); setMentionedUserId(''); setCommentRequestId(crypto.randomUUID()) } })
                  }}
                >
                  <Input value={commentBody} onChange={(event) => changeCommentDraft({ body: event.target.value })} placeholder="댓글을 입력하세요" aria-label="댓글 내용" maxLength={5000} disabled={commentActions.create.isPending} />
                  <div className="flex gap-2">
                    <select className="min-w-0 flex-1 rounded-md border border-line bg-white px-3 text-[12px]" value={mentionedUserId} onChange={(event) => changeCommentDraft({ mentionedUserId: event.target.value })} aria-label="멘션할 멤버 UUID 선택" disabled={projectQuery.isLoading || projectQuery.isError || mentionCandidates.length === 0 || commentActions.create.isPending}>
                      <option value="">{projectQuery.isLoading ? '멤버를 불러오는 중' : projectQuery.isError ? '멤버를 불러오지 못함' : mentionCandidates.length === 0 ? '멘션 가능 멤버 없음' : '멘션 없음'}</option>
                      {mentionCandidates.map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}
                    </select>
                    <Button type="submit" size="sm" disabled={commentActions.create.isPending || !commentBody.trim()}>등록</Button>
                  </div>
                  {projectQuery.isError && <p role="alert" className="text-[11px] text-danger">멤버를 불러오지 못했습니다. <button type="button" className="underline" onClick={() => void projectQuery.refetch()}>다시 시도</button></p>}
                  {commentActions.create.isError && <p role="alert" className="text-[11px] text-danger">댓글 저장 결과를 확인하지 못했습니다. 내용을 바꾸지 않고 다시 등록하면 같은 요청 ID로 안전하게 재시도합니다.</p>}
                </form>
                {comments.isLoading ? <p className="text-[12px] text-ink-muted">댓글을 불러오는 중입니다.</p> : comments.isError ? <p role="alert" className="text-[12px] text-danger">댓글을 불러오지 못했습니다.</p> : comments.data?.items.length === 0 ? <p className="text-[12px] text-ink-muted">아직 댓글이 없습니다.</p> : null}
                <ul className="space-y-3">
                  {(comments.data?.items ?? []).map((comment) => (
                    <li key={comment.id} className="rounded-xl bg-line-soft p-3">
                      <div className="flex items-center gap-2">
                        <MessageSquare className="size-3.5 shrink-0 text-ink-subtle" />
                        <span className="text-[12px] font-bold text-ink">{project?.members.find((member) => member.id === comment.author_id)?.name ?? `사용자 ${comment.author_id.slice(0, 8)}`}</span>
                        <time className="ml-auto text-[11px] text-ink-subtle tabular-nums">
                          {formatTime(comment.created_at)}
                        </time>
                      </div>
                      {editingCommentId === comment.id ? <Input className="mt-2" value={editingBody} onChange={(event) => setEditingBody(event.target.value)} aria-label="댓글 수정 내용" /> : <p className="mt-1.5 text-[12.5px] leading-5 text-ink-muted">{comment.deleted_at ? '삭제된 댓글입니다.' : comment.body}</p>}
                      {comment.mentioned_user_ids.length > 0 && <p className="mt-1 text-[11px] text-primary">멘션 {comment.mentioned_user_ids.length}명</p>}
                      {comment.author_id === user?.id && !comment.deleted_at && (
                        <div className="mt-2 flex gap-2">
                          {editingCommentId === comment.id ? <Button size="sm" variant="ghost" disabled={commentActions.update.isPending || !editingBody.trim()} onClick={() => commentActions.update.mutate({ id: comment.id, payload: { body: editingBody, expected_version: comment.version, anchor_id: comment.anchor_id, anchor_kind: comment.anchor_kind, mentioned_user_ids: comment.mentioned_user_ids } }, { onSuccess: () => setEditingCommentId(undefined) })}>수정 저장</Button> : <Button size="sm" variant="ghost" disabled={commentActions.update.isPending || commentActions.remove.isPending} onClick={() => { commentActions.update.reset(); setEditingCommentId(comment.id); setEditingBody(comment.body) }}>수정</Button>}
                          <Button size="sm" variant="ghost" disabled={commentActions.remove.isPending || commentActions.update.isPending} onClick={() => commentActions.remove.mutate({ id: comment.id, payload: { expected_version: comment.version } })}>{commentActions.remove.isPending ? '삭제 중…' : '삭제'}</Button>
                        </div>
                      )}
                      {comment.author_id === user?.id && commentActions.update.isError && commentActions.update.variables?.id === comment.id && <p role="alert" className="mt-2 text-[11px] text-danger">댓글을 수정하지 못했습니다. 최신 버전을 확인한 뒤 다시 시도해 주세요.</p>}
                      {comment.author_id === user?.id && commentActions.remove.isError && commentActions.remove.variables?.id === comment.id && <p role="alert" className="mt-2 text-[11px] text-danger">댓글을 삭제하지 못했습니다. 최신 버전을 확인한 뒤 다시 시도해 주세요.</p>}
                    </li>
                  ))}
                </ul>
              </TabsContent>

              <TabsContent value="history" className="h-full overflow-y-auto p-3">
                {versionError && (
                  <p className="mb-2 flex items-center gap-2 rounded-lg bg-danger-soft px-3 py-2 text-[11.5px] font-semibold text-danger">
                    <AlertCircle className="size-3.5 shrink-0" />
                    {versionError}
                  </p>
                )}
                <VersionHistory
                  versions={versions.map((version) => ({
                    ...version,
                    author:
                      project?.members.find((member) => member.id === version.author)?.name ??
                      `사용자 ${version.author.slice(0, 8)}`,
                  }))}
                  onCreateVersion={handleAddVersion}
                  isCreating={createVersion.isPending || saveMergedDocument.isPending}
                  onSelectVersion={setPreviewVersion}
                />
              </TabsContent>
            </div>
          </Tabs>
        </Card>

        {/* 목차 레일 — 3열이 들어갈 여유가 있을 때만 */}
        <Card className="hidden h-fit p-4 2xl:block">
          <p className="mb-2.5 flex items-center gap-1.5 px-1 text-[12.5px] font-bold text-ink">
            <History className="size-3.5 text-ink-subtle" />
            문서 구조
          </p>
          <OutlinePanel blocks={blocks} activeId={activeBlockId} onSelect={scrollToBlock} />
          <GrokEditAgent
            projectId={projectId}
            onSuggestionsCreated={refreshGrokSuggestions}
          />
          <div className="mt-4 rounded-xl border border-primary-100 bg-primary-50/60 p-3">
            <p className="flex items-center gap-1.5 text-[12px] font-bold text-primary">
              <Sparkles className="size-3.5" />
              남은 제안 {suggestions.length}건
            </p>
            <p className="mt-1 text-[11.5px] leading-4 text-ink-muted">
              본문의 ✓ 또는 ×로 제안별 적용 여부를 결정하세요.
            </p>
          </div>
        </Card>
      </div>

      <RagEvidenceDialog
        anchorId={selectedRagAnchorId}
        documents={projectDocuments}
        onClose={() => setSelectedRagAnchorId(null)}
        onOpenOriginal={setOriginalPreview}
      />
      <DocumentPreviewDialog
        target={originalPreview}
        onOpenChange={(open) => !open && setOriginalPreview(null)}
      />
      <CreateVersionDialog
        open={isVersionDialogOpen}
        onOpenChange={setIsVersionDialogOpen}
        defaultLabel={defaultVersionLabel}
        isSubmitting={createVersion.isPending || saveMergedDocument.isPending}
        errorMessage={versionError}
        onConfirm={(label) => void handleConfirmVersion(label)}
      />
      <VersionPreviewDialog
        projectId={projectId}
        version={previewVersion}
        onClose={() => setPreviewVersion(null)}
      />
    </PageTransition>
  )
}

function extractDocumentRagAnchorIds(blocks: DocBlock[]) {
  const ids = new Set<string>()
  const pattern = /\[RAG:([0-9a-f]{8}-[0-9a-f-]{27})\]/gi
  for (const block of blocks) {
    if (block.type !== 'heading' && block.type !== 'paragraph' && block.type !== 'callout') continue
    for (const match of block.text.matchAll(pattern)) ids.add(match[1]!)
  }
  return [...ids]
}

function SaveIndicator({
  state,
  savedAt,
  errorMessage,
  onRetry,
}: {
  state: ReturnType<typeof useAutosave>['state']
  savedAt: Date | null
  errorMessage: string | null
  onRetry: () => void
}) {
  if (state === 'idle') return null

  if (state === 'error') {
    return (
      <AnimatePresence mode="wait">
        <motion.button
          key="error"
          type="button"
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.18 }}
          onClick={onRetry}
          title={errorMessage ?? '저장하지 못했습니다.'}
          className="flex items-center gap-1 rounded-md bg-danger-soft px-2 py-1 text-[11.5px] font-bold text-danger hover:brightness-95"
        >
          <AlertCircle className="size-3" />
          저장 실패 · 다시 시도
        </motion.button>
      </AnimatePresence>
    )
  }

  const content =
    state === 'saving' ? (
      <>
        <Loader2 className="size-3 animate-spin" />
        저장 중...
      </>
    ) : state === 'pending' ? (
      <>
        <Cloud className="size-3" />
        변경사항 있음
      </>
    ) : (
      <>
        <Check className="size-3" />
        자동 저장됨 {savedAt ? formatTime(savedAt.toISOString()) : ''}
      </>
    )

  return (
    <AnimatePresence mode="wait">
      <motion.span
        key={state}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.18 }}
        className={
          state === 'pending'
            ? 'flex items-center gap-1 rounded-md bg-warning-soft px-2 py-1 text-[11.5px] font-bold text-warning'
            : 'flex items-center gap-1 rounded-md bg-secondary-50 px-2 py-1 text-[11.5px] font-bold text-secondary-600'
        }
      >
        {content}
      </motion.span>
    </AnimatePresence>
  )
}
