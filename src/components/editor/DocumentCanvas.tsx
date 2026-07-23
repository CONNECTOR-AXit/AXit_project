import { Info } from 'lucide-react'

import { Badge, type BadgeProps } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { BlockTag, DocBlock } from '@/types'

const tagVariant: Record<BlockTag, BadgeProps['variant']> = {
  공통: 'success',
  통합: 'primary',
  'AI 보완': 'secondary',
  '차이 조정': 'warning',
}

export interface DocumentCanvasProps {
  blocks: DocBlock[]
  /** 목차 패널에서 현재 강조된 섹션 id. */
  activeBlockId?: string
  onSelectBlock?: (id: string) => void
  onEdit?: () => void
  editable?: boolean
  className?: string
}

/** 문서 표면. 블록을 contenteditable 로 두어 실제로 타이핑하는 느낌을 줍니다. */
export function DocumentCanvas({
  blocks,
  activeBlockId,
  onSelectBlock,
  onEdit,
  editable = true,
  className,
}: DocumentCanvasProps) {
  return (
    <article className={cn('mx-auto w-full max-w-[760px] space-y-1 px-6 py-10 sm:px-12', className)}>
      {blocks.map((block) => (
        <section
          key={block.id}
          id={`block-${block.id}`}
          onClick={() => onSelectBlock?.(block.id)}
          className={cn(
            'group relative -mx-3 rounded-lg px-3 py-1.5 transition-colors',
            activeBlockId === block.id ? 'bg-primary-50/60' : 'hover:bg-line-soft/60',
          )}
        >
          {block.tag && (
            <Badge
              variant={tagVariant[block.tag]}
              className="absolute -top-1 -right-1 opacity-0 transition-opacity group-hover:opacity-100"
            >
              {block.tag}
            </Badge>
          )}
          <BlockView block={block} editable={editable} onEdit={onEdit} />
        </section>
      ))}
    </article>
  )
}

function BlockView({
  block,
  editable,
  onEdit,
}: {
  block: DocBlock
  editable: boolean
  onEdit?: () => void
}) {
  const editProps = {
    contentEditable: editable,
    suppressContentEditableWarning: true,
    onInput: onEdit,
  }

  switch (block.type) {
    case 'heading': {
      const sizes = {
        1: 'text-[26px] leading-9 font-extrabold mt-6',
        2: 'text-[19px] leading-7 font-bold mt-5',
        3: 'text-[16px] leading-6 font-bold mt-4',
      } as const
      const Tag = `h${block.level}` as 'h1' | 'h2' | 'h3'
      return (
        <Tag {...editProps} className={cn('tracking-tight text-ink', sizes[block.level])}>
          {block.text}
        </Tag>
      )
    }

    case 'paragraph':
      return (
        <p {...editProps} className="text-[14.5px] leading-7 text-ink">
          {block.text}
        </p>
      )

    case 'list':
      return (
        <ul className="space-y-1.5 py-1">
          {block.items.map((item, index) => (
            <li key={index} className="flex items-start gap-2.5">
              <span className="mt-2.5 size-1.5 shrink-0 rounded-full bg-ink-subtle" />
              <span {...editProps} className="flex-1 text-[14.5px] leading-7 text-ink">
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
                      {...editProps}
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
          <p {...editProps} className="text-[13px] leading-6 text-ink">
            {block.text}
          </p>
        </div>
      )
  }
}
