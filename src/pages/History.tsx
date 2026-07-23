import { motion } from 'framer-motion'
import { HistoryIcon, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { useHistory } from '@/api/queries'
import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { UserAvatar } from '@/components/common/UserAvatar'
import { PageTransition, staggerContainer, staggerItem } from '@/components/layout/PageTransition'
import { activityKindMeta } from '@/components/project/ActivityFeed'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { userByName } from '@/data/members'
import { formatDate, formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ActivityKind, HistoryEntry } from '@/types'

const kindLabel: Record<ActivityKind, string> = {
  upload: '업로드',
  analysis: 'AI 분석',
  create: '생성',
  comment: '댓글',
  edit: '편집',
  invite: '초대',
  export: '내보내기',
}

export default function History() {
  const { data, isLoading } = useHistory()
  const [search, setSearch] = useState('')
  const [kind, setKind] = useState<ActivityKind | 'all'>('all')

  const grouped = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    const filtered = (data ?? []).filter((entry) => {
      const matchesKeyword =
        !keyword ||
        entry.projectName.toLowerCase().includes(keyword) ||
        entry.detail.toLowerCase().includes(keyword) ||
        entry.action.toLowerCase().includes(keyword)
      return matchesKeyword && (kind === 'all' || entry.kind === kind)
    })

    const sorted = [...filtered].sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
    )

    // 캘린더 날짜별로 묶어 타임라인이 시간순으로 읽히게 합니다.
    const map = new Map<string, HistoryEntry[]>()
    for (const entry of sorted) {
      const day = formatDate(entry.createdAt)
      map.set(day, [...(map.get(day) ?? []), entry])
    }
    return [...map.entries()]
  }, [data, kind, search])

  return (
    <PageTransition className="space-y-6">
      <PageHeader title="히스토리" description="프로젝트에서 일어난 모든 변경 기록입니다." />

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
            {Object.entries(kindLabel).map(([value, label]) => (
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
      ) : grouped.length === 0 ? (
        <EmptyState
          icon={HistoryIcon}
          title="기록이 없어요"
          description="검색어나 필터를 바꿔서 다시 찾아보세요."
        />
      ) : (
        <motion.div variants={staggerContainer} initial="hidden" animate="show" className="space-y-6">
          {grouped.map(([day, entries]) => (
            <section key={day} className="space-y-2.5">
              <h2 className="sticky top-16 z-10 -mx-1 w-fit rounded-md bg-canvas/90 px-2 py-1 text-[12px] font-bold text-ink-muted backdrop-blur">
                {day}
              </h2>
              {entries.map((entry) => (
                <HistoryRow key={entry.id} entry={entry} />
              ))}
            </section>
          ))}
        </motion.div>
      )}
    </PageTransition>
  )
}

function HistoryRow({ entry }: { entry: HistoryEntry }) {
  const meta = activityKindMeta[entry.kind]

  return (
    <motion.div variants={staggerItem}>
      <Card className="flex items-start gap-3.5 p-4 transition-all duration-200 hover:border-primary-200 hover:shadow-lift">
        <span
          className={cn('flex size-9 shrink-0 items-center justify-center rounded-xl', meta.className)}
        >
          <meta.icon className="size-4" />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[13.5px] font-bold text-ink">{entry.action}</span>
            <Link
              to={`/projects/${entry.projectId}`}
              className="truncate rounded bg-line-soft px-1.5 py-0.5 text-[11.5px] font-semibold text-ink-muted transition-colors hover:bg-primary-50 hover:text-primary"
            >
              {entry.projectName}
            </Link>
          </div>
          <p className="mt-1 text-[12.5px] leading-5 text-ink-muted">{entry.detail}</p>
          <div className="mt-2 flex items-center gap-1.5">
            <UserAvatar user={userByName(entry.actor)} size="xs" ring={false} />
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
