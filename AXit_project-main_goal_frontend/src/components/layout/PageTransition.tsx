import { motion } from 'framer-motion'
import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

export interface PageTransitionProps {
  children: ReactNode
  className?: string
}

/** 라우트 전환 fade + lift. 짧게 유지해 이동이 느려 보이지 않게 합니다. */
export function PageTransition({ children, className }: PageTransitionProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
      className={cn('w-full', className)}
    >
      {children}
    </motion.div>
  )
}

/**
 * 카드 그리드·리스트용 stagger 변형.
 * 부모에 staggerContainer, 각 자식에 staggerItem 을 지정하면
 * 순차적으로 나타납니다.
 */
export const staggerContainer = {
  hidden: {},
  show: { transition: { staggerChildren: 0.05, delayChildren: 0.04 } },
}

export const staggerItem = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: [0.22, 1, 0.36, 1] as const } },
}
