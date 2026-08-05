import { AnimatePresence, motion } from 'framer-motion'
import { ChevronRight, FilePlus2, PencilLine, Sparkles, Trash2, type LucideIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { AiSuggestion } from '@/types'

const kindMeta: Record<
  AiSuggestion['kind'],
  { icon: LucideIcon; heading: string; chip: string; action: string; actionClass: string }
> = {
  add: {
    icon: FilePlus2,
    heading: '추가 추천',
    chip: 'bg-primary-50 text-primary',
    action: '추가하기',
    actionClass: 'text-primary hover:bg-primary-50',
  },
  edit: {
    icon: PencilLine,
    heading: '수정 제안',
    chip: 'bg-warning-soft text-warning',
    action: '적용하기',
    actionClass: 'text-warning hover:bg-warning-soft',
  },
  remove: {
    icon: Trash2,
    heading: '삭제 제안',
    chip: 'bg-danger-soft text-danger',
    action: '확인하기',
    actionClass: 'text-danger hover:bg-danger-soft',
  },
}

const order: AiSuggestion['kind'][] = ['add', 'edit', 'remove']

export interface AiSuggestionPanelProps {
  suggestions: AiSuggestion[]
  onApply: (suggestion: AiSuggestion) => void
  onApplyAll: () => void
  className?: string
}

/** 유형별로 묶은 AI 추천 — 편집기의 우측 레일. */
export function AiSuggestionPanel({
  suggestions,
  onApply,
  onApplyAll,
  className,
}: AiSuggestionPanelProps) {
  return (
    <div className={cn('flex h-full flex-col', className)}>
      <div className="flex-1 space-y-5 overflow-y-auto p-4">
        {suggestions.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-14 text-center">
            <span className="flex size-11 items-center justify-center rounded-2xl bg-success-soft text-success">
              <Sparkles className="size-5" />
            </span>
            <p className="text-[13px] font-bold text-ink">모든 제안을 반영했어요</p>
            <p className="text-[12px] text-ink-muted">
              문서를 수정하면 AI가 새로운 제안을 다시 찾아드릴게요.
            </p>
          </div>
        )}

        {order.map((kind) => {
          const group = suggestions.filter((item) => item.kind === kind)
          if (group.length === 0) return null
          const meta = kindMeta[kind]

          return (
            <section key={kind} className="space-y-2">
              <h3 className="text-[13px] font-bold text-ink">{meta.heading}</h3>
              <AnimatePresence initial={false}>
                {group.map((suggestion) => (
                  <motion.div
                    key={suggestion.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, x: 20, height: 0 }}
                    transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
                    className="rounded-xl bg-line-soft p-3 transition-colors hover:bg-line"
                  >
                    <div className="flex items-start gap-2.5">
                      <span
                        className={cn(
                          'flex size-7 shrink-0 items-center justify-center rounded-lg',
                          meta.chip,
                        )}
                      >
                        <meta.icon className="size-3.5" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-[12.5px] leading-5 font-semibold text-ink">
                          {suggestion.title}
                        </p>
                        <p className="mt-1 text-[11.5px] leading-4 text-ink-muted">
                          {suggestion.detail}
                        </p>
                        <p className="mt-1.5 flex items-center gap-0.5 text-[11px] font-semibold text-ink-subtle">
                          <ChevronRight className="size-3" />
                          {suggestion.targetSection}
                        </p>
                      </div>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => onApply(suggestion)}
                        className={cn('h-7 shrink-0 px-2 text-[11.5px]', meta.actionClass)}
                      >
                        {meta.action}
                      </Button>
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </section>
          )
        })}
      </div>

      {suggestions.length > 0 && (
        <div className="border-t border-line p-3">
          <Button variant="subtle" className="w-full" onClick={onApplyAll}>
            <Sparkles />
            전체 제안 적용
          </Button>
        </div>
      )}
    </div>
  )
}
