import { FileStack, Search } from 'lucide-react'
import { useMemo, useState } from 'react'

import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { MergedDocumentList } from '@/components/dashboard/MergedDocumentList'
import { PageTransition } from '@/components/layout/PageTransition'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { mergedDocuments } from '@/data/documents'

const DEMO_NOW = new Date('2024-05-16T15:00:00')

export default function Documents() {
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<'recent' | 'name' | 'sources'>('recent')

  const filtered = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    const matched = mergedDocuments.filter(
      (doc) =>
        !keyword ||
        doc.title.toLowerCase().includes(keyword) ||
        doc.projectName.toLowerCase().includes(keyword),
    )

    return [...matched].sort((a, b) => {
      if (sort === 'name') return a.title.localeCompare(b.title, 'ko')
      if (sort === 'sources') return b.sourceCount - a.sourceCount
      return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
    })
  }, [search, sort])

  return (
    <PageTransition className="space-y-6">
      <PageHeader
        title="통합 문서"
        description="AI가 생성한 통합 문서를 한곳에서 확인하고 이어서 편집하세요."
      />

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1 sm:max-w-[300px]">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-subtle" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="통합 문서 검색"
            className="pl-9"
            aria-label="통합 문서 검색"
          />
        </div>
        <Select value={sort} onValueChange={(value) => setSort(value as typeof sort)}>
          <SelectTrigger aria-label="정렬 기준">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="recent">최근 수정 순</SelectItem>
            <SelectItem value="name">이름 순</SelectItem>
            <SelectItem value="sources">원본 문서 많은 순</SelectItem>
          </SelectContent>
        </Select>
        <span className="ml-auto text-[12px] font-semibold text-ink-subtle">
          총 {filtered.length}개
        </span>
      </div>

      {filtered.length > 0 ? (
        <MergedDocumentList documents={filtered} now={DEMO_NOW} />
      ) : (
        <EmptyState
          icon={FileStack}
          title="통합 문서를 찾을 수 없어요"
          description="검색어를 바꾸거나 프로젝트에서 AI 분석을 먼저 실행해보세요."
        />
      )}
    </PageTransition>
  )
}
