import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Bold,
  Heading1,
  Heading2,
  Heading3,
  Italic,
  Link2,
  List,
  ListOrdered,
  MoreHorizontal,
  Redo2,
  Table,
  Underline,
  Undo2,
  type LucideIcon,
} from 'lucide-react'
import { useRef } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Tooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

interface ToolButton {
  icon: LucideIcon
  label: string
  command: string
  value?: string
}

const groups: ToolButton[][] = [
  [
    { icon: Heading1, label: '제목 1', command: 'formatBlock', value: 'h1' },
    { icon: Heading2, label: '제목 2', command: 'formatBlock', value: 'h2' },
    { icon: Heading3, label: '제목 3', command: 'formatBlock', value: 'h3' },
  ],
  [
    { icon: Bold, label: '굵게', command: 'bold' },
    { icon: Italic, label: '기울임', command: 'italic' },
    { icon: Underline, label: '밑줄', command: 'underline' },
  ],
  [
    { icon: List, label: '글머리 목록', command: 'insertUnorderedList' },
    { icon: ListOrdered, label: '번호 목록', command: 'insertOrderedList' },
  ],
  [
    { icon: AlignLeft, label: '왼쪽 정렬', command: 'justifyLeft' },
    { icon: AlignCenter, label: '가운데 정렬', command: 'justifyCenter' },
    { icon: AlignRight, label: '오른쪽 정렬', command: 'justifyRight' },
  ],
  [
    { icon: Link2, label: '링크', command: 'createLink' },
    { icon: Table, label: '표', command: 'insertHTML', value: '<table><tbody><tr><td>내용</td><td>내용</td></tr><tr><td>내용</td><td>내용</td></tr></tbody></table>' },
  ],
]

export interface EditorToolbarProps {
  onCommand?: (label: string) => void
  className?: string
}

/** 서식 툴바. 각 명령은 `onCommand` 로 흘려보내 데모에서 로깅할 수 있습니다. */
export function EditorToolbar({ onCommand, className }: EditorToolbarProps) {
  const savedRange = useRef<Range | null>(null)

  const rememberSelection = () => {
    const selection = document.getSelection()
    if (!selection?.rangeCount) return
    const range = selection.getRangeAt(0)
    const canvas = document.querySelector('[data-document-canvas]')
    if (canvas?.contains(range.commonAncestorContainer)) savedRange.current = range.cloneRange()
  }

  const run = (label: string, command: string, value?: string) => {
    const selection = document.getSelection()
    if (savedRange.current && selection) {
      selection.removeAllRanges()
      selection.addRange(savedRange.current)
    }
    let commandValue = value
    if (command === 'createLink') {
      commandValue = window.prompt('연결할 주소를 입력하세요', 'https://')?.trim()
      if (!commandValue) return
    }
    document.execCommand(command, false, commandValue)
    rememberSelection()
    onCommand?.(label)
  }

  return (
    <div
      className={cn(
        'scrollbar-none flex items-center gap-1 overflow-x-auto border-b border-line bg-white px-3 py-2',
        className,
      )}
      role="toolbar"
      aria-label="문서 서식"
      onPointerDownCapture={rememberSelection}
    >
      <Select defaultValue="body" onValueChange={(value) => run(value === 'body' ? '본문' : value === 'quote' ? '인용' : `제목 ${value.slice(1)}`, 'formatBlock', value === 'body' ? 'p' : value === 'quote' ? 'blockquote' : value)}>
        <SelectTrigger className="h-8 w-[92px] shrink-0 text-[12.5px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="body">본문</SelectItem>
          <SelectItem value="h1">제목 1</SelectItem>
          <SelectItem value="h2">제목 2</SelectItem>
          <SelectItem value="quote">인용</SelectItem>
        </SelectContent>
      </Select>

      <Separator orientation="vertical" className="mx-1 h-5 shrink-0" />

      <ToolIcon icon={Undo2} label="실행 취소" command="undo" onRun={run} />
      <ToolIcon icon={Redo2} label="다시 실행" command="redo" onRun={run} />

      {groups.map((group, index) => (
        <span key={index} className="flex shrink-0 items-center gap-1">
          <Separator orientation="vertical" className="mx-1 h-5" />
          {group.map((tool) => (
            <ToolIcon key={tool.label} {...tool} onRun={run} />
          ))}
        </span>
      ))}

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" className="shrink-0" aria-label="추가 서식">
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem onSelect={() => run('코드 블록', 'formatBlock', 'pre')}>코드 블록</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => run('구분선', 'insertHorizontalRule')}>구분선</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => run('콜아웃', 'formatBlock', 'blockquote')}>콜아웃</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

function ToolIcon({
  icon: Icon,
  label,
  command,
  value,
  onRun,
}: ToolButton & { onRun: (label: string, command: string, value?: string) => void }) {
  return (
    <Tooltip label={label}>
      <Button
        variant="ghost"
        size="icon-sm"
        className="shrink-0"
        aria-label={label}
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => onRun(label, command, value)}
      >
        <Icon />
      </Button>
    </Tooltip>
  )
}
