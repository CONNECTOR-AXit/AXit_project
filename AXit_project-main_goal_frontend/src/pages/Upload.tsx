import { AlertCircle, ArrowRight, ChevronDown, FilePlus2, FileUp, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'

import { ApiError } from '@/api/client'
import {
  useDeleteSubmission,
  useProject,
  useRetryExtraction,
  useStartAnalysis,
  useUploadDocuments,
} from '@/api/queries'
import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { PageTransition } from '@/components/layout/PageTransition'
import { DocumentPreviewDialog, type PreviewTarget } from '@/components/upload/DocumentPreviewDialog'
import { Dropzone } from '@/components/upload/Dropzone'
import { NotionTextEditor } from '@/components/upload/NotionTextEditor'
import { UploadList } from '@/components/upload/UploadList'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { formatBytes } from '@/lib/format'
import { useUploadQueue, type UploadItem } from '@/hooks/useUploadQueue'
import type { DocumentFile, Project } from '@/types'

const MAX_FILES = 20

function documentToUploadItem(doc: DocumentFile): UploadItem {
  return {
    id: doc.id,
    name: doc.name,
    kind: doc.kind,
    size: doc.size,
    // doc.status/progress를 그대로 씁니다 — 서버 처리(추출)가 아직 끝나지
    // 않은 문서를 여기서 'analyzed'로 뭉개면, "AI 분석 시작" 버튼이 실제로는
    // 아직 처리 중인 문서를 두고도 눌려서 서버의 close()가 409로 거부합니다.
    progress: doc.progress,
    status: doc.status,
    addedAt: doc.uploadedAt,
    revisionId: doc.revisionId,
    mimeType: doc.mimeType,
    submissionKind: doc.submissionKind,
  }
}

export interface UploadProps {
  /**
   * 'augment'면 "재분석"이 아니라 "증강"에서 온 것 — 이미 분석된 자료에
   * 새 자료를 더하는 흐름이라는 걸 문구로만 알려줍니다. 실제 동작(업로드
   * 큐, 분석 시작)은 두 모드가 완전히 동일합니다 — 어차피 이 화면에 온
   * 시점엔 세션이 이미 다시 열려(open) 있어서, 기존 문서 + 새 문서를
   * 함께 다시 분석하는 것뿐입니다.
   */
  mode?: 'upload' | 'augment'
}

/** 프로젝트별 문서 업로드 화면 — /projects/:projectId/upload, /augment. */
export default function Upload({ mode = 'upload' }: UploadProps = {}) {
  const { projectId } = useParams<{ projectId: string }>()
  const { data, isLoading, isError } = useProject(projectId)

  // 없는 프로젝트는 목록으로 돌려보냅니다 (ProjectDetail과 같은 규칙).
  if (isError) return <Navigate to="/projects" replace />

  if (isLoading || !data) {
    return (
      <PageTransition className="space-y-6">
        <Skeleton className="h-9 w-72" />
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
          <Skeleton className="h-[220px] rounded-xl" />
          <Skeleton className="h-[220px] rounded-xl" />
        </div>
      </PageTransition>
    )
  }

  // project.id로 key를 주어, 다른 프로젝트의 업로드 화면으로 이동할 때
  // 업로드 큐 상태가 이전 프로젝트 걸 들고 있지 않고 완전히 새로 시작됩니다.
  return (
    <UploadWorkspace
      key={data.project.id}
      project={data.project}
      documents={data.documents}
      mode={mode}
    />
  )
}

function UploadWorkspace({
  project,
  documents,
  mode,
}: {
  project: Project
  documents: DocumentFile[]
  mode: 'upload' | 'augment'
}) {
  const navigate = useNavigate()
  const uploadDocuments = useUploadDocuments(project.id)
  const startAnalysis = useStartAnalysis(project.id)
  const retryExtraction = useRetryExtraction(project.id)
  const deleteSubmission = useDeleteSubmission(project.id)
  const serverItems = useMemo(() => documents.map(documentToUploadItem), [documents])
  const {
    items,
    add,
    remove,
    updateProgress,
    markUploaded,
    markFailed,
    sync,
    isUploading,
    lastError,
  } = useUploadQueue({
    maxFiles: MAX_FILES,
    initial: serverItems,
  })
  const [mdTitle, setMdTitle] = useState('')
  const [mdContent, setMdContent] = useState('')
  const [isDirectWriteOpen, setIsDirectWriteOpen] = useState(true)
  const [previewTarget, setPreviewTarget] = useState<PreviewTarget | null>(null)

  // 다른 화면(대시보드/헤더의 "문서 업로드" 바로가기 등)이 "최근에 보던
  // 프로젝트"로 돌아올 수 있도록 활성 프로젝트를 계속 최신 상태로 둡니다.
  useEffect(() => {
    sessionStorage.setItem('axit:active-project-id', project.id)
  }, [project.id])

  // 서버가 폴링으로 다시 읽어온 문서 상태(처리 완료/실패 등)를 화면에도
  // 반영합니다 — 안 그러면 새로고침해야만 최신 상태가 보입니다.
  useEffect(() => {
    sync(serverItems)
  }, [serverItems, sync])

  const totals = useMemo(() => {
    const bytes = items.reduce((sum, item) => sum + item.size, 0)
    const done = items.filter((item) => item.progress >= 100).length
    return { bytes, done }
  }, [items])

  // 서버 처리(추출)가 끝나 'analyzed'(ready) 또는 'failed'로 확정된 문서만
  // 셉니다. 'queued'/'uploading' 상태로 남은 문서가 있으면 서버의 close()가
  // "아직 준비되지 않은 리비전"으로 보고 409로 거부하므로, 그 문서들이 모두
  // 끝날 때까지 버튼을 눌러도 소용없게 막아둡니다(실패한 문서는 자동 제외).
  const readyCount = items.filter(
    (item) => item.status === 'analyzed' && Boolean(item.revisionId),
  ).length
  const isProcessing = items.some(
    (item) => item.status === 'queued' || item.status === 'uploading',
  )
  const canAnalyze = readyCount >= 2 && !isUploading && !isProcessing

  // 파일 업로드는 한 번에 하나씩만 서버로 보냅니다. addFiles/retryUpload가
  // 겹쳐 호출돼도(여러 번 드롭·재시도 클릭 등) 여기 큐에만 쌓이고, 진행 중인
  // 업로드가 끝난 뒤에야 다음 파일이 시작됩니다 — 두 요청이 동시에 나가면서
  // 생기는 경합(레이스)을 구조적으로 없앱니다.
  const uploadQueueRef = useRef<{ id: string; file: File }[]>([])
  const isDrainingRef = useRef(false)

  const uploadOneFile = async ({ id, file }: { id: string; file: File }) => {
    try {
      const { fileResults } = await uploadDocuments.mutateAsync({
        files: [file],
        // 제목을 안 주면 백엔드가 모든 파일에 "파일 제출"이라는 같은 제목을
        // 붙여서, 실제 파일명 대신 그 문구가 문서 목록에 표시됐습니다.
        title: file.name,
        onFileProgress: (_index, percent) => updateProgress(id, percent),
      })
      const created = fileResults[0]
      markUploaded(
        id,
        created
          ? {
              revisionId: created.current_revision_id,
              mimeType: file.type || 'application/octet-stream',
              submissionKind: 'file',
            }
          : undefined,
      )
    } catch (error) {
      markFailed(id, error instanceof ApiError ? error.message : '업로드에 실패했습니다.')
    }
  }

  const drainUploadQueue = async () => {
    if (isDrainingRef.current) return
    isDrainingRef.current = true
    while (uploadQueueRef.current.length > 0) {
      const next = uploadQueueRef.current.shift()
      if (next) await uploadOneFile(next)
    }
    isDrainingRef.current = false
  }

  const enqueueUploads = (accepted: { item: { id: string }; file: File }[]) => {
    if (accepted.length === 0) return
    uploadQueueRef.current.push(
      ...accepted.map(({ item, file }) => ({ id: item.id, file })),
    )
    void drainUploadQueue()
  }

  const addFiles = (files: FileList | File[]) => {
    const accepted = add(files)
    enqueueUploads(accepted)
  }

  const submitText = (title: string, text: string) => {
    const accepted = add([new File([text], `${title}.md`, { type: 'text/markdown' })])
    if (accepted.length === 0) return
    const { item } = accepted[0]
    uploadDocuments.mutate(
      { title, text },
      {
        onSuccess: ({ textResult }) =>
          markUploaded(
            item.id,
            textResult
              ? {
                  revisionId: textResult.current_revision_id,
                  mimeType: 'text/markdown',
                  submissionKind: 'text',
                  inlineText: text,
                }
              : undefined,
          ),
        onError: (error) =>
          markFailed(item.id, error instanceof ApiError ? error.message : '제출에 실패했습니다.'),
      },
    )
  }

  const submitMarkdown = () => {
    const title = mdTitle.trim()
    if (!title) return
    submitText(title, mdContent)
    setMdTitle('')
    setMdContent('')
  }

  // 실패한 항목은 같은 내용을 다시 보내봐야 대부분 또 실패합니다(예: 손상된
  // 파일) — 그래서 재시도 대신, 실패한 자리를 지우고 새로 고른 파일을 그
  // 자리에 업로드합니다.
  const reuploadItem = (id: string, file: File) => {
    remove(id)
    addFiles([file])
  }

  // 서버에 이미 저장된 문서는 서버에서도 실제로 지워야 새로고침해도 다시
  // 나타나지 않습니다 — 로컬 상태에서만 지우면 목록이 서버 것으로 되돌아갑니다.
  // 아직 서버에 닿지 못한(리비전이 없는) 항목만 로컬에서 바로 지웁니다.
  const deleteItem = async (id: string) => {
    const item = items.find((candidate) => candidate.id === id)
    if (!item?.revisionId) {
      remove(id)
      return
    }
    try {
      await deleteSubmission.mutateAsync(id)
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 404)) return
    }
    remove(id)
  }

  const deleteAll = () => {
    for (const item of items) void deleteItem(item.id)
  }

  const previewItem = (item: UploadItem) => {
    if (!item.revisionId) return
    setPreviewTarget({
      name: item.name,
      mimeType: item.mimeType || 'application/octet-stream',
      revisionId: item.revisionId,
      submissionKind: item.submissionKind ?? 'file',
      inlineText: item.inlineText,
    })
  }

  const uploadError =
    uploadDocuments.error instanceof ApiError ? uploadDocuments.error.message : null
  const analyzeError =
    startAnalysis.error instanceof ApiError ? startAnalysis.error.message : null

  const analyze = async () => {
    // 처리에 실패한 문서는 분석 대상에서 빼고 진행합니다 — 안 그러면 실패한
    // 문서 하나 때문에 분석 시작 자체가 계속 막혀버립니다.
    const excludedRevisionIds = items
      .filter((item) => item.status === 'failed' && item.revisionId)
      .map((item) => item.revisionId as string)
    try {
      await startAnalysis.mutateAsync(excludedRevisionIds)
      navigate(`/projects/${project.id}/analysis`)
    } catch {
      // startAnalysis.error가 메시지를 들고 있으므로 화면에서 그대로 보여줍니다.
    }
  }

  return (
    <PageTransition className="space-y-6">
      <PageHeader
        breadcrumbs={[
          { label: '프로젝트', to: '/projects' },
          { label: project.name, to: `/projects/${project.id}` },
          { label: mode === 'augment' ? '자료 증강' : '문서 업로드' },
        ]}
        title={mode === 'augment' ? '자료 증강' : '문서 업로드'}
        description={
          mode === 'augment'
            ? `"${project.name}" 프로젝트는 이미 AI 분석이 끝났어요. 추가 자료를 더해 분석에 반영하세요.`
            : `"${project.name}" 프로젝트에 통합할 문서를 업로드하세요.`
        }
        actions={
          <Button
            variant="gradient"
            disabled={!canAnalyze}
            onClick={() => void analyze()}
          >
            <Sparkles />
            {mode === 'augment' ? '증강 분석 시작' : 'AI 분석 시작'}
          </Button>
        }
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-5">
          {project.description && (
            <Card className="p-5">
              <p className="text-[12px] font-bold text-ink-subtle">프로젝트 설명</p>
              <p className="mt-1.5 text-[13px] leading-6 whitespace-pre-wrap text-ink-muted">
                {project.description}
              </p>
            </Card>
          )}

          <Card className="p-5">
            <Dropzone onFiles={addFiles} disabled={items.length >= MAX_FILES} />

            <p className="mt-3 text-[11.5px] leading-5 text-ink-subtle">
              이 단계에서는 파일만 업로드합니다. Grok은 실행되지 않으며, AI 분석 시작 버튼을
              누른 이후에만 문서 요약과 외부 검증을 수행합니다.
            </p>

            {(lastError || uploadError) && (
              <p className="mt-3 flex items-center gap-2 rounded-lg bg-danger-soft px-3 py-2.5 text-[12.5px] font-semibold text-danger">
                <AlertCircle className="size-4 shrink-0" />
                {lastError || uploadError}
              </p>
            )}
          </Card>

          <Card className="p-5">
            <div className="flex items-center justify-between gap-3">
              <p className="flex items-center gap-1.5 text-[13px] font-bold text-ink">
                <FilePlus2 className="size-4 text-ink-muted" />
                문서 직접 작성
              </p>
              <button
                type="button"
                aria-expanded={isDirectWriteOpen}
                aria-controls="direct-write-content"
                aria-label={isDirectWriteOpen ? '문서 직접 작성 접기' : '문서 직접 작성 펼치기'}
                onClick={() => setIsDirectWriteOpen((open) => !open)}
                className="rounded-lg p-1.5 text-ink-subtle transition-colors hover:bg-line-soft hover:text-ink focus-visible:ring-2 focus-visible:ring-primary/30 focus-visible:outline-none"
              >
                <ChevronDown
                  className={`size-4 transition-transform duration-200 ${isDirectWriteOpen ? 'rotate-180' : ''}`}
                />
              </button>
            </div>

            <div id="direct-write-content" hidden={!isDirectWriteOpen}>
              <p className="mt-1 text-[12px] text-ink-muted">
                파일 대신 제목과 내용을 바로 입력해 업로드된 문서에 추가할 수 있어요.
              </p>

              <div className="mt-4 space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="md-title">제목</Label>
                <Input
                  id="md-title"
                  value={mdTitle}
                  onChange={(event) => setMdTitle(event.target.value)}
                  placeholder="문서 제목을 입력하세요"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="md-content">내용</Label>
                <NotionTextEditor
                  id="md-content"
                  value={mdContent}
                  onChange={setMdContent}
                  placeholder="# 로 제목, - 또는 * 로 목록, 1. 로 번호 목록을 만들 수 있어요"
                  rows={7}
                />
              </div>
              <Button
                variant="primary"
                className="w-full sm:w-auto"
                disabled={!mdTitle.trim() || items.length >= MAX_FILES}
                onClick={submitMarkdown}
              >
                <FilePlus2 />
                제출
              </Button>
              </div>
            </div>
          </Card>

          <SectionCard
            title={`업로드된 문서 (${items.length}/${MAX_FILES})`}
            description={
              items.length > 0
                ? `총 ${formatBytes(totals.bytes)} · 완료 ${totals.done}개`
                : undefined
            }
            action={
              items.length > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={deleteAll}
                  className="-mt-1 -mr-2 text-ink-muted hover:text-danger"
                >
                  <Trash2 />
                  전체 삭제
                </Button>
              )
            }
          >
            {items.length > 0 ? (
              <UploadList
                items={items}
                onRemove={(id) => void deleteItem(id)}
                onRetryExtraction={(revisionId) => retryExtraction.mutate(revisionId)}
                onReupload={reuploadItem}
                onPreview={previewItem}
              />
            ) : (
              <EmptyState
                icon={FileUp}
                title="업로드된 문서가 없어요"
                description="위 영역에 파일을 끌어다 놓거나 파일 선택 버튼을 눌러 업로드하세요."
                className="border-0 bg-transparent py-10"
              />
            )}
          </SectionCard>
        </div>

        {/* 우측 사이드 레일 */}
        <div className="space-y-5">
          <SectionCard title="지원 형식">
            <ul className="space-y-4">
              {[
                { ext: 'PDF', note: '텍스트 레이어가 있는 문서' },
                { ext: 'DOCX', note: 'Microsoft Word 문서' },
                { ext: 'HWP', note: '한글 문서 (hwp, hwpx)' },
                { ext: 'TXT', note: '일반 텍스트' },
                { ext: 'PPTX', note: '슬라이드 본문 및 노트' },
                { ext: 'XLSX', note: '표 데이터 및 시트' },
                { ext: 'PNG', note: '스캔·사진 이미지 (OCR)' },
                { ext: 'JPEG', note: '스캔·사진 이미지 (OCR)' },
              ].map((format) => (
                <li key={format.ext} className="flex items-center gap-3">
                  <span className="w-12 shrink-0 rounded-md bg-line-soft py-1 text-center text-[11px] font-extrabold text-ink-muted">
                    {format.ext}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[12.5px] text-ink-muted">
                    {format.note}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-4 border-t border-line-soft pt-3 text-[11.5px] leading-4 text-ink-subtle">
              파일당 최대 50MB, 프로젝트당 최대 {MAX_FILES}개까지 업로드할 수 있습니다.
            </p>
          </SectionCard>

          <Card className="overflow-hidden border-primary-100">
            <div className="brand-gradient h-1 w-full" />
            <div className="p-5">
              <p className="flex items-center gap-1.5 text-[13px] font-bold text-ink">
                <Sparkles className="size-4 text-ink-muted" />
                다음 단계
              </p>
              <p className="mt-2 text-[12.5px] leading-5 text-ink-muted">
                {mode === 'augment'
                  ? '기존 자료에 방금 더한 자료를 합쳐 AI가 처음부터 다시 분석해 드려요.'
                  : '문서가 2개 이상 모이면 AI가 공통 내용과 차이점을 분석해 하나의 통합 문서를 만들어드려요.'}
              </p>
              <Button
                variant="gradient"
                className="mt-4 w-full"
                disabled={!canAnalyze}
                onClick={() => void analyze()}
              >
                {mode === 'augment' ? '증강 분석 시작' : 'AI 분석 시작'}
                <ArrowRight />
              </Button>
              {!canAnalyze && (
                <p className="mt-2 text-center text-[11.5px] text-ink-subtle">
                  {isUploading
                    ? '업로드가 끝나면 시작할 수 있어요.'
                    : isProcessing
                      ? '문서를 처리하는 중이에요. 잠시만 기다려주세요.'
                      : '문서가 2개 이상 필요해요.'}
                </p>
              )}
              {analyzeError && (
                <p className="mt-2 flex items-center gap-1.5 text-[11.5px] font-semibold text-danger">
                  <AlertCircle className="size-3.5 shrink-0" />
                  {analyzeError}
                </p>
              )}
              <Button asChild variant="ghost" size="sm" className="mt-1 w-full">
                <Link to={`/projects/${project.id}`}>프로젝트로 이동</Link>
              </Button>
            </div>
          </Card>
        </div>
      </div>

      <DocumentPreviewDialog
        target={previewTarget}
        onOpenChange={(open) => {
          if (!open) setPreviewTarget(null)
        }}
      />
    </PageTransition>
  )
}
