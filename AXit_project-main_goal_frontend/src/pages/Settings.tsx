import { CircleAlert, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import {
  useMyPreferences,
  useMyProfile,
  useUpdateMyPreferences,
  useUpdateMyProfile,
} from '@/api/queries'
import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { SectionCard } from '@/components/common/SectionCard'
import { PageTransition } from '@/components/layout/PageTransition'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { NotificationPreferenceMatrix, ProfileUpdateRequest } from '@axit/api-client'

const preferenceLabels: Array<{ kind: keyof NotificationPreferenceMatrix; label: string }> = [
  { kind: 'analysis_completed', label: 'AI 분석 완료' },
  { kind: 'mention', label: '멘션' },
  { kind: 'comment', label: '댓글' },
]

export default function Settings() {
  const profile = useMyProfile()
  const preferences = useMyPreferences()
  const updateProfile = useUpdateMyProfile()
  const updatePreferences = useUpdateMyPreferences()
  const [profileDraft, setProfileDraft] = useState<Omit<ProfileUpdateRequest, 'expected_version'>>()
  const [preferenceDraft, setPreferenceDraft] = useState<NotificationPreferenceMatrix>()

  useEffect(() => {
    if (profile.data) {
      setProfileDraft({
        display_name: profile.data.display_name,
        job_title: profile.data.job_title,
        language: profile.data.language,
      })
    }
  }, [profile.data])

  useEffect(() => {
    if (preferences.data) setPreferenceDraft(structuredClone(preferences.data.values))
  }, [preferences.data])

  const loading = profile.isLoading || preferences.isLoading
  const failed = profile.isError || preferences.isError

  return (
    <PageTransition className="space-y-6">
      <PageHeader title="설정" description="서버에 저장되는 내 프로필과 알림 수신 의도를 관리합니다." />
      {loading ? (
        <div className="flex items-center gap-2 rounded-xl border border-line bg-white p-6 text-sm text-ink-muted"><Loader2 className="size-4 animate-spin" />설정을 불러오는 중입니다.</div>
      ) : failed || !profile.data || !preferences.data || !profileDraft || !preferenceDraft ? (
        <EmptyState icon={CircleAlert} title="설정을 불러오지 못했어요" description="로그인 상태와 네트워크를 확인한 뒤 다시 시도해 주세요." action={<Button onClick={() => { void profile.refetch(); void preferences.refetch() }}>다시 시도</Button>} />
      ) : (
        <Tabs defaultValue="account">
          <TabsList>
            <TabsTrigger value="account">계정</TabsTrigger>
            <TabsTrigger value="notification">알림</TabsTrigger>
            <TabsTrigger value="unsupported">범위 외 기능</TabsTrigger>
          </TabsList>

          <TabsContent value="account">
            <SectionCard title="프로필" description="저장 후 새로고침하거나 다시 로그인해도 유지됩니다." contentClassName="pb-6">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2"><Label htmlFor="name">이름</Label><Input id="name" value={profileDraft.display_name} onChange={(e) => setProfileDraft({ ...profileDraft, display_name: e.target.value })} /></div>
                <div className="space-y-2"><Label htmlFor="email">이메일</Label><Input id="email" value={profile.data.email} readOnly disabled aria-readonly="true" /></div>
                <div className="space-y-2"><Label htmlFor="role">직무</Label><Input id="role" value={profileDraft.job_title ?? ''} onChange={(e) => setProfileDraft({ ...profileDraft, job_title: e.target.value || null })} /></div>
                <div className="space-y-2"><Label htmlFor="language">언어</Label><Select value={profileDraft.language} onValueChange={(value) => setProfileDraft({ ...profileDraft, language: value as ProfileUpdateRequest['language'] })}><SelectTrigger id="language" className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="ko">한국어</SelectItem><SelectItem value="en">English</SelectItem><SelectItem value="ja">日本語</SelectItem></SelectContent></Select></div>
              </div>
              <SaveRow
                pending={updateProfile.isPending}
                error={updateProfile.isError}
                success={updateProfile.isSuccess}
                onCancel={() => setProfileDraft({ display_name: profile.data.display_name, job_title: profile.data.job_title, language: profile.data.language })}
                onSave={() => updateProfile.mutate({ ...profileDraft, expected_version: profile.data.profile_version })}
              />
            </SectionCard>
          </TabsContent>

          <TabsContent value="notification">
            <SectionCard title="알림 설정" description="앱 알림과 이메일 의도를 저장합니다. 이메일은 로컬 큐에만 저장되었으며 외부로 발송되지 않았습니다." contentClassName="pb-6">
              <ul className="divide-y divide-line-soft">
                {preferenceLabels.map(({ kind, label }) => (
                  <li key={kind} className="space-y-3 py-4 first:pt-0">
                    <p className="text-[13.5px] font-bold text-ink">{label}</p>
                    <div className="flex flex-wrap gap-6">
                      <label className="flex items-center gap-2 text-[12.5px] text-ink-muted"><Switch checked={preferenceDraft[kind].in_app} onCheckedChange={(checked) => setPreferenceDraft({ ...preferenceDraft, [kind]: { ...preferenceDraft[kind], in_app: checked } })} />앱 알림</label>
                      <label className="flex items-center gap-2 text-[12.5px] text-ink-muted"><Switch checked={preferenceDraft[kind].email_intent} onCheckedChange={(checked) => setPreferenceDraft({ ...preferenceDraft, [kind]: { ...preferenceDraft[kind], email_intent: checked } })} />이메일 의도 <Badge variant="neutral">외부 미발송</Badge></label>
                    </div>
                  </li>
                ))}
              </ul>
              <SaveRow
                pending={updatePreferences.isPending}
                error={updatePreferences.isError}
                success={updatePreferences.isSuccess}
                onCancel={() => setPreferenceDraft(structuredClone(preferences.data.values))}
                onSave={() => updatePreferences.mutate({ values: preferenceDraft, expected_version: preferences.data.preferences_version })}
              />
            </SectionCard>
          </TabsContent>

          <TabsContent value="unsupported">
            <SectionCard title="이번 범위에 포함되지 않는 기능" description="지원되지 않는 기능을 저장된 것처럼 표시하지 않습니다." contentClassName="pb-6">
              <ul className="space-y-3 text-[13px] text-ink-muted">
                {['프로필 이미지 변경', 'AI 동작 개인화', '팀 전체 초대 설정', '플랜·결제·사용량', '실시간 채팅·현재 접속자', '공개 공유', '실제 이메일 발송'].map((label) => <li key={label} className="flex items-center justify-between rounded-lg bg-line-soft px-3 py-2"><span>{label}</span><Badge variant="neutral">범위 외</Badge></li>)}
              </ul>
            </SectionCard>
          </TabsContent>
        </Tabs>
      )}
    </PageTransition>
  )
}

function SaveRow({ pending, error, success, onCancel, onSave }: { pending: boolean; error: boolean; success: boolean; onCancel: () => void; onSave: () => void }) {
  return <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-line-soft pt-4">
    {error && <p role="alert" className="mr-auto text-[12px] text-danger">저장하지 못했습니다. 서버 값을 다시 확인해 주세요.</p>}
    {!error && success && <p role="status" className="mr-auto text-[12px] text-secondary-600">서버에 저장되었습니다.</p>}
    <Button variant="ghost" disabled={pending} onClick={onCancel}>취소</Button>
    <Button variant="primary" disabled={pending} onClick={onSave}>{pending ? '저장 중…' : '변경사항 저장'}</Button>
  </div>
}
