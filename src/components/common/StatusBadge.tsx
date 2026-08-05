import { Badge, type BadgeProps } from '@/components/ui/badge'
import type { DocumentStatus, ProjectStatus } from '@/types'

/** 프로젝트 상태 → 라벨 + 배지 색. */
export const projectStatusMap: Record<
  ProjectStatus,
  { label: string; variant: BadgeProps['variant'] }
> = {
  draft: { label: '준비 중', variant: 'neutral' },
  uploading: { label: '업로드 중', variant: 'warning' },
  analyzing: { label: 'AI 분석 중', variant: 'warning' },
  review: { label: '검토 중', variant: 'warning' },
  completed: { label: '완료', variant: 'success' },
}

/** 문서 상태 → 라벨 + 배지 색. */
export const documentStatusMap: Record<
  DocumentStatus,
  { label: string; variant: BadgeProps['variant'] }
> = {
  queued: { label: '대기 중', variant: 'neutral' },
  uploading: { label: '업로드 중', variant: 'warning' },
  uploaded: { label: '업로드 완료', variant: 'success' },
  analyzed: { label: '분석 완료', variant: 'success' },
  failed: { label: '실패', variant: 'danger' },
}

export function ProjectStatusBadge({ status }: { status: ProjectStatus }) {
  const { label, variant } = projectStatusMap[status]
  return <Badge variant={variant}>{label}</Badge>
}

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  const { label, variant } = documentStatusMap[status]
  return <Badge variant={variant}>{label}</Badge>
}
