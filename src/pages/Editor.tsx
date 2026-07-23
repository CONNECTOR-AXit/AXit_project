import { AnimatePresence, motion } from 'framer-motion'
import {
  Check,
  ChevronDown,
  Cloud,
  Download,
  Eye,
  History,
  Loader2,
  MessageSquare,
  Pencil,
  Share2,
  Sparkles,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'

import { useMergedDocument } from '@/api/queries'
import { PageHeader } from '@/components/common/PageHeader'
import { UserAvatar } from '@/components/common/UserAvatar'
import { AiSuggestionPanel } from '@/components/editor/AiSuggestionPanel'
import { DocumentCanvas } from '@/components/editor/DocumentCanvas'
import { EditorToolbar } from '@/components/editor/EditorToolbar'
import { OutlinePanel } from '@/components/editor/OutlinePanel'
import { VersionHistory } from '@/components/editor/VersionHistory'
import { PageTransition } from '@/components/layout/PageTransition'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsListPill, TabsTriggerPill } from '@/components/ui/tabs'
import { documentComments, documentSources } from '@/data/editor'
import { users } from '@/data/members'
import { projectById } from '@/data/projects'
import { useAutosave } from '@/hooks/useAutosave'
import { formatTime } from '@/lib/format'
import type { AiSuggestion } from '@/types'

export default function Editor() {
  const { projectId = 'p-1' } = useParams<{ projectId: string }>()
  const { data, isLoading } = useMergedDocument(projectId)
  const project = projectById(projectId)

  const [dismissed, setDismissed] = useState<string[]>([])
  const [activeBlockId, setActiveBlockId] = useState<string>()
  const [previewMode, setPreviewMode] = useState(false)
  const { state: saveState, savedAt, touch } = useAutosave()

  const suggestions = useMemo(
    () => (data?.suggestions ?? []).filter((item) => !dismissed.includes(item.id)),
    [data?.suggestions, dismissed],
  )

  const applySuggestion = (suggestion: AiSuggestion) => {
    setDismissed((prev) => [...prev, suggestion.id])
    touch()
  }

  const applyAll = () => {
    setDismissed((data?.suggestions ?? []).map((item) => item.id))
    touch()
  }

  const scrollToBlock = (id: string) => {
    setActiveBlockId(id)
    document.getElementById(`block-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
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
            <SaveIndicator state={saveState} savedAt={savedAt} />
          </span>
        }
        actions={
          <>
            <div className="mr-1 hidden items-center -space-x-2 sm:flex">
              {users.slice(0, 3).map((user) => (
                <UserAvatar key={user.id} user={user} size="sm" />
              ))}
            </div>
            <Button variant="ghost" onClick={() => setPreviewMode((v) => !v)}>
              <Eye />
              {previewMode ? '편집 모드' : '미리보기'}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline">
                  <Download />
                  다운로드
                  <ChevronDown className="size-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem>PDF (.pdf)</DropdownMenuItem>
                <DropdownMenuItem>Word (.docx)</DropdownMenuItem>
                <DropdownMenuItem>한글 (.hwp)</DropdownMenuItem>
                <DropdownMenuItem>마크다운 (.md)</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button variant="primary">
              <Share2 />
              공유하기
            </Button>
          </>
        }
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_330px] 2xl:grid-cols-[minmax(0,1fr)_330px_232px]">
        {/* 편집 표면 */}
        <Card className="flex min-w-0 flex-col overflow-hidden p-0">
          {!previewMode && <EditorToolbar onCommand={touch} />}
          <div className="max-h-[calc(100vh-260px)] min-h-[520px] flex-1 overflow-y-auto bg-canvas/40">
            <div className="my-6 rounded-xl border border-line bg-white shadow-soft sm:mx-6">
              <DocumentCanvas
                blocks={doc.blocks}
                activeBlockId={activeBlockId}
                onSelectBlock={setActiveBlockId}
                onEdit={touch}
                editable={!previewMode}
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3 border-t border-line px-4 py-2.5 text-[11.5px] text-ink-subtle">
            <span>{doc.wordCount.toLocaleString('ko-KR')}자</span>
            <span>·</span>
            <span>원본 문서 5개</span>
            <span>·</span>
            <span>버전 {doc.version}</span>
            <Badge variant="secondary" className="ml-auto">
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
                  댓글 ({documentComments.length})
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
                  onApply={applySuggestion}
                  onApplyAll={applyAll}
                  className="h-full"
                />
              </TabsContent>

              <TabsContent value="source" className="h-full overflow-y-auto p-4">
                <p className="text-[12px] leading-5 text-ink-muted">
                  이 통합 문서는 아래 5개 문서에서 만들어졌습니다.
                </p>
                <ul className="mt-3 space-y-2">
                  {documentSources.map((source) => (
                    <li
                      key={source.name}
                      className="flex items-center gap-2 rounded-lg border border-line px-3 py-2.5"
                    >
                      <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold text-ink">
                        {source.name}
                      </span>
                      <span className="shrink-0 text-[12px] font-bold text-primary tabular-nums">
                        {source.percent}%
                      </span>
                    </li>
                  ))}
                </ul>
              </TabsContent>

              <TabsContent value="comments" className="h-full overflow-y-auto p-4">
                <ul className="space-y-3">
                  {documentComments.map((comment) => (
                    <li key={comment.id} className="rounded-xl border border-line p-3">
                      <div className="flex items-center gap-2">
                        <MessageSquare className="size-3.5 shrink-0 text-ink-subtle" />
                        <span className="text-[12px] font-bold text-ink">{comment.author}</span>
                        <time className="ml-auto text-[11px] text-ink-subtle tabular-nums">
                          {formatTime(comment.createdAt)}
                        </time>
                      </div>
                      <p className="mt-1.5 text-[12.5px] leading-5 text-ink-muted">{comment.body}</p>
                      <button
                        type="button"
                        onClick={() => {
                          const target = doc.blocks.find(
                            (block) => block.type === 'heading' && block.text === comment.section,
                          )
                          if (target) scrollToBlock(target.id)
                        }}
                        className="mt-2 text-[11px] font-bold text-primary hover:underline"
                      >
                        {comment.section} →
                      </button>
                    </li>
                  ))}
                </ul>
              </TabsContent>

              <TabsContent value="history" className="h-full overflow-y-auto p-3">
                <VersionHistory versions={versions} />
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
          <OutlinePanel blocks={doc.blocks} activeId={activeBlockId} onSelect={scrollToBlock} />
          <div className="mt-4 rounded-xl border border-primary-100 bg-primary-50/60 p-3">
            <p className="flex items-center gap-1.5 text-[12px] font-bold text-primary">
              <Sparkles className="size-3.5" />
              남은 제안 {suggestions.length}건
            </p>
            <p className="mt-1 text-[11.5px] leading-4 text-ink-muted">
              AI 추천 탭에서 한 번에 적용할 수 있어요.
            </p>
          </div>
        </Card>
      </div>
    </PageTransition>
  )
}

function SaveIndicator({
  state,
  savedAt,
}: {
  state: ReturnType<typeof useAutosave>['state']
  savedAt: Date | null
}) {
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
