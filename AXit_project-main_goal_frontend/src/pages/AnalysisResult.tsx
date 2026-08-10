import { AlertCircle, AlertTriangle, Download, FileEdit, FilePlus2, Loader2, RotateCcw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api, ApiError } from '@/api/client'
import { useAnalysis, useMergedDocument, useProject, useReopenSession, useRetryAnalysis } from '@/api/queries'
import { DifferenceTab } from '@/components/analysis/DifferenceTab'
import { InsightTab } from '@/components/analysis/InsightTab'
import { KeywordTab } from '@/components/analysis/KeywordTab'
import { PerDocumentTab } from '@/components/analysis/PerDocumentTab'
import { SummaryTab } from '@/components/analysis/SummaryTab'
import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { DocumentCanvas } from '@/components/editor/DocumentCanvas'
import { RagEvidenceDialog } from '@/components/editor/RagEvidenceDialog'
import { PageTransition } from '@/components/layout/PageTransition'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { downloadMergedDocument } from '@/lib/markdown'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  DocumentPreviewDialog,
  type PreviewTarget,
} from '@/components/upload/DocumentPreviewDialog'
import type { DocBlock } from '@/types'

const tabs = [
  { value: 'summary', label: '요약' },
  { value: 'merged-document', label: '통합 문서' },
  { value: 'difference', label: '외부검증' },
  { value: 'per-document', label: '문서별 분석' },
  { value: 'keyword', label: '키워드' },
  { value: 'insight', label: 'AI 인사이트' },
] as const

