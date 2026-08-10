import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'
import {
  BellOff,
  CircleAlert,
  CheckCheck,
  Info,
  MessageSquare,
  Sparkles,
  UserPlus,
  Mail,
  type LucideIcon,
} from 'lucide-react'
import {
  useFriendRequestActions,
  useMyEmailOutbox,
  useNotificationReadActions,
  useNotifications,
} from '@/api/queries'
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

const kindMeta: Record<NotificationKind, { icon: LucideIcon; className: string; label: string }> = {
  analysis: { icon: Sparkles, className: 'bg-line-soft text-ink-muted', label: 'AI 분석' },
  mention: { icon: MessageSquare, className: 'bg-line-soft text-ink-muted', label: '멘션' },
  invite: { icon: UserPlus, className: 'bg-line-soft text-ink-muted', label: '초대' },
  comment: { icon: MessageSquare, className: 'bg-line-soft text-ink-muted', label: '댓글' },
  member: { icon: Info, className: 'bg-line-soft text-ink-muted', label: '멤버' },
}

export default function Notifications() {
  const { data, isLoading, isError, refetch } = useNotifications()
  const { markAllRead, markRead } = useNotificationReadActions()
  const outbox = useMyEmailOutbox()
  const friendRequestActions = useFriendRequestActions()
  const items = data?.items ?? []
  const unread = items.filter((item) => !item.read)

  return (
    <PageTransition className="space-y-6">
      <PageHeader
        title="알림"
        description="프로젝트 활동과 AI 분석 결과를 확인하세요."
        actions={
          <Button variant="outline" onClick={() => markAllRead.mutate()} disabled={data?.unreadCount === 0 || markAllRead.isPending}>
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
      ) : isError ? (
        <EmptyState
          icon={CircleAlert}
          title="알림을 불러오지 못했어요"
          description="네트워크 연결 또는 로그인 상태를 확인한 뒤 다시 시도해 주세요."
          action={<Button onClick={() => void refetch()}>다시 시도</Button>}
        />
      ) : (
        <Tabs defaultValue="all">
          <TabsList>
            <TabsTrigger value="all">전체 ({items.length})</TabsTrigger>
            <TabsTrigger value="unread">읽지 않음 ({data?.unreadCount ?? 0})</TabsTrigger>
            <TabsTrigger value="outbox">이메일 큐 ({outbox.data?.items.length ?? 0})</TabsTrigger>
          </TabsList>

          <TabsContent value="all">
            <NotificationGroup
              items={items}
              onRead={(id) => markRead.mutate(id)}
              onAccept={(id) => friendRequestActions.accept.mutate(id)}
              onReject={(id) => friendRequestActions.reject.mutate(id)}
              actionPending={friendRequestActions.accept.isPending || friendRequestActions.reject.isPending}
              emptyTitle="알림이 없어요"
            />
          </TabsContent>
          <TabsContent value="unread">
            <NotificationGroup
              items={unread}
              onRead={(id) => markRead.mutate(id)}
              onAccept={(id) => friendRequestActions.accept.mutate(id)}
              onReject={(id) => friendRequestActions.reject.mutate(id)}
              actionPending={friendRequestActions.accept.isPending || friendRequestActions.reject.isPending}
              emptyTitle="읽지 않은 알림이 없어요"
              emptyDescription="새로운 소식이 오면 여기에 표시됩니다."
            />
          </TabsContent>
          <TabsContent value="outbox">
            {outbox.isLoading ? (
              <Skeleton className="h-24 rounded-xl" />
            ) : outbox.isError ? (
              <EmptyState icon={CircleAlert} title="로컬 이메일 큐를 불러오지 못했어요" description="다시 시도해 주세요." action={<Button onClick={() => void outbox.refetch()}>다시 시도</Button>} />
            ) : outbox.data?.items.length ? (
              <ul className="space-y-2.5">
                {outbox.data.items.map((item) => (
                  <li key={item.id}>
                    <Card className="flex items-start gap-3 p-4">
                      <Mail className="mt-0.5 size-4 text-ink-subtle" />
                      <div>
                        <p className="text-[13px] font-bold text-ink">{item.template_key}</p>
                        <p className="mt-1 text-[12px] text-ink-muted"><strong>{item.status}</strong> · {item.delivery_notice}</p>
                      </div>
                      <time className="ml-auto text-[11px] text-ink-subtle">{formatRelative(item.created_at)}</time>
                    </Card>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState icon={Mail} title="로컬 이메일 큐가 비어 있어요" description="이메일 의도는 로컬 큐에만 기록되며 외부로 발송되지 않습니다." />
            )}
          </TabsContent>
        </Tabs>
      )}
    </PageTransition>
  )
}

function NotificationGroup({
  items,
  onRead,
  onAccept,
  onReject,
  actionPending,
  emptyTitle,
  emptyDescription = '새로운 알림이 도착하면 이곳에 표시됩니다.',
}: {
  items: NotificationItem[]
  onRead: (id: string) => void
  onAccept: (id: string) => void
  onReject: (id: string) => void
  actionPending: boolean
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
                'relative transition-all duration-200 hover:shadow-lift',
                !item.read && 'bg-primary-50/25',
              )}
            >
              <div className="flex items-start gap-3.5 p-4" onClick={() => onRead(item.id)}>
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
                  {item.actionKind !== 'respond_friend_request' && item.actionKind !== 'none' && item.href && (
                    <Button asChild size="sm" variant="ghost" className="mt-2">
                      <Link to={item.href} onClick={(event) => { event.stopPropagation(); onRead(item.id) }}>열기</Link>
                    </Button>
                  )}
                </div>

                <time className="shrink-0 text-[11.5px] text-ink-subtle">
                  {formatRelative(item.createdAt)}
                </time>
              </div>
              {item.actionKind === 'respond_friend_request' && (
                <div className="flex justify-end gap-2 border-t border-line-soft px-4 py-3">
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={actionPending}
                    onClick={() => onReject(item.resourceId)}
                  >
                    거절
                  </Button>
                  <Button
                    size="sm"
                    variant="primary"
                    disabled={actionPending}
                    onClick={() => onAccept(item.resourceId)}
                  >
                    수락
                  </Button>
                </div>
              )}
            </Card>
          </motion.li>
        )
      })}
    </motion.ul>
  )
}
