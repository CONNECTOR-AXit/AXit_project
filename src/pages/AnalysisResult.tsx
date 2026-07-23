import { Download, FileEdit, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { useAnalysis } from '@/api/queries'
import { CommonTab } from '@/components/analysis/CommonTab'
import { DifferenceTab } from '@/components/analysis/DifferenceTab'
import { InsightTab } from '@/components/analysis/InsightTab'
import { KeywordTab } from '@/components/analysis/KeywordTab'
import { PerDocumentTab } from '@/components/analysis/PerDocumentTab'
import { SummaryTab } from '@/components/analysis/SummaryTab'
import { PageHeader } from '@/components/common/PageHeader'
import { PageTransition } from '@/components/layout/PageTransition'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { projectById } from '@/data/projects'

const tabs = [
  { value: 'summary', label: '요약' },
  { value: 'common', label: '공통 내용' },
  { value: 'difference', label: '차이점' },
  { value: 'per-document', label: '문서별 분석' },
  { value: 'keyword', label: '키워드' },
  { value: 'insight', label: 'AI 인사이트' },
] as const

export default function AnalysisResult() {
  const { projectId = 'p-1' } = useParams<{ projectId: string }>()
  const { data: result, isLoading } = useAnalysis(projectId)
  const [tab, setTab] = useState<string>('summary')
  const project = projectById(projectId)

  return (
    <PageTransition className="space-y-6">
      <PageHeader
        breadcrumbs={[
          { label: '프로젝트', to: '/projects' },
          { label: project?.name ?? '프로젝트', to: `/projects/${projectId}` },
          { label: '분석 결과' },
        ]}
        title={`${project?.name ?? '프로젝트'} 분석 결과`}
        description="AI가 찾아낸 공통 내용과 차이점을 확인하고 통합 문서로 이어가세요."
        actions={
          <>
            <Button asChild variant="outline">
              <Link to={`/projects/${projectId}/analysis`}>
                <RotateCcw />
                다시 분석하기
              </Link>
            </Button>
            <Button asChild variant="primary">
              <Link to={`/projects/${projectId}/editor`}>
                <FileEdit />
                통합 문서 편집
              </Link>
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost">
                  <Download />
                  다운로드
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem>PDF로 저장</DropdownMenuItem>
                <DropdownMenuItem>DOCX로 저장</DropdownMenuItem>
                <DropdownMenuItem>분석 데이터 (CSV)</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        }
      />

      {isLoading || !result ? (
        <div className="space-y-5">
          <Skeleton className="h-10 w-full max-w-lg" />
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
            <Skeleton className="h-[420px] rounded-xl" />
            <Skeleton className="h-[420px] rounded-xl" />
          </div>
        </div>
      ) : (
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
          <TabsContent value="common">
            <CommonTab result={result} />
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
      )}
    </PageTransition>
  )
}
