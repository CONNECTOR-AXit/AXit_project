import { ArrowLeft, FileQuestion } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Logo } from '@/components/common/Logo'
import { Button } from '@/components/ui/button'

/** 레이아웃 밖에서 단독으로 렌더링되는 404 화면. */
export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-canvas px-6 text-center">
      <Logo />
      <span className="flex size-16 items-center justify-center rounded-2xl bg-white text-ink-subtle shadow-card">
        <FileQuestion className="size-7" />
      </span>
      <div className="space-y-2">
        <h1 className="text-[32px] leading-10 font-extrabold tracking-tight text-ink">
          페이지를 찾을 수 없어요
        </h1>
        <p className="max-w-md text-[14px] leading-6 text-ink-muted">
          요청하신 주소가 변경되었거나 삭제되었을 수 있습니다. 대시보드로 돌아가 다시 시도해보세요.
        </p>
      </div>
      <Button asChild variant="gradient" size="lg">
        <Link to="/">
          <ArrowLeft />
          대시보드로 돌아가기
        </Link>
      </Button>
    </div>
  )
}
