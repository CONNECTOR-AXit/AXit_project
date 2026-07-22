import { Download, Eye, MoreHorizontal, Trash2 } from 'lucide-react'

import { FileTypeIcon } from '@/components/common/FileTypeIcon'
import { DocumentStatusBadge } from '@/components/common/StatusBadge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { formatBytes, formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DocumentFile } from '@/types'

export interface DocumentTableProps {
  documents: DocumentFile[]
  /** 업로더 열을 숨깁니다. 좁은 컨테이너에서 사용합니다. */
  compact?: boolean
  className?: string
}

/**
 * 업로드된 문서 목록.
 * 표는 최소 폭을 유지하고 컨테이너가 좁아지면 가로로만 스크롤됩니다.
 * 페이지 자체가 가로로 밀리지 않습니다.
 */
export function DocumentTable({ documents, compact = false, className }: DocumentTableProps) {
  const columns = ['문서명', '크기', ...(compact ? [] : ['업로드']), '상태', '업로드 일시', '']

  return (
    <div className={cn('overflow-x-auto', className)}>
      <table className="w-full min-w-[640px] border-collapse text-left">
        <thead>
          <tr className="border-b border-line">
            {columns.map((label, index) => (
              <th
                key={`${label}-${index}`}
                scope="col"
                className="px-3 py-2.5 text-[11px] font-bold tracking-wide text-ink-subtle"
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {documents.map((doc) => (
            <tr
              key={doc.id}
              className="group border-b border-line-soft transition-colors last:border-0 hover:bg-line-soft/60"
            >
              <td className="px-3 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  <FileTypeIcon kind={doc.kind} size="sm" />
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-semibold text-ink">{doc.name}</p>
                    {doc.pages !== undefined && (
                      <p className="text-[11px] text-ink-subtle">{doc.pages}페이지</p>
                    )}
                  </div>
                </div>
              </td>

              <td className="px-3 py-3 text-[12px] font-medium text-ink-muted tabular-nums">
                {formatBytes(doc.size)}
              </td>

              {!compact && (
                <td className="px-3 py-3 text-[12px] font-medium text-ink-muted">
                  {doc.uploadedBy}
                </td>
              )}

              <td className="px-3 py-3">
                <DocumentStatusBadge status={doc.status} />
              </td>

              <td className="px-3 py-3 text-[12px] text-ink-subtle tabular-nums">
                {formatDateTime(doc.uploadedAt)}
              </td>

              <td className="px-3 py-3 text-right">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
                      aria-label={`${doc.name} 메뉴`}
                    >
                      <MoreHorizontal />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent>
                    <DropdownMenuItem>
                      <Eye />
                      미리보기
                    </DropdownMenuItem>
                    <DropdownMenuItem>
                      <Download />
                      다운로드
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem variant="danger">
                      <Trash2 />
                      삭제
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
