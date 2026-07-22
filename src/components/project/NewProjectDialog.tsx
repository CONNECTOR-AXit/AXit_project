import { Plus } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input, Textarea } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'

export interface NewProjectDialogProps {
  /** 기본 버튼 대신 다른 트리거를 쓰고 싶을 때 전달합니다. */
  trigger?: ReactNode
}

/** 새 프로젝트 생성 다이얼로그. */
export function NewProjectDialog({ trigger }: NewProjectDialogProps) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [autoAnalyze, setAutoAnalyze] = useState(true)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!name.trim()) return
    setOpen(false)
    setName('')
    setDescription('')
    // 데모 빌드에서는 생성 대신 업로드 단계로 넘깁니다.
    navigate('/upload')
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button variant="primary">
            <Plus />새 프로젝트
          </Button>
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>새 프로젝트 만들기</DialogTitle>
          <DialogDescription>
            통합할 문서를 모아둘 프로젝트를 만듭니다. 생성 후 바로 문서를 업로드할 수 있어요.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="project-name">프로젝트명</Label>
            <Input
              id="project-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="예: 마케팅 캠페인 기획안 통합"
              autoFocus
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="project-description">설명 (선택)</Label>
            <Textarea
              id="project-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="어떤 문서를 통합하는 프로젝트인지 간단히 적어주세요."
              rows={3}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="project-visibility">공개 범위</Label>
            <Select defaultValue="member">
              <SelectTrigger id="project-visibility" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="team">팀 전체 공개</SelectItem>
                <SelectItem value="member">초대한 멤버만</SelectItem>
                <SelectItem value="private">나만 보기</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center justify-between gap-4 rounded-lg border border-line bg-line-soft/60 px-3.5 py-3">
            <div className="min-w-0">
              <p className="text-[13px] font-bold text-ink">업로드 후 자동 분석</p>
              <p className="text-[12px] leading-4 text-ink-muted">
                문서가 2개 이상 모이면 AI 분석을 자동으로 시작합니다.
              </p>
            </div>
            <Switch
              checked={autoAnalyze}
              onCheckedChange={setAutoAnalyze}
              aria-label="업로드 후 자동 분석"
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              취소
            </Button>
            {/* 이름이 비면 제출을 막아 빈 프로젝트가 생기지 않게 합니다. */}
            <Button type="submit" variant="gradient" disabled={!name.trim()}>
              프로젝트 만들기
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
