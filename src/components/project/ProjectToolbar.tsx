import { LayoutGrid, List, Search } from 'lucide-react'

import { projectStatusMap } from '@/components/common/StatusBadge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { ProjectSortKey, ProjectStatusFilter, ProjectViewMode } from '@/types'

const sortLabel: Record<ProjectSortKey, string> = {
  recent: '최신 순',
  name: '이름 순',
  progress: '진행률 순',
}

export interface ProjectToolbarProps {
  search: string
  onSearchChange: (value: string) => void
  sort: ProjectSortKey
  onSortChange: (value: ProjectSortKey) => void
  status: ProjectStatusFilter
  onStatusChange: (value: ProjectStatusFilter) => void
  view: ProjectViewMode
  onViewChange: (value: ProjectViewMode) => void
  className?: string
}

/** 프로젝트 목록 상단 툴바 — 검색 · 정렬 · 상태 필터 · 보기 전환. */
export function ProjectToolbar({
  search,
  onSearchChange,
  sort,
  onSortChange,
  status,
  onStatusChange,
  view,
  onViewChange,
  className,
}: ProjectToolbarProps) {
  return (
    <div className={cn('flex flex-wrap items-center gap-2', className)}>
      <div className="relative min-w-[200px] flex-1 sm:max-w-[280px]">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-subtle" />
        <Input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="프로젝트 검색"
          className="pl-9"
          aria-label="프로젝트 검색"
        />
      </div>

      <Select value={sort} onValueChange={(value) => onSortChange(value as ProjectSortKey)}>
        <SelectTrigger aria-label="정렬 기준">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(Object.keys(sortLabel) as ProjectSortKey[]).map((key) => (
            <SelectItem key={key} value={key}>
              {sortLabel[key]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/*
        상태 라벨은 StatusBadge 의 projectStatusMap 을 그대로 씁니다.
        필터와 배지에 표시되는 문구가 어긋나지 않습니다.
      */}
      <Select value={status} onValueChange={(value) => onStatusChange(value as ProjectStatusFilter)}>
        <SelectTrigger aria-label="상태 필터">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">전체 상태</SelectItem>
          {Object.entries(projectStatusMap).map(([value, meta]) => (
            <SelectItem key={value} value={value}>
              {meta.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <div className="ml-auto hidden items-center gap-0.5 rounded-lg bg-line-soft p-0.5 sm:flex">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="그리드 보기"
          aria-pressed={view === 'grid'}
          onClick={() => onViewChange('grid')}
          className={cn(view === 'grid' && 'bg-white text-ink shadow-soft hover:bg-white')}
        >
          <LayoutGrid />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="목록 보기"
          aria-pressed={view === 'list'}
          onClick={() => onViewChange('list')}
          className={cn(view === 'list' && 'bg-white text-ink shadow-soft hover:bg-white')}
        >
          <List />
        </Button>
      </div>
    </div>
  )
}
