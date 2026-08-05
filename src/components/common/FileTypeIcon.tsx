import { FileSpreadsheet, FileText, FileType2, Presentation, type LucideIcon } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { FileKind } from '@/types'

interface KindStyle {
  icon: LucideIcon
  label: string
  className: string
}

/** 확장자별 아이콘. 형식 구분은 아이콘 모양으로만 하고, 배경은 다른 아이콘과 동일하게 회색으로 둡니다. */
export const kindStyles: Record<FileKind, KindStyle> = {
  pdf: { icon: FileType2, label: 'PDF', className: 'bg-line-soft text-ink-muted' },
  docx: { icon: FileText, label: 'DOCX', className: 'bg-line-soft text-ink-muted' },
  hwp: { icon: FileText, label: 'HWP', className: 'bg-line-soft text-ink-muted' },
  txt: { icon: FileText, label: 'TXT', className: 'bg-line-soft text-ink-muted' },
  pptx: { icon: Presentation, label: 'PPTX', className: 'bg-line-soft text-ink-muted' },
  xlsx: { icon: FileSpreadsheet, label: 'XLSX', className: 'bg-line-soft text-ink-muted' },
}

const sizeClass = {
  sm: 'size-8 rounded-lg [&_svg]:size-4',
  md: 'size-10 rounded-xl [&_svg]:size-[18px]',
  lg: 'size-12 rounded-xl [&_svg]:size-5',
} as const

export interface FileTypeIconProps {
  kind: FileKind
  size?: keyof typeof sizeClass
  className?: string
}

export function FileTypeIcon({ kind, size = 'md', className }: FileTypeIconProps) {
  const { icon: Icon, className: tone } = kindStyles[kind]
  return (
    <span
      className={cn('flex shrink-0 items-center justify-center', sizeClass[size], tone, className)}
      aria-hidden="true"
    >
      <Icon strokeWidth={2} />
    </span>
  )
}

/** 파일명에서 FileKind 를 추론합니다. 모르는 확장자는 txt 로 둡니다. */
export function kindFromName(name: string): FileKind {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  if (ext === 'doc' || ext === 'docx') return 'docx'
  if (ext === 'ppt' || ext === 'pptx') return 'pptx'
  if (ext === 'xls' || ext === 'xlsx') return 'xlsx'
  if (ext === 'pdf') return 'pdf'
  if (ext === 'hwp' || ext === 'hwpx') return 'hwp'
  return 'txt'
}
