import { Check, Info, Loader2, Quote, Sparkles, X } from 'lucide-react'
import {
  useLayoutEffect,
  useMemo,
  useRef,
  type CSSProperties,
  type ElementType,
  type FormEvent,
} from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { findSuggestionTargetIndex, visibleSuggestionText } from '@/lib/suggestionChanges'
import { cn } from '@/lib/utils'
import type { AiSuggestion, DocBlock } from '@/types'

export interface DocumentCanvasProps {
  blocks: DocBlock[]
  /** 목차 패널에서 현재 강조된 섹션 id. */
  activeBlockId?: string
  onSelectBlock?: (id: string) => void
  /** 실제로 편집 가능한(제목/문단) 블록의 텍스트가 바뀔 때마다 호출됩니다. */
  onBlockTextChange?: (blockId: string, text: string) => void
  onSelectRagAnchor?: (anchorId: string) => void
  /** source anchor ID별 원본 문서 제목. 같은 제목은 항상 같은 색상으로 표시됩니다. */
  ragAnchorLabels?: Record<string, string>
  /** 프로젝트 문서 목록의 색상 배정 순서. */
  ragTitleOrder?: string[]
  suggestions?: AiSuggestion[]
  resolvingSuggestionId?: string
  suggestionErrorId?: string
  suggestionError?: string | null
  onAcceptSuggestion?: (suggestion: AiSuggestion) => void
  onRejectSuggestion?: (suggestion: AiSuggestion) => void
  editable?: boolean
  className?: string
}

const _EDITABLE_TYPES = new Set<DocBlock['type']>(['heading', 'paragraph'])

