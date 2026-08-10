import { cn } from '@/lib/utils'

export interface LogoProps {
  /** 워드마크 숨김. 사이드바가 접혔을 때 사용합니다. */
  compact?: boolean
  className?: string
}

/** AXit 브랜드 로고 — 좌측 문서 아이콘 + 우측 AXit 텍스트. */
export function Logo({ compact = false, className }: LogoProps) {
  return (
    <span className={cn('flex items-center gap-2.5 select-none', className)}>
      <span className="brand-gradient relative flex size-8 shrink-0 items-center justify-center rounded-[10px]">
        <svg viewBox="0 0 24 24" className="size-4.5" fill="none" aria-hidden="true">
          {/* 문서 본체 */}
          <path
            d="M13.5 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.5L13.5 3Z"
            fill="white"
            fillOpacity="0.95"
          />
          {/* 접힌 모서리 */}
          <path d="M13.5 3 19 8.5h-4a1.5 1.5 0 0 1-1.5-1.5V3Z" fill="white" fillOpacity="0.55" />
          {/* 본문 라인 */}
          <path
            d="M8.5 12.5h7M8.5 15.5h4.5"
            stroke="#0F73D8"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        </svg>
      </span>
      {!compact && (
        <span className="text-[19px] leading-none font-extrabold tracking-tight text-ink">
          AX<span className="text-primary">it</span>
        </span>
      )}
    </span>
  )
}
