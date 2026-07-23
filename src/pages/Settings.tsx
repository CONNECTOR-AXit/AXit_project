import { Sparkles } from 'lucide-react'
import { useState } from 'react'

import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { UserAvatar } from '@/components/common/UserAvatar'
import { PageTransition } from '@/components/layout/PageTransition'
import { MemberList } from '@/components/project/MemberList'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { projects } from '@/data/projects'
import { currentUser } from '@/data/user'

interface ToggleSetting {
  id: string
  label: string
  description: string
  defaultOn: boolean
}

const notificationSettings: ToggleSetting[] = [
  {
    id: 'analysis',
    label: 'AI 분석 완료 알림',
    description: '분석이 끝나면 이메일과 앱 알림을 보냅니다.',
    defaultOn: true,
  },
  {
    id: 'mention',
    label: '멘션 알림',
    description: '문서에서 나를 언급했을 때 알려줍니다.',
    defaultOn: true,
  },
  {
    id: 'comment',
    label: '댓글 알림',
    description: '내가 참여한 문서에 새 댓글이 달리면 알려줍니다.',
    defaultOn: false,
  },
  {
    id: 'weekly',
    label: '주간 리포트',
    description: '매주 월요일 아침에 지난 주 활동을 정리해 보냅니다.',
    defaultOn: true,
  },
]

const aiSettings: ToggleSetting[] = [
  {
    id: 'auto-analyze',
    label: '업로드 후 자동 분석',
    description: '문서가 2개 이상 모이면 분석을 자동으로 시작합니다.',
    defaultOn: true,
  },
  {
    id: 'auto-suggest',
    label: '편집 중 실시간 추천',
    description: '통합 문서를 편집하는 동안 AI가 개선점을 제안합니다.',
    defaultOn: true,
  },
  {
    id: 'keep-source',
    label: '원본 출처 표시',
    description: '통합 문서의 각 문단에 어떤 원본에서 왔는지 표시합니다.',
    defaultOn: true,
  },
]