/** 문서 표면. 블록을 contenteditable 로 두어 실제로 타이핑하는 느낌을 줍니다. */
export function DocumentCanvas({
  blocks,
  activeBlockId,
  onSelectBlock,
  onBlockTextChange,
  onSelectRagAnchor,
  ragAnchorLabels = {},
  ragTitleOrder = [],
  suggestions = [],
  resolvingSuggestionId,
  suggestionErrorId,
  suggestionError,
  onAcceptSuggestion,
  onRejectSuggestion,
  editable = true,
  className,
}: DocumentCanvasProps) {
  const blocksById = new Map(blocks.map((block) => [block.id, block]))
  const overflowRagTitleTones = useRef(new Map<string, CSSProperties>())
  const ragTitleTones = useMemo(
    () =>
      createRagTitleTones(
        [...ragTitleOrder, ...Object.values(ragAnchorLabels)],
        overflowRagTitleTones.current,
      ),
    [ragAnchorLabels, ragTitleOrder],
  )
  const suggestionsByTarget = useMemo(() => {
    const result = new Map<number, AiSuggestion[]>()
    for (const suggestion of suggestions) {
      const targetIndex = findSuggestionTargetIndex(blocks, suggestion)
      const displayIndex = targetIndex >= 0 ? targetIndex : blocks.length
      result.set(displayIndex, [...(result.get(displayIndex) ?? []), suggestion])
    }
    return result
  }, [blocks, suggestions])

  // contenteditable 영역에 발생하는 네이티브 input 이벤트의 target은 (실제로 글자가
  // 바뀐 안쪽 블록이 아니라) contenteditable 루트(article) 자신이라, event.target으로는
  // 어느 블록이 편집됐는지 알 수 없습니다 — 현재 캐럿(선택 영역) 기준으로 찾습니다.
  const handleInput = (_event: FormEvent<HTMLElement>) => {
    if (!onBlockTextChange) return
    const selection = window.getSelection()
    if (!selection || selection.rangeCount === 0) return
    const anchor = selection.getRangeAt(0).startContainer
    const anchorElement = anchor instanceof Element ? anchor : anchor.parentElement
    const section = anchorElement?.closest<HTMLElement>('[data-block-id]')
    const blockId = section?.dataset.blockId
    if (!blockId) return
    const block = blocksById.get(blockId)
    if (!block || !('text' in block) || (block.type !== 'heading' && block.type !== 'paragraph')) return
    const textElement = section.querySelector<HTMLElement>('[data-block-text]')
    if (!textElement) return
    const visibleText = textElement.textContent ?? ''
    const ragTags = extractRagAnchorIds(block.text).map((id) => `[RAG:${id}]`).join(' ')
    onBlockTextChange(blockId, `${visibleText.trimEnd()}${ragTags ? ` ${ragTags}` : ''}`)
  }

  return (
    <article
      data-document-canvas
      contentEditable={editable}
      suppressContentEditableWarning
      onInput={handleInput}
      onClick={(event) => {
        const section = (event.target as HTMLElement).closest<HTMLElement>('[data-block-id]')
        if (section?.dataset.blockId) onSelectBlock?.(section.dataset.blockId)
      }}
      className={cn(
        'mx-auto w-full max-w-[760px] space-y-1 px-6 py-10 outline-none sm:px-12',
        editable && 'focus:ring-2 focus:ring-primary-100 focus:ring-inset',
        className,
      )}
    >
      {blocks.map((block, blockIndex) => (
        <div key={block.id}>
        <section
          id={`block-${block.id}`}
          data-block-id={block.id}
          // 목록/표/콜아웃은 아직 저장 가능한 블록 형태가 아니라서 편집을 막습니다 —
          // 조용히 사라질 편집을 허용하지 않기 위함입니다.
          contentEditable={_EDITABLE_TYPES.has(block.type) ? undefined : false}
          className={cn(
            'group relative -mx-3 rounded-lg px-3 py-1.5 transition-colors',
            activeBlockId === block.id ? 'bg-primary-50/60' : 'hover:bg-line-soft/60',
          )}
        >
          {block.tag && block.tag !== 'RAG' && (
            <Badge
              contentEditable={false}
              variant="primary"
              title={`출처: ${block.tag}`}
              className="pointer-events-none absolute -top-1 -right-1 max-w-[220px] select-none gap-1 truncate opacity-0 transition-opacity group-hover:opacity-100"
            >
              <Quote className="size-2.5 shrink-0" />
              <span className="truncate">{block.tag}</span>
            </Badge>
          )}
          <BlockView block={block} />
          {ragAnchorIdsForBlock(block).length > 0 && (
            <div contentEditable={false} className="mt-1.5 flex flex-wrap gap-1.5">
              {ragAnchorIdsForBlock(block).map((anchorId) => {
                const label = ragAnchorLabels[anchorId] ?? '문서 확인 중…'
                return (
                  <button
                    key={anchorId}
                    type="button"
                    title={label}
                    style={ragTitleTones.get(label)}
                    className={cn(
                      'inline-flex max-w-[190px] items-center gap-1 rounded-full border px-2 py-0.5 text-[10.5px] font-bold transition-[filter] hover:brightness-95',
                      !ragTitleTones.has(label) && 'border-slate-200 bg-slate-50 text-slate-600',
                    )}
                    onClick={(event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      onSelectRagAnchor?.(anchorId)
                    }}
                  >
                    <Quote className="size-2.5 shrink-0" />
                    <span className="truncate">{truncateRagTitle(label)}</span>
                  </button>
                )
              })}
            </div>
          )}
        </section>
        {(suggestionsByTarget.get(blockIndex) ?? []).map((suggestion) => (
          <InlineSuggestion
            key={suggestion.id}
            suggestion={suggestion}
            target={block}
            isResolving={resolvingSuggestionId === suggestion.id}
            error={suggestionErrorId === suggestion.id ? suggestionError : null}
            onAccept={onAcceptSuggestion}
            onReject={onRejectSuggestion}
          />
        ))}
        </div>
      ))}
      {(suggestionsByTarget.get(blocks.length) ?? []).map((suggestion) => (
        <InlineSuggestion
          key={suggestion.id}
          suggestion={suggestion}
          isResolving={resolvingSuggestionId === suggestion.id}
          error={suggestionErrorId === suggestion.id ? suggestionError : null}
          onAccept={onAcceptSuggestion}
          onReject={onRejectSuggestion}
        />
      ))}
    </article>
  )
}

