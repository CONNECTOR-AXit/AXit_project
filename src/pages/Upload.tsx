import { PhasePlaceholder } from '@/components/common/PhasePlaceholder'

export default function Upload() {
  return (
    <PhasePlaceholder
      title="문서 업로드"
      description="프로젝트에 통합할 문서를 업로드하세요."
      phase="Phase 4"
      planned={[
        'Drag & Drop 업로드 영역',
        '지원 형식 안내 — PDF · DOCX · TXT · HWP · PPTX',
        '파일별 업로드 Progress 및 상태 표시',
        '파일 삭제 · 전체 삭제',
      ]}
    />
  )
}