export default function AnalysisResult() {
  const { projectId = 'p-1' } = useParams<{ projectId: string }>()
  const { data: result, isLoading, isError } = useAnalysis(projectId)
  const { data: projectData } = useProject(projectId)
  const {
    data: mergedDocumentData,
    isLoading: isMergedDocumentLoading,
    isError: isMergedDocumentError,
  } = useMergedDocument(projectId)
  const [tab, setTab] = useState<string>('summary')
  const project = projectData?.project
  const projectDocuments = useMemo(() => projectData?.documents ?? [], [projectData?.documents])
  const navigate = useNavigate()
  const reopenSession = useReopenSession(projectId)
  const retryAnalysis = useRetryAnalysis(projectId)
  const [reopenError, setReopenError] = useState<string | null>(null)
  const [selectedRagAnchorId, setSelectedRagAnchorId] = useState<string | null>(null)
  const [originalPreview, setOriginalPreview] = useState<PreviewTarget | null>(null)
  const [ragAnchorLabels, setRagAnchorLabels] = useState<Record<string, string>>({})
  const isFailed = project?.status === 'review'

  useEffect(() => {
    if (!mergedDocumentData) {
      setRagAnchorLabels({})
      return
    }

    const fallbackLabels = buildRagAnchorLabels(mergedDocumentData.document.blocks)
    const anchorIds = Object.keys(fallbackLabels)
    setRagAnchorLabels(fallbackLabels)
    let cancelled = false

    // 편집창과 동일하게 anchor의 source_revision_id를 실제 프로젝트 문서 제목으로
    // 바꿉니다. 단, 한꺼번에 요청해 클릭 요청을 막지 않도록 순차 처리합니다.
    void (async () => {
      for (const anchorId of anchorIds) {
        if (cancelled) return
        try {
          const { data: target } = await api.get<{ source_revision_id: string }>(
            `/source-anchors/${anchorId}/resolve`,
          )
          if (cancelled) return
          const source = projectDocuments.find(
            (document) => document.revisionId === target.source_revision_id,
          )
          if (source) {
            setRagAnchorLabels((labels) => ({ ...labels, [anchorId]: source.name }))
          }
        } catch {
          // 블록 tag 기반 제목을 유지하면 네트워크 오류가 있어도 출처 표시가 사라지지 않습니다.
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [mergedDocumentData, projectDocuments])

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

  return (
    <PageTransition className="space-y-6">
      <PageHeader
        breadcrumbs={[
          { label: '프로젝트', to: '/projects' },
          { label: project?.name ?? '프로젝트', to: `/projects/${projectId}` },
          { label: '분석 결과' },
        ]}
        title={`${project?.name ?? '프로젝트'} 분석 결과`}
        description="AI가 요약하고 외부 자료로 검증한 결과를 확인하고 통합 문서로 이어가세요."
        actions={
          <>
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
            <Button asChild variant="primary">
              <Link to={`/projects/${projectId}/editor`}>
                <FileEdit />
                통합 문서 편집
              </Link>
            </Button>
            <Button
              variant="ghost"
              disabled={!mergedDocumentData}
              onClick={() => mergedDocumentData && downloadMergedDocument(mergedDocumentData.document)}
            >
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

      {isFailed ? (
        <EmptyState
          icon={AlertTriangle}
          title="분석 중 오류가 발생했어요"
          description="일부 문서 분석이 반복적으로 실패했습니다. 다시 시도하거나, 문제가 되는 문서를 제외하고 진행해 주세요."
          action={
            <Button
              variant="gradient"
              disabled={retryAnalysis.isPending}
              onClick={() => void retryAnalysis.mutateAsync()}
            >
              다시 시도
            </Button>
          }
        />
      ) : isError ? (
        <EmptyState
          icon={Loader2}
          title="아직 분석 결과가 준비되지 않았어요"
          description="AI가 문서를 분석하는 중일 수 있어요. 잠시 후 자동으로 다시 확인합니다."
        />
      ) : isLoading || !result ? (
        <div className="space-y-5">
          <Skeleton className="h-10 w-full max-w-lg" />
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
            <Skeleton className="h-[420px] rounded-xl" />
            <Skeleton className="h-[420px] rounded-xl" />
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            {tabs.map((item) => (
              <TabsTrigger key={item.value} value={item.value}>
                {item.label}
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="summary">
            <SummaryTab result={result} onOpenDifferences={() => setTab('difference')} />
          </TabsContent>
          <TabsContent value="merged-document">
            {mergedDocumentData ? (
              <Card className="overflow-hidden p-0">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
                  <div>
                    <h2 className="text-base font-bold text-ink">{mergedDocumentData.document.title}</h2>
                    <p className="mt-0.5 text-xs text-ink-muted">
                      원본 문서를 바탕으로 생성된 통합 문서입니다.
                    </p>
                  </div>
                  <Button asChild variant="outline" size="sm">
                    <Link to={`/projects/${projectId}/editor`}>
                      <FileEdit />
                      편집하기
                    </Link>
                  </Button>
                </div>
                <div className="max-h-[680px] overflow-y-auto bg-canvas/40">
                  <DocumentCanvas
                    blocks={mergedDocumentData.document.blocks}
                    onSelectRagAnchor={setSelectedRagAnchorId}
                    ragAnchorLabels={ragAnchorLabels}
                    ragTitleOrder={projectDocuments.map((document) => document.name)}
                    editable={false}
                  />
                </div>
              </Card>
            ) : isMergedDocumentLoading ? (
              <Skeleton className="h-[520px] rounded-xl" />
            ) : (
              <EmptyState
                icon={isMergedDocumentError ? AlertTriangle : Loader2}
                title="통합 문서가 아직 준비되지 않았어요"
                description="통합 문서 생성이 완료되면 이곳에서 바로 확인할 수 있습니다."
              />
            )}
          </TabsContent>
          <TabsContent value="difference">
            <DifferenceTab result={result} />
          </TabsContent>
          <TabsContent value="per-document">
            <PerDocumentTab result={result} />
          </TabsContent>
          <TabsContent value="keyword">
            <KeywordTab result={result} />
          </TabsContent>
          <TabsContent value="insight">
            <InsightTab result={result} />
          </TabsContent>
          </Tabs>
        </div>
      )}

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

function buildRagAnchorLabels(blocks: DocBlock[]) {
  const labels: Record<string, string> = {}
  for (const block of blocks) {
    const label = block.tag?.trim() || '근거 문서'
    for (const anchorId of extractDocumentRagAnchorIds([block])) labels[anchorId] = label
  }
  return labels
}