function InlineSuggestion({
  suggestion,
  target,
  isResolving,
  error,
  onAccept,
  onReject,
}: {
  suggestion: AiSuggestion
  target?: DocBlock
  isResolving: boolean
  error?: string | null
  onAccept?: (suggestion: AiSuggestion) => void
  onReject?: (suggestion: AiSuggestion) => void
}) {
  const before = target && 'text' in target ? visibleSuggestionText(target.text) : ''
  const showBefore = suggestion.kind !== 'add' && Boolean(before)
  const showAfter = suggestion.kind !== 'remove'

  return (
    <aside
      id={`suggestion-${suggestion.id}`}
      data-inline-suggestion={suggestion.id}
      contentEditable={false}
      className="my-2 rounded-xl border border-primary-100 bg-white p-3 shadow-sm"
    >
      <div className="flex items-center gap-2">
        <span className="flex size-6 items-center justify-center rounded-lg bg-primary-50 text-primary">
          <Sparkles className="size-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[11.5px] font-bold text-ink">{suggestion.title}</p>
          <p className="text-[10.5px] text-ink-subtle">AI 변경 제안</p>
        </div>
        <Button
          type="button"
          size="icon-sm"
          variant="ghost"
          aria-label="AI 제안 거절"
          title="적용하지 않기"
          disabled={isResolving}
          className="rounded-full text-danger hover:bg-danger-soft hover:text-danger"
          onClick={() => onReject?.(suggestion)}
        >
          <X />
        </Button>
        <Button
          type="button"
          size="icon-sm"
          variant="ghost"
          aria-label="AI 제안 적용"
          title="통합문서에 적용"
          disabled={isResolving}
          className="rounded-full bg-success-soft text-success hover:bg-success-soft hover:brightness-95"
          onClick={() => onAccept?.(suggestion)}
        >
          {isResolving ? <Loader2 className="animate-spin" /> : <Check />}
        </Button>
      </div>
      <div className="mt-2.5 space-y-1.5 text-[13px] leading-6">
        {showBefore && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-red-700 line-through decoration-red-500 decoration-2">
            <span className="mr-2 select-none font-bold no-underline">−</span>
            {before}
          </div>
        )}
        {showAfter && (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 font-medium text-emerald-800">
            <span className="mr-2 select-none font-bold">+</span>
            {visibleSuggestionText(suggestion.detail)}
          </div>
        )}
      </div>
      {error && !isResolving && (
        <p role="alert" className="mt-2 text-[11px] font-semibold text-danger">{error}</p>
      )}
    </aside>
  )
}

/**
 * React가 매 렌더마다 `{text}`를 자식으로 다시 그리면, 방금 브라우저가 직접
 * 반영한 타이핑과 경합해 캐럿이 맨 앞으로 튀는 문제가 있었습니다(React가
 * "새로 렌더"라고 판단해 텍스트 노드를 다시 만듦). DOM이 실제 텍스트를 갖고
 * 있게 두고, 우리가 마지막으로 반영한 값과 다를 때(= 우리 자신의 입력이
 * 아니라 외부에서 값이 바뀐 경우)만 명시적으로 textContent를 덮어씁니다.
 */
function EditableText({
  as: Tag,
  text,
  className,
}: {
  as: ElementType
  text: string
  className?: string
}) {
  const ref = useRef<HTMLElement>(null)
  const lastSyncedRef = useRef<string | null>(null)

  useLayoutEffect(() => {
    if (lastSyncedRef.current === text) return
    lastSyncedRef.current = text
    const el = ref.current
    if (el && el.textContent !== text) el.textContent = text
  }, [text])

  return <Tag ref={ref} data-block-text className={className} />
}

