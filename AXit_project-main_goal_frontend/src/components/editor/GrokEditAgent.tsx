import { Bot, Loader2, Send, Sparkles } from 'lucide-react'
import { useState } from 'react'

import { useRunGrokEditTask } from '@/api/queries'
import { Button } from '@/components/ui/button'

interface GrokEditAgentProps {
  projectId: string
  onSuggestionsCreated: () => void
}

export function GrokEditAgent({ projectId, onSuggestionsCreated }: GrokEditAgentProps) {
  const [instruction, setInstruction] = useState('')
  const [lastResult, setLastResult] = useState<string | null>(null)
  const task = useRunGrokEditTask(projectId)

  const submit = async () => {
    const value = instruction.trim()
    if (!value || task.isPending) return
    setLastResult(null)
    try {
      const suggestions = await task.mutateAsync(value)
      setLastResult(`AI가 원본 문서를 다시 확인해 ${suggestions.length}개의 수정 제안을 만들었습니다.`)
      setInstruction('')
      onSuggestionsCreated()
    } catch {
      // 오류 문구는 mutation 상태에서 안정적으로 표시합니다.
    }
  }

  return (
    <section className="mt-4 rounded-xl border border-primary-100 bg-primary-50/45 p-3" aria-label="AI 문서 수정 작업">
      <p className="flex items-center gap-1.5 text-[12px] font-bold text-primary">
        <Bot className="size-3.5" />
        AI 문서 수정
      </p>
      <p className="mt-1 text-[11px] leading-4 text-ink-muted">
        수정 지시를 입력하면 업로드 문서의 RAG 근거를 다시 확인하고 적용 가능한 제안을 만듭니다.
      </p>
      <textarea
        value={instruction}
        onChange={(event) => setInstruction(event.target.value)}
        placeholder="예: 보안 조건과 비용 수치를 원본 파일에서 다시 확인해 문서를 수정해줘"
        maxLength={4000}
        disabled={task.isPending}
        className="mt-2 min-h-24 w-full resize-y rounded-lg border border-line bg-white px-2.5 py-2 text-[12px] leading-5 text-ink outline-none focus:border-primary"
      />
      <Button
        type="button"
        size="sm"
        className="mt-2 w-full"
        disabled={!instruction.trim() || task.isPending}
        onClick={() => void submit()}
      >
        {task.isPending ? <Loader2 className="animate-spin" /> : <Send />}
        {task.isPending ? '원본 문서 재확인 중…' : 'AI에게 수정 요청'}
      </Button>
      {lastResult && (
        <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-4 text-secondary-600">
          <Sparkles className="mt-0.5 size-3 shrink-0" />
          {lastResult}
        </p>
      )}
      {task.isError && (
        <p role="alert" className="mt-2 text-[11px] leading-4 text-danger">
          AI가 수정 제안을 만들지 못했습니다. 잠시 후 같은 요청을 다시 실행해주세요.
        </p>
      )}
    </section>
  )
}
