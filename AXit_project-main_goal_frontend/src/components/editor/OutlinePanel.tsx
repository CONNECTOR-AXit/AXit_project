import { cn } from '@/lib/utils'
import type { DocBlock } from '@/types'

export interface OutlineNode {
  id: string
  text: string
  level: 1 | 2 | 3
}

export interface OutlinePanelProps {
  blocks: DocBlock[]
  activeId?: string
  onSelect: (id: string) => void
  className?: string
}

/** heading 블록에서 문서 목차를 뽑아냅니다. */
export function outlineFrom(blocks: DocBlock[]): OutlineNode[] {
  return blocks
    .filter((block): block is Extract<DocBlock, { type: 'heading' }> => block.type === 'heading')
    .map((block) => ({ id: block.id, text: block.text, level: block.level }))
}

/** 문서 구조(목차) 패널. 클릭하면 해당 블록으로 스크롤합니다. */
export function OutlinePanel({ blocks, activeId, onSelect, className }: OutlinePanelProps) {
  const nodes = outlineFrom(blocks)

  return (
    <nav className={cn('space-y-0.5', className)} aria-label="문서 구조">
      {nodes.map((node) => (
        <button
          key={node.id}
          type="button"
          onClick={() => onSelect(node.id)}
          className={cn(
            'block w-full truncate rounded-md px-2.5 py-1.5 text-left text-[12.5px] transition-colors',
            node.level === 3 && 'pl-6',
            node.level === 2 && 'pl-4',
            activeId === node.id
              ? 'bg-primary-50 font-bold text-primary'
              : 'font-medium text-ink-muted hover:bg-line-soft hover:text-ink',
          )}
        >
          {node.text}
        </button>
      ))}
    </nav>
  )
}
