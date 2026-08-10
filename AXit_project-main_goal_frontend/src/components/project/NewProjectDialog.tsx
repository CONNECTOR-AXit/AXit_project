import { AlertCircle, ArrowRight, Check, Loader2, Plus, Sparkles, X } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError } from '@/api/client'
import {
  useCreateProject,
  useSuggestDescriptions,
  type DescriptionInterviewTurn,
  type DescriptionSuggestionQuestion,
} from '@/api/queries'
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
import { Progress } from '@/components/ui/progress'

export interface NewProjectDialogProps {
  /** 기본 버튼 대신 다른 트리거를 쓰고 싶을 때 전달합니다. */
  trigger?: ReactNode
}

// AI가 선택지 안에 "직접 입력" 같은 자유 응답 placeholder를 끼워 넣는 경우가
// 있어(예: "직접 입력(예: 특정 브랜드명)"), 클릭하면 그 문구 자체가 답변으로
// 제출돼버립니다. 그런 선택지는 걸러내고, 별도의 고정된 "기타" 버튼으로
// 직접 입력 UI를 켜고 끕니다.
const OTHER_OPTION_PATTERN = /^(기타|직접\s*입력)/

/** 새 프로젝트 생성 다이얼로그. */
export function NewProjectDialog({ trigger }: NewProjectDialogProps) {
  const navigate = useNavigate()
  const createProject = useCreateProject()
  const suggestDescriptions = useSuggestDescriptions()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  // "설명 구체화" 인터뷰 상태 — 질문 1개 -> 답변 -> (AI가 충분하다고 판단할 때까지
  // 반복) -> 확장된 설명 하나(샌드박스 박스)를 미리보기로 보여주고 체크/취소로
  // 반영 여부를 정합니다. 적용하면 description이 늘어나고 인터뷰 상태는
  // 초기화됩니다. 버튼을 다시 누르면 그 시점의 description을 초안 삼아 새
  // 인터뷰가 시작되므로, 반복해서 누를수록 설명이 계속 길어집니다.
  const [history, setHistory] = useState<DescriptionInterviewTurn[]>([])
  const [pendingQuestion, setPendingQuestion] = useState<DescriptionSuggestionQuestion | null>(
    null,
  )
  const [finalDescription, setFinalDescription] = useState<string | null>(null)
  const [customAnswer, setCustomAnswer] = useState('')
  const [showCustomAnswer, setShowCustomAnswer] = useState(false)

  const resetInterview = () => {
    setHistory([])
    setPendingQuestion(null)
    setFinalDescription(null)
    setCustomAnswer('')
    setShowCustomAnswer(false)
    suggestDescriptions.reset()
  }

  const reset = () => {
    setName('')
    setDescription('')
    resetInterview()
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!name.trim()) return
    const project = await createProject.mutateAsync({
      name: name.trim(),
      description: description.trim(),
    })
    sessionStorage.setItem('axit:active-project-id', project.id)
    setOpen(false)
    reset()
    navigate(`/projects/${project.id}/upload`)
  }

  const runInterviewStep = async (nextHistory: DescriptionInterviewTurn[], forceFinal = false) => {
    const result = await suggestDescriptions.mutateAsync({
      title: name.trim(),
      draft: description.trim(),
      history: nextHistory,
      forceFinal,
    })
    if (result.step === 'question') {
      setPendingQuestion(result.question)
      setShowCustomAnswer(false)
      setCustomAnswer('')
    } else {
      setPendingQuestion(null)
      setFinalDescription(result.description)
    }
  }

  const startInterview = () => {
    if (!name.trim()) return
    setFinalDescription(null)
    void runInterviewStep(history)
  }

  // "지금 답변으로 생성" — 질문을 그만 받고, 지금까지 답한 내용으로 바로
  // 확정 설명 후보를 받습니다 (답변을 버리지 않고 곧바로 정리해달라는 흐름).
  const finishInterviewNow = () => {
    void runInterviewStep(history, true)
  }

  const answerQuestion = (answer: string) => {
    const trimmed = answer.trim()
    if (!trimmed || !pendingQuestion) return
    const nextHistory = [...history, { question: pendingQuestion.question, answer: trimmed }]
    setHistory(nextHistory)
    setCustomAnswer('')
    void runInterviewStep(nextHistory)
  }

  const applyFinalDescription = () => {
    if (finalDescription === null) return
    setDescription(finalDescription)
    resetInterview()
  }

  const discardFinalDescription = () => {
    resetInterview()
  }

  const suggestError =
    suggestDescriptions.error instanceof ApiError ? suggestDescriptions.error.message : null
  const interviewBusy = suggestDescriptions.isPending

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) reset()
      }}
    >
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
            <div className="flex items-center justify-between gap-2">
              <Label htmlFor="project-description">설명 (선택)</Label>
              {!pendingQuestion && finalDescription === null && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="-mr-2 h-7 px-2 text-[11.5px] text-primary"
                  disabled={!name.trim() || interviewBusy}
                  onClick={startInterview}
                >
                  <Sparkles className="size-3.5" />
                  {interviewBusy ? 'AI가 생각하는 중...' : 'AI로 설명 구체화'}
                </Button>
              )}
            </div>
            <Textarea
              id="project-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="어떤 문서를 통합하는 프로젝트인지 간단히 적어주세요."
              rows={3}
            />

            {suggestError && (
              <p className="flex items-center gap-1.5 text-[11.5px] font-medium text-danger">
                <AlertCircle className="size-3.5 shrink-0" />
                {suggestError}
              </p>
            )}

            {pendingQuestion && (
              <div className="space-y-2 rounded-lg border border-primary-100 bg-primary-50/40 p-3">
                <div className="flex items-center gap-2">
                  <Progress
                    value={Math.round(pendingQuestion.clarity * 100)}
                    tone={pendingQuestion.clarity >= 0.8 ? 'success' : 'gradient'}
                    className="h-1.5 flex-1"
                  />
                  <span className="shrink-0 text-[10.5px] font-bold tabular-nums text-ink-subtle">
                    명확도 {Math.round(pendingQuestion.clarity * 100)}%
                  </span>
                </div>
                <div className="flex items-start justify-between gap-2">
                  <p className="text-[12.5px] font-bold text-ink">{pendingQuestion.question}</p>
                  <button
                    type="button"
                    onClick={finishInterviewNow}
                    disabled={interviewBusy}
                    className="flex shrink-0 items-center gap-1 rounded-full border border-line-soft bg-white px-2 py-1 text-[11px] font-semibold text-ink-muted transition-colors hover:border-primary-200 hover:text-primary disabled:opacity-50"
                    title="질문을 그만 받고 지금까지 답변으로 설명을 만듭니다"
                  >
                    <Sparkles className="size-3" />
                    지금 답변으로 생성
                  </button>
                </div>
                {interviewBusy && (
                  <p className="flex items-center gap-1.5 text-[11.5px] text-ink-muted">
                    <Loader2 className="size-3.5 animate-spin" />
                    AI가 다음 질문을 준비하는 중입니다...
                  </p>
                )}
                <div className="flex flex-wrap gap-1.5">
                  {pendingQuestion.options
                    .filter((option) => !OTHER_OPTION_PATTERN.test(option.trim()))
                    .map((option) => (
                      <button
                        key={option}
                        type="button"
                        disabled={interviewBusy}
                        onClick={() => answerQuestion(option)}
                        className="rounded-full border border-primary-200 bg-white px-2.5 py-1 text-[11.5px] font-semibold text-primary transition-colors hover:bg-primary-50 disabled:opacity-50"
                      >
                        {option}
                      </button>
                    ))}
                  {/* 정해진 답이 없을 수 있으니 "기타"는 AI 선택지와 별개로 항상 둡니다. */}
                  <button
                    type="button"
                    disabled={interviewBusy}
                    onClick={() => setShowCustomAnswer((prev) => !prev)}
                    aria-pressed={showCustomAnswer}
                    className="rounded-full border border-dashed border-ink-subtle px-2.5 py-1 text-[11.5px] font-semibold text-ink-muted transition-colors hover:bg-line-soft disabled:opacity-50 aria-pressed:border-primary-200 aria-pressed:text-primary"
                  >
                    기타 (직접 입력)
                  </button>
                </div>
                {showCustomAnswer && (
                  <div className="flex items-center gap-1.5">
                    <Input
                      value={customAnswer}
                      onChange={(event) => setCustomAnswer(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                          event.preventDefault()
                          answerQuestion(customAnswer)
                        }
                      }}
                      placeholder="답변을 입력하세요"
                      autoFocus
                      disabled={interviewBusy}
                      className="h-8 text-[12px]"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-8 shrink-0 px-2.5"
                      disabled={interviewBusy || !customAnswer.trim()}
                      onClick={() => answerQuestion(customAnswer)}
                    >
                      제출
                      <ArrowRight className="size-3.5" />
                    </Button>
                  </div>
                )}
              </div>
            )}

            {finalDescription !== null && (
              <div className="space-y-2 rounded-lg border border-primary-100 bg-primary-50/40 p-3">
                <p className="flex items-center gap-1.5 text-[11px] font-bold text-primary">
                  <Sparkles className="size-3.5" />
                  AI가 구체화한 설명
                </p>
                <p className="whitespace-pre-wrap rounded-md border border-line-soft bg-white p-2.5 text-[12px] leading-5 text-ink">
                  {finalDescription}
                </p>
                <div className="flex items-center justify-end gap-1.5">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 px-2.5 text-ink-muted"
                    onClick={discardFinalDescription}
                  >
                    <X className="size-3.5" />
                    취소
                  </Button>
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    className="h-8 px-2.5"
                    onClick={applyFinalDescription}
                  >
                    <Check className="size-3.5" />
                    적용
                  </Button>
                </div>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              취소
            </Button>
            {/* 이름이 비면 제출을 막아 빈 프로젝트가 생기지 않게 합니다. */}
            <Button
              type="submit"
              variant="gradient"
              disabled={!name.trim() || createProject.isPending}
            >
              프로젝트 만들기
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
