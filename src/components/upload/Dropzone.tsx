import { motion } from 'framer-motion'
import { UploadCloud } from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export interface DropzoneProps {
  onFiles: (files: FileList | File[]) => void
  hint?: string
  accept?: string
  maxSizeLabel?: string
  disabled?: boolean
  className?: string
}

/** 드래그 앤 드롭 + 파일 선택 업로드 영역. */
export function Dropzone({
  onFiles,
  hint = 'PDF, DOCX, HWP, TXT, PPTX',
  accept = '.pdf,.docx,.doc,.hwp,.hwpx,.txt,.pptx,.ppt,.xlsx,.xls',
  maxSizeLabel = '최대 50MB',
  disabled = false,
  className,
}: DropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  // 자식 위로 드래그가 지나가면 dragenter/dragleave 가 계속 발생하므로
  // 깊이를 세어 실제로 영역을 벗어났을 때만 상태를 해제합니다.
  const depth = useRef(0)

  const onDragEnter = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    if (disabled) return
    depth.current += 1
    setDragging(true)
  }

  const onDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    depth.current -= 1
    if (depth.current <= 0) {
      depth.current = 0
      setDragging(false)
    }
  }

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    depth.current = 0
    setDragging(false)
    if (disabled) return
    if (event.dataTransfer.files?.length) onFiles(event.dataTransfer.files)
  }

  return (
    <div
      onDragEnter={onDragEnter}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      className={cn(
        'relative flex flex-col items-center justify-center gap-1 rounded-2xl border-2 border-dashed px-6 py-14 text-center transition-all duration-200',
        dragging
          ? 'border-primary bg-primary-50/70 shadow-brand'
          : 'border-line bg-line-soft/40 hover:border-primary-200 hover:bg-primary-50/30',
        disabled && 'pointer-events-none opacity-60',
        className,
      )}
    >
      <motion.span
        animate={dragging ? { y: -6, scale: 1.06 } : { y: 0, scale: 1 }}
        transition={{ type: 'spring', stiffness: 320, damping: 20 }}
        className={cn(
          'mb-3 flex size-14 items-center justify-center rounded-2xl transition-colors',
          dragging ? 'brand-gradient text-white' : 'bg-white text-primary shadow-card',
        )}
      >
        <UploadCloud className="size-6" strokeWidth={2} />
      </motion.span>

      <p className="text-[14px] font-bold text-ink">
        {dragging ? '여기에 놓으면 업로드됩니다' : '파일을 드래그 앤 드롭하거나'}
      </p>
      {!dragging && <p className="text-[13px] text-ink-muted">클릭하여 업로드하세요</p>}

      <p className="mt-2 text-[12px] text-ink-subtle">
        지원 형식: {hint} ({maxSizeLabel})
      </p>

      <Button
        type="button"
        variant="primary"
        size="sm"
        className="mt-4"
        onClick={() => inputRef.current?.click()}
      >
        파일 선택
      </Button>

      <input
        ref={inputRef}
        type="file"
        multiple
        accept={accept}
        className="sr-only"
        aria-label="업로드할 파일 선택"
        onChange={(event) => {
          if (event.target.files?.length) onFiles(event.target.files)
          // 같은 파일을 다시 선택해도 change 가 발생하도록 초기화합니다.
          event.target.value = ''
        }}
      />
    </div>
  )
}
