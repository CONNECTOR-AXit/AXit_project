import { ArrowUpRight, FileCheck2 } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Badge } from '@/components/ui/badge'
import { formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { MergedDocumentSummary } from '@/types'

export interface MergedDocumentListProps {
  documents: MergedDocumentSummary[]
  /** 상대 시간 기준 시각. 더미 날짜가 고정이라 주입받습니다. */
  now?: Date
  className?: string
}

/** AI가 생성한 통합 문서 카드 목록. */
export function MergedDocumentList({ documents, now, className }: MergedDocumentListProps) {
  return (
    <ul className={cn('grid gap-3 sm:grid-cols-2 xl:grid-cols-3', className)}>
      {documents.map((doc) => (
        <li key={doc.id}>
          <Link
            to={`/projects/${doc.projectId}/editor`}
            className="group flex h-full flex-col gap-3 rounded-xl border border-line bg-white p-4 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lift"
          >
            <div className="flex items-start gap-3">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-line-soft text-ink-muted">
                <FileCheck2 className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13.5px] font-bold text-ink transition-colors group-hover:text-primary">
                  {doc.title}
                </p>
                <p className="mt-0.5 truncate text-[11.5px] text-ink-subtle">{doc.projectName}</p>
              </div>
              <ArrowUpRight className="size-4 shrink-0 text-ink-subtle opacity-0 transition-opacity group-hover:opacity-100" />
            </div>

            {/* mt-auto 로 카드 높이가 달라도 하단 정보가 바닥에 붙습니다. */}
            <div className="mt-auto flex items-center gap-2">
              <Badge variant="primary">{doc.version}</Badge>
              <span className="text-[11.5px] font-medium text-ink-muted">
                원본 {doc.sourceCount}개
              </span>
              <span className="ml-auto text-[11.5px] text-ink-subtle">
                {formatRelative(doc.updatedAt, now)}
              </span>
            </div>
          </Link>
        </li>
      ))}
    </ul>
  )
}