function BlockView({
  block,
}: {
  block: DocBlock
}) {
  switch (block.type) {
    case 'heading': {
      const sizes = {
        1: 'text-[26px] leading-9 font-extrabold mt-6',
        2: 'text-[19px] leading-7 font-bold mt-5',
        3: 'text-[16px] leading-6 font-bold mt-4',
      } as const
      const Tag = `h${block.level}` as 'h1' | 'h2' | 'h3'
      return (
        <EditableText as={Tag} text={visibleBlockText(block.text)} className={cn('tracking-tight text-ink', sizes[block.level])} />
      )
    }

    case 'paragraph':
      return <EditableText as="p" text={visibleBlockText(block.text)} className="text-[14.5px] leading-7 text-ink" />

    case 'list':
      return (
        <ul className="space-y-1.5 py-1">
          {block.items.map((item, index) => (
            <li key={index} className="flex items-start gap-2.5">
              <span className="mt-2.5 size-1.5 shrink-0 rounded-full bg-ink-subtle" />
              <span className="flex-1 text-[14.5px] leading-7 text-ink">
                {item}
              </span>
            </li>
          ))}
        </ul>
      )

    case 'table':
      return (
        <div className="my-2 overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[440px] border-collapse text-left">
            <thead>
              <tr className="bg-line-soft">
                {block.columns.map((column) => (
                  <th
                    key={column}
                    scope="col"
                    className="border-b border-line px-3.5 py-2.5 text-[12.5px] font-bold text-ink"
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={rowIndex} className="border-b border-line-soft last:border-0">
                  {row.map((cell, cellIndex) => (
                    <td
                      key={cellIndex}
                      className={cn(
                        'px-3.5 py-2.5 text-[13px] text-ink',
                        cellIndex === 0 && 'font-semibold',
                        cellIndex === 1 && 'tabular-nums',
                      )}
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )

    case 'callout':
      return (
        <div className="my-2 flex items-start gap-2.5 rounded-lg border border-warning/25 bg-warning-soft/60 px-3.5 py-3">
          <Info className="mt-0.5 size-4 shrink-0 text-warning" />
          <p className="text-[13px] leading-6 text-ink">
            {block.text}
          </p>
        </div>
      )
  }
}

const RAG_TAG_PATTERN = /\[RAG:([0-9a-f]{8}-[0-9a-f-]{27})\]/gi

function extractRagAnchorIds(text: string) {
  return Array.from(text.matchAll(RAG_TAG_PATTERN), (match) => match[1]!).filter(
    (value, index, values) => values.indexOf(value) === index,
  )
}

function visibleBlockText(text: string) {
  return text.replace(RAG_TAG_PATTERN, '').replace(/\s+$/g, '')
}

function ragAnchorIdsForBlock(block: DocBlock) {
  return 'text' in block ? extractRagAnchorIds(block.text) : []
}

const LOADING_RAG_TITLES = new Set(['문서 확인 중…', '원본 문서', '근거 문서'])
const FIXED_RAG_TONE_COUNT = 20

/**
 * 현재 문서에 처음 등장한 순서대로 20개의 고정 색상을 배정합니다. 21번째부터는
 * 임의 색상을 만들되 overflowTones에 저장하여 같은 제목의 모든 RAG 태그가
 * 이후 렌더에서도 동일한 색상을 공유하게 합니다.
 */
function createRagTitleTones(
  titles: string[],
  overflowTones: Map<string, CSSProperties>,
) {
  const uniqueTitles = [...new Set(titles.filter((title) => !LOADING_RAG_TITLES.has(title)))]
  const usedColors = new Set<string>()

  return new Map<string, CSSProperties>(
    uniqueTitles.map((title, index) => {
      if (index < FIXED_RAG_TONE_COUNT) {
        const fixedTone = ragToneFromHue(index * 137.508)
        usedColors.add(String(fixedTone.color))
        return [title, fixedTone]
      }

      const existingTone = overflowTones.get(title)
      if (existingTone && !usedColors.has(String(existingTone.color))) {
        usedColors.add(String(existingTone.color))
        return [title, existingTone]
      }

      let randomTone = ragToneFromHue(Math.random() * 360)
      while (usedColors.has(String(randomTone.color))) {
        randomTone = ragToneFromHue(Math.random() * 360)
      }
      overflowTones.set(title, randomTone)
      usedColors.add(String(randomTone.color))
      return [title, randomTone]
    }),
  )
}

function ragToneFromHue(hue: number): CSSProperties {
  const normalizedHue = Math.round(hue % 360)
  return {
    borderColor: `hsl(${normalizedHue} 62% 76%)`,
    backgroundColor: `hsl(${normalizedHue} 78% 96%)`,
    color: `hsl(${normalizedHue} 64% 30%)`,
  }
}

function truncateRagTitle(title: string) {
  return title.length > 16 ? `${title.slice(0, 16)}…` : title
}
