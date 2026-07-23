import { motion } from 'framer-motion'
import {
  BellOff,
  CheckCheck,
  Info,
  MessageSquare,
  Sparkles,
  UserPlus,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useNotifications } from '@/api/queries'
import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { PageTransition, staggerContainer, staggerItem } from '@/components/layout/PageTransition'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { NotificationItem, NotificationKind } from '@/types'

const DEMO_NOW = new Date('2024-05-16T15:00:00')

const kindMeta: Record<NotificationKind, { icon: LucideIcon; className: string; label: string }> = {
  analysis: { icon: Sparkles, className: 'bg-secondary-50 text-secondary-600', label: 'AI 분석' },
  mention: { icon: MessageSquare, className: 'bg-primary-50 text-primary', label: '멘션' },
  invite: { icon: UserPlus, className: 'bg-success-soft text-success', label: '초대' },
  comment: { icon: MessageSquare, className: 'bg-warning-soft text-warning', label: '댓글' },
  system: { icon: Info, className: 'bg-line-soft text-ink-muted', label: '시스템' },
}

export default function Notifications() {
  const { data, isLoading } = useNotifications()
  const [readIds, setReadIds] = useState<string[]>([])

  const items = (data ?? []).map((item) => ({
    ...item,
    read: item.read || readIds.includes(item.id),
  }))
  const unread = items.filter((item) => !item.read)

  const markAllRead = () => setReadIds(items.map((item) => item.id))

  return (
    <PageTransition className="space-y-6">
      <PageHeader
        title="알림"
        description="프로젝트 활동과 AI 분석 결과를 확인하세요."
        actions={
          <Button variant="outline" onClick={markAllRead} disabled={unread.length === 0}>
            <CheckCheck />
            모두 읽음 처리
          </Button>
        }
      />

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-[86px] rounded-xl" />
          ))}
        </div>
      ) : (
        <Tabs defaultValue="all">
          <TabsList>
            <TabsTrigger value="all">전체 ({items.length})</TabsTrigger>
            <TabsTrigger value="unread">읽지 않음 ({unread.length})</TabsTrigger>
          </TabsList>

          <TabsContent value="all">
            <NotificationGroup
              items={items}
              onRead={(id) => setReadIds((prev) => [...prev, id])}
              emptyTitle="알림이 없어요"
            />
          </TabsContent>
          <TabsContent value="unread">
            <NotificationGroup
              items={unread}
              onRead={(id) => setReadIds((prev) => [...prev, id])}
              emptyTitle="읽지 않은 알림이 없어요"
              emptyDescription="새로운 소식이 오면 여기에 표시됩니다."
            />
          </TabsContent>
        </Tabs>
      )}
    </PageTransition>
  )
}

function NotificationGroup({
  items,
  onRead,
  emptyTitle,
  emptyDescription = '새로운 알림이 도착하면 이곳에 표시됩니다.',
}: {
  items: NotificationItem[]
  onRead: (id: string) => void
  emptyTitle: string
  emptyDescription?: string
}) {
  if (items.length === 0) {
    return <EmptyState icon={BellOff} title={emptyTitle} description={emptyDescription} />
  }

  return (
    <motion.ul variants={staggerContainer} initial="hidden" animate="show" className="space-y-2.5">
      {items.map((item) => {
        const meta = kindMeta[item.kind]
        return (
          <motion.li key={item.id} variants={staggerItem}>
            <Card
              className={cn(
                'relative transition-all duration-200 hover:border-primary-200 hover:shadow-lift',
                !item.read && 'border-primary-100 bg-primary-50/25',
              )}
            >
              <Link
                to={item.href ?? '#'}
                onClick={() => onRead(item.id)}
                className="flex items-start gap-3.5 p-4 focus-visible:ring-[3px] focus-visible:ring-primary/25 focus-visible:outline-none"
              >
                <span
                  className={cn(
                    'flex size-9 shrink-0 items-center justify-center rounded-xl',
                    meta.className,
                  )}
                >
                  <meta.icon className="size-4" />
                </span>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13.5px] font-bold text-ink">{item.title}</span>
                    <span className="rounded bg-line-soft px-1.5 py-0.5 text-[11px] font-semibold text-ink-muted">
                      {meta.label}
                    </span>
                    {!item.read && <span className="size-2 rounded-full bg-primary" />}
                  </div>
                  <p className="mt-1 text-[12.5px] leading-5 text-ink-muted">{item.body}</p>
                </div>

                <time className="shrink-0 text-[11.5px] text-ink-subtle">
                  {formatRelative(item.createdAt, DEMO_NOW)}
                </time>
              </Link>
            </Card>
          </motion.li>
        )
      })}
    </motion.ul>
  )
}
