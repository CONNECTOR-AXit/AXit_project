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
}

const groups: ToolButton[][] = [
  [
    { icon: Heading1, label: '제목 1' },
    { icon: Heading2, label: '제목 2' },
    { icon: Heading3, label: '제목 3' },
  ],
  [
    { icon: Bold, label: '굵게' },
    { icon: Italic, label: '기울임' },
    { icon: Underline, label: '밑줄' },
  ],
  [
    { icon: List, label: '글머리 목록' },
    { icon: ListOrdered, label: '번호 목록' },
  ],
  [
    { icon: AlignLeft, label: '왼쪽 정렬' },
    { icon: AlignCenter, label: '가운데 정렬' },
    { icon: AlignRight, label: '오른쪽 정렬' },
  ],
  [
    { icon: Link2, label: '링크' },
    { icon: Table, label: '표' },
  ],
]

export interface EditorToolbarProps {
  onCommand?: (label: string) => void
  className?: string
}

/** 서식 툴바. 각 명령은 `onCommand` 로 흘려보내 데모에서 로깅할 수 있습니다. */
export function EditorToolbar({ onCommand, className }: EditorToolbarProps) {
  return (
    <div
      className={cn(
        'scrollbar-none flex items-center gap-1 overflow-x-auto border-b border-line bg-white px-3 py-2',
        className,
      )}
      role="toolbar"
      aria-label="문서 서식"
    >
      <Select defaultValue="body">
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

      <ToolIcon icon={Undo2} label="실행 취소" onCommand={onCommand} />
      <ToolIcon icon={Redo2} label="다시 실행" onCommand={onCommand} />

      {groups.map((group, index) => (
        <span key={index} className="flex shrink-0 items-center gap-1">
          <Separator orientation="vertical" className="mx-1 h-5" />
          {group.map((tool) => (
            <ToolIcon key={tool.label} {...tool} onCommand={onCommand} />
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
          <DropdownMenuItem onSelect={() => onCommand?.('코드 블록')}>코드 블록</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => onCommand?.('구분선')}>구분선</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => onCommand?.('콜아웃')}>콜아웃</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

function ToolIcon({
  icon: Icon,
  label,
  onCommand,
}: ToolButton & { onCommand?: (label: string) => void }) {
  return (
    <Tooltip label={label}>
      <Button
        variant="ghost"
        size="icon-sm"
        className="shrink-0"
        aria-label={label}
        onClick={() => onCommand?.(label)}
      >
        <Icon />
      </Button>
    </Tooltip>
  )
}
