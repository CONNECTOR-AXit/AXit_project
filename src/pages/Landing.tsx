import { motion } from 'framer-motion'
import { FileStack, FileUp, Sparkles, type LucideIcon } from 'lucide-react'
import { Link } from 'react-router-dom'

import { staggerContainer, staggerItem } from '@/components/layout/PageTransition'
import { Logo } from '@/components/common/Logo'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'

interface Feature {
  icon: LucideIcon
  title: string
  description: string
}

const features: Feature[] = [
  {
    icon: FileUp,
    title: '문서 업로드',
    description: 'PDF, DOCX, HWP, PPTX, XLSX 등 다양한 형식의 문서를 한 번에 모아 올릴 수 있어요.',
  },
  {
    icon: Sparkles,
    title: 'AI 분석',
    description: '업로드한 문서들의 공통 내용과 차이점, 핵심 내용을 AI가 자동으로 정리합니다.',
  },
  {
    icon: FileStack,
    title: '통합 문서',
    description: '분석 결과를 바탕으로 하나의 통합 문서를 만들고, 팀과 함께 이어서 편집하세요.',
  },
]

/** 로그인 전 사용자에게 보여주는 소개 페이지. 레이아웃 밖에서 단독으로 렌더링됩니다. */
export default function Landing() {
  return (
    <div className="min-h-screen bg-canvas">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <Logo />
        <div className="flex items-center gap-2">
          <Button asChild variant="ghost">
            <Link to="/login">로그인</Link>
          </Button>
          <Button asChild variant="gradient">
            <Link to="/signup">무료로 시작하기</Link>
          </Button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 pt-16 pb-24 text-center">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
        >
          <h1 className="mx-auto max-w-2xl text-[36px] leading-tight font-extrabold tracking-tight text-ink sm:text-[44px]">
            여러 문서를, <span className="text-primary">하나의 통합 문서</span>로
          </h1>
          <p className="mx-auto mt-4 max-w-xl text-[15px] leading-7 text-ink-muted">
            문서를 업로드하면 AI가 공통 내용·차이점·핵심 내용을 정리하고, 하나의 통합 문서로
            만들어드립니다.
          </p>
          <div className="mt-8 flex items-center justify-center gap-3">
            <Button asChild variant="gradient" size="lg">
              <Link to="/signup">무료로 시작하기</Link>
            </Button>
            <Button asChild variant="outline" size="lg">
              <Link to="/login">로그인</Link>
            </Button>
          </div>
        </motion.div>

        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="mt-20 grid gap-4 text-left sm:grid-cols-3"
        >
          {features.map((feature) => (
            <motion.div key={feature.title} variants={staggerItem}>
              <Card className="h-full p-5">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-line-soft text-ink-muted">
                  <feature.icon className="size-[18px]" />
                </span>
                <h3 className="mt-3.5 text-[14.5px] font-bold text-ink">{feature.title}</h3>
                <p className="mt-1.5 text-[13px] leading-5 text-ink-muted">
                  {feature.description}
                </p>
              </Card>
            </motion.div>
          ))}
        </motion.div>
      </main>

      <footer className="border-t border-line-soft py-6 text-center text-[12px] text-ink-subtle">
        © {new Date().getFullYear()} AXit. All rights reserved.
      </footer>
    </div>
  )
}
