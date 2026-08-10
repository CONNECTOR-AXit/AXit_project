import { motion } from 'framer-motion'
import { CircleAlert, HistoryIcon, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { useHistory } from '@/api/queries'
import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { PageTransition, staggerContainer, staggerItem } from '@/components/layout/PageTransition'
import { activityKindMeta } from '@/components/project/ActivityFeed'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate, formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ActivityKind, HistoryEntry } from '@/types'

const availableKinds: Array<{ value: ActivityKind; label: string }> = [
  { value: 'upload', label: '업로드' },
  { value: 'analysis', label: 'AI 분석' },
  { value: 'create', label: '생성' },
]

export default function History() {
  const { data, isLoading, isError, refetch } = useHistory()
  const [search, setSearch] = useState('')
  const [kind, setKind] = useState<ActivityKind | 'all'>('all')

  const entries = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    const filtered = (data?.items ?? []).filter((entry) => {
      const matchesKeyword =
        !keyword ||
        entry.projectName.toLowerCase().includes(keyword) ||
        entry.detail.toLowerCase().includes(keyword) ||
        entry.action.toLowerCase().includes(keyword)
      return matchesKeyword && (kind === 'all' || entry.kind === kind)
    })

    return [...filtered].sort((a, b) => b.ledgerSequence - a.ledgerSequence)
  }, [data?.items, kind, search])

  return (
    <PageTransition className="space-y-6">
      <PageHeader title="히스토리" description="프로젝트 생성, 자료 제출, AI 분석 상태를 시간순으로 확인합니다." />

      {data?.coverageStartedAt && (
        <p className="rounded-lg border border-line bg-white px-3 py-2 text-[12px] text-ink-muted">
          감사 원장은 {formatDateTime(data.coverageStartedAt)}부터 기록됩니다. 그 이전 활동은 이 목록이 완전하지 않을 수 있습니다.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1 sm:max-w-[300px]">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-subtle" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="기록 검색"
            className="pl-9"
            aria-label="히스토리 검색"
          />
        </div>
        <Select value={kind} onValueChange={(value) => setKind(value as typeof kind)}>
          <SelectTrigger aria-label="활동 유형 필터">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">전체 활동</SelectItem>
            {availableKinds.map(({ value, label }) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-20 rounded-xl" />
          ))}
        </div>
      ) : isError ? (
        <EmptyState
          icon={CircleAlert}
          title="히스토리를 불러오지 못했어요"
          description="네트워크 연결 또는 로그인 상태를 확인한 뒤 다시 시도해 주세요."
          action={<Button onClick={() => void refetch()}>다시 시도</Button>}
        />
      ) : entries.length === 0 ? (
        <EmptyState
          icon={HistoryIcon}
          title="기록이 없어요"
          description={
            data?.items.length
              ? '검색어나 필터를 바꿔서 다시 찾아보세요.'
              : '프로젝트를 만들거나 자료를 제출하면 여기에 활동이 표시됩니다.'
          }
        />
      ) : (
        <motion.div variants={staggerContainer} initial="hidden" animate="show" className="space-y-6">
          {entries.map((entry, index) => {
            const day = formatDate(entry.createdAt)
            const previousDay = index > 0 ? formatDate(entries[index - 1]!.createdAt) : undefined
            return (
              <div key={entry.id} className="space-y-2.5">
                {day !== previousDay && (
                  <h2 className="sticky top-16 z-10 -mx-1 w-fit rounded-md bg-canvas/90 px-2 py-1 text-[12px] font-bold text-ink-muted backdrop-blur">{day}</h2>
                )}
                <HistoryRow entry={entry} />
              </div>
            )
          })}
        </motion.div>
      )}
    </PageTransition>
  )
}

function HistoryRow({ entry }: { entry: HistoryEntry }) {
  const meta = activityKindMeta[entry.kind]

  return (
    <motion.div variants={staggerItem}>
      <Card className="flex items-start gap-3.5 p-4 transition-all duration-200 hover:shadow-lift">
        <span
          className={cn('flex size-9 shrink-0 items-center justify-center rounded-xl', meta.className)}
        >
          <meta.icon className="size-4" />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[13.5px] font-bold text-ink">{entry.action}</span>
            {entry.href ? (
              <Link to={entry.href} className="truncate rounded bg-line-soft px-1.5 py-0.5 text-[11.5px] font-semibold text-ink-muted transition-colors hover:bg-primary-50 hover:text-primary">
                {entry.projectName}
              </Link>
            ) : (
              <span className="truncate rounded bg-line-soft px-1.5 py-0.5 text-[11.5px] font-semibold text-ink-muted">{entry.projectName}</span>
            )}
          </div>
          <p className="mt-1 text-[12.5px] leading-5 text-ink-muted">{entry.detail}</p>
          <div className="mt-2 flex items-center gap-1.5">
            <span className="text-[11.5px] font-medium text-ink-subtle">{entry.actor}</span>
          </div>
        </div>

        <time className="shrink-0 text-[11.5px] text-ink-subtle tabular-nums">
          {formatDateTime(entry.createdAt).slice(-5)}
        </time>
      </Card>
    </motion.div>
  )
}
