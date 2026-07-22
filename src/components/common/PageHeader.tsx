import { ChevronRight } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { cn } from '@/lib/utils'

export interface Crumb {
  label: string
  /** 없으면 링크가 아닌 텍스트로 표시됩니다. */
  to?: string
}

export interface PageHeaderProps {
  title: ReactNode
  description?: ReactNode
  breadcrumbs?: Crumb[]
  actions?: ReactNode
  className?: string
}

/** 페이지 상단 제목 영역 — breadcrumb · 제목 · 설명 · 우측 액션. */
export function PageHeader({
  title,
  description,
  breadcrumbs,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <header className={cn('flex flex-col gap-4', className)}>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label="breadcrumb">
          <ol className="flex flex-wrap items-center gap-1 text-[13px] text-ink-subtle">
            {breadcrumbs.map((crumb, index) => {
              // 마지막 항목은 현재 위치이므로 링크로 만들지 않습니다.
              const isLast = index === breadcrumbs.length - 1
              return (
                <li key={`${crumb.label}-${index}`} className="flex items-center gap-1">
                  {crumb.to && !isLast ? (
                    <Link
                      to={crumb.to}
                      className="rounded px-1 py-0.5 font-medium transition-colors hover:bg-line-soft hover:text-ink"
                    >
                      {crumb.label}
                    </Link>
                  ) : (
                    <span className={cn('px-1 py-0.5', isLast && 'font-semibold text-ink-muted')}>
                      {crumb.label}
                    </span>
                  )}
                  {!isLast && <ChevronRight className="size-3.5 shrink-0" />}
                </li>
              )
            })}
          </ol>
        </nav>
      )}

      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-1.5">
          <h1 className="truncate text-[26px] leading-9 font-extrabold tracking-tight text-ink">
            {title}
          </h1>
          {description && <p className="text-sm leading-6 text-ink-muted">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  )
}
