import { AlertCircle, ArrowRight, FileUp, Sparkles, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { PageTransition } from '@/components/layout/PageTransition'
import { Dropzone } from '@/components/upload/Dropzone'
import { UploadList } from '@/components/upload/UploadList'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useUploadQueue, type UploadItem } from '@/hooks/useUploadQueue'
import { formatBytes } from '@/lib/format'
import { projects } from '@/data/projects'

const MAX_FILES = 10

/** 프로젝트가 이미 진행 중인 것처럼 보이도록 미리 채워 둔 파일. */
const seeded: UploadItem[] = [
  {
    id: 'seed-1',
    name: '캠페인 개요.docx',
    kind: 'docx',
    size: 1.2 * 1024 * 1024,
    progress: 100,
    status: 'uploaded',
    addedAt: '2024-05-15T14:20:00',
  },
  {
    id: 'seed-2',
    name: '채널별 홍보 전략.pdf',
    kind: 'pdf',
    size: 2.3 * 1024 * 1024,
    progress: 100,
    status: 'uploaded',
    addedAt: '2024-05-15T14:18:00',
  },
  {
    id: 'seed-3',
    name: '예산 계획.xlsx',
    kind: 'xlsx',
    size: 0.8 * 1024 * 1024,
    progress: 100,
    status: 'uploaded',
    addedAt: '2024-05-15T14:15:00',
  },
  {
    id: 'seed-4',
    name: '기대 효과 및 KPI.hwp',
    kind: 'hwp',
    size: 1.5 * 1024 * 1024,
    progress: 100,
    status: 'uploaded',
    addedAt: '2024-05-15T14:12:00',
  },
  {
    id: 'seed-5',
    name: '참고 자료.txt',
    kind: 'txt',
    size: 0.1 * 1024 * 1024,
    progress: 100,
    status: 'uploaded',
    addedAt: '2024-05-15T14:10:00',
  },
]

export default function Upload() {
  const navigate = useNavigate()
  const [projectId, setProjectId] = useState('p-1')
  const { items, add, remove, clear, retry, isUploading, lastError } = useUploadQueue({
    initial: seeded,
    maxFiles: MAX_FILES,
  })

  const totals = useMemo(() => {
    const bytes = items.reduce((sum, item) => sum + item.size, 0)
    const done = items.filter((item) => item.progress >= 100).length
    const overall = items.length
      ? Math.round(items.reduce((sum, item) => sum + item.progress, 0) / items.length)
      : 0
    return { bytes, done, overall }
  }, [items])

  const canAnalyze = items.length >= 2 && !isUploading

  return (
    <PageTransition className="space-y-6">
      <PageHeader
        title="문서 업로드"
        description="프로젝트에 통합할 문서를 업로드하세요."
        actions={
          <Button
            variant="gradient"
            disabled={!canAnalyze}
            onClick={() => navigate(`/projects/${projectId}/analysis`)}
          >
            <Sparkles />
            AI 분석 시작
          </Button>
        }
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-5">
          <Card className="p-5">
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <span className="text-[13px] font-bold text-ink">업로드할 프로젝트</span>
              <Select value={projectId} onValueChange={setProjectId}>
                <SelectTrigger className="min-w-[220px]" aria-label="프로젝트 선택">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {projects.map((project) => (
                    <SelectItem key={project.id} value={project.id}>
                      {project.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <Dropzone onFiles={add} disabled={items.length >= MAX_FILES} />

            {lastError && (
              <p className="mt-3 flex items-center gap-2 rounded-lg bg-danger-soft px-3 py-2.5 text-[12.5px] font-semibold text-danger">
                <AlertCircle className="size-4 shrink-0" />
                {lastError}
              </p>
            )}
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
                  onClick={clear}
                  className="-mt-1 -mr-2 text-ink-muted hover:text-danger"
                >
                  <Trash2 />
                  전체 삭제
                </Button>
              )
            }
          >
            {items.length > 0 ? (
              <>
                <UploadList items={items} onRemove={remove} onRetry={retry} />
                <div className="mt-4 flex items-center gap-3 rounded-lg bg-line-soft/70 px-3.5 py-3">
                  <span className="text-[12px] font-bold text-ink">전체 진행률</span>
                  <Progress
                    value={totals.overall}
                    tone={totals.overall >= 100 ? 'success' : 'gradient'}
                    className="flex-1"
                  />
                  <span className="text-[12.5px] font-extrabold text-ink tabular-nums">
                    {totals.overall}%
                  </span>
                </div>
              </>
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
                <Sparkles className="size-4 text-secondary-500" />
                다음 단계
              </p>
              <p className="mt-2 text-[12.5px] leading-5 text-ink-muted">
                문서가 2개 이상 모이면 AI가 공통 내용과 차이점을 분석해 하나의 통합 문서를
                만들어드려요.
              </p>
              <Button
                variant="gradient"
                className="mt-4 w-full"
                disabled={!canAnalyze}
                onClick={() => navigate(`/projects/${projectId}/analysis`)}
              >
                AI 분석 시작
                <ArrowRight />
              </Button>
              {!canAnalyze && (
                <p className="mt-2 text-center text-[11.5px] text-ink-subtle">
                  {isUploading ? '업로드가 끝나면 시작할 수 있어요.' : '문서가 2개 이상 필요해요.'}
                </p>
              )}
              <Button asChild variant="ghost" size="sm" className="mt-1 w-full">
                <Link to={`/projects/${projectId}`}>프로젝트로 이동</Link>
              </Button>
            </div>
          </Card>
        </div>
      </div>
    </PageTransition>
  )
}