export default function Settings() {
  const [toggles, setToggles] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(
      [...notificationSettings, ...aiSettings].map((item) => [item.id, item.defaultOn]),
    ),
  )

  const setToggle = (id: string, value: boolean) =>
    setToggles((prev) => ({ ...prev, [id]: value }))

  return (
    <PageTransition className="space-y-6">
      <PageHeader title="설정" description="계정, 알림, AI 분석 동작을 관리하세요." />

      <Tabs defaultValue="account">
        <TabsList>
          <TabsTrigger value="account">계정</TabsTrigger>
          <TabsTrigger value="notification">알림</TabsTrigger>
          <TabsTrigger value="ai">AI 분석</TabsTrigger>
          <TabsTrigger value="team">팀</TabsTrigger>
          <TabsTrigger value="plan">플랜</TabsTrigger>
        </TabsList>

        {/* 계정 */}
        <TabsContent value="account" className="space-y-5">
          <SectionCard title="프로필" description="다른 멤버에게 표시되는 정보입니다.">
            <div className="flex flex-wrap items-center gap-4">
              <UserAvatar user={currentUser} size="lg" />
              <div className="min-w-0">
                <p className="text-[15px] font-bold text-ink">{currentUser.name}</p>
                <p className="text-[12.5px] text-ink-muted">{currentUser.email}</p>
              </div>
              <Button variant="outline" size="sm" className="ml-auto">
                이미지 변경
              </Button>
            </div>

            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="name">이름</Label>
                <Input id="name" defaultValue={currentUser.name} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="email">이메일</Label>
                <Input id="email" type="email" defaultValue={currentUser.email} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="role">직무</Label>
                <Input id="role" defaultValue="프로덕트 매니저" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="language">언어</Label>
                <Select defaultValue="ko">
                  <SelectTrigger id="language" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ko">한국어</SelectItem>
                    <SelectItem value="en">English</SelectItem>
                    <SelectItem value="ja">日本語</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="mt-5 flex justify-end gap-2 border-t border-line-soft pt-4">
              <Button variant="ghost">취소</Button>
              <Button variant="primary">변경사항 저장</Button>
            </div>
          </SectionCard>
        </TabsContent>

        {/* 알림 */}
        <TabsContent value="notification">
          <SectionCard title="알림 설정" description="받고 싶은 알림만 켜두세요.">
            <SettingToggles items={notificationSettings} values={toggles} onChange={setToggle} />
          </SectionCard>
        </TabsContent>

        {/* AI */}
        <TabsContent value="ai" className="space-y-5">
          <SectionCard title="AI 분석 동작" description="문서를 통합하는 방식을 조정합니다.">
            <SettingToggles items={aiSettings} values={toggles} onChange={setToggle} />
          </SectionCard>

          <SectionCard title="분석 정확도" description="느릴수록 더 꼼꼼하게 비교합니다.">
            <Select defaultValue="balanced">
              <SelectTrigger className="w-full sm:w-[280px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fast">빠르게 (약 1분)</SelectItem>
                <SelectItem value="balanced">균형 (약 2분)</SelectItem>
                <SelectItem value="thorough">정밀 (약 5분)</SelectItem>
              </SelectContent>
            </Select>
          </SectionCard>
        </TabsContent>

        {/* 팀 */}
        <TabsContent value="team">
          <SectionCard
            title="팀 멤버"
            description="워크스페이스에 참여 중인 멤버입니다."
            action={
              <Button variant="primary" size="sm" className="-mt-1">
                멤버 초대
              </Button>
            }
          >
            <MemberList members={projects[0]!.members} />
          </SectionCard>
        </TabsContent>

        {/* 플랜 */}
        <TabsContent value="plan" className="space-y-5">
          <Card className="overflow-hidden border-primary-100">
            <div className="brand-gradient h-1 w-full" />
            <div className="flex flex-wrap items-center gap-4 p-5">
              <span className="brand-gradient flex size-11 shrink-0 items-center justify-center rounded-xl text-white shadow-brand">
                <Sparkles className="size-5" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-[15px] font-bold text-ink">
                  AXit Team
                  <Badge variant="primary">현재 플랜</Badge>
                </p>
                <p className="mt-0.5 text-[12.5px] text-ink-muted">
                  월 ₩49,000 · 다음 결제일 2024.06.15
                </p>
              </div>
              <Button variant="gradient">플랜 업그레이드</Button>
            </div>
          </Card>

          <SectionCard title="사용량" description="이번 달 사용 현황입니다.">
            <div className="space-y-5">
              <UsageRow label="AI 분석" used={32} total={50} unit="회" />
              <UsageRow label="저장 용량" used={8} total={10} unit="GB" />
              <UsageRow label="팀 멤버" used={4} total={10} unit="명" />
            </div>
          </SectionCard>
        </TabsContent>
      </Tabs>
    </PageTransition>
  )
}

function SettingToggles({
  items,
  values,
  onChange,
}: {
  items: ToggleSetting[]
  values: Record<string, boolean>
  onChange: (id: string, value: boolean) => void
}) {
  return (
    <ul className="divide-y divide-line-soft">
      {items.map((item) => (
        <li
          key={item.id}
          className="flex items-center justify-between gap-6 py-3.5 first:pt-0 last:pb-0"
        >
          <div className="min-w-0">
            <p className="text-[13.5px] font-bold text-ink">{item.label}</p>
            <p className="mt-0.5 text-[12.5px] leading-5 text-ink-muted">{item.description}</p>
          </div>
          <Switch
            checked={values[item.id] ?? item.defaultOn}
            onCheckedChange={(value) => onChange(item.id, value)}
            aria-label={item.label}
          />
        </li>
      ))}
    </ul>
  )
}

function UsageRow({
  label,
  used,
  total,
  unit,
}: {
  label: string
  used: number
  total: number
  unit: string
}) {
  const pct = Math.round((used / total) * 100)
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <span className="text-[13px] font-bold text-ink">{label}</span>
        <span className="text-[12.5px] font-semibold text-ink-muted tabular-nums">
          {used} / {total}
          {unit}
        </span>
      </div>
      <Progress value={pct} tone={pct >= 80 ? 'warning' : 'gradient'} className="h-2" />
    </div>
  )
}
