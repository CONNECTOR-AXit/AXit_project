import { Loader2, Save } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'

export interface CreateVersionDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  defaultLabel: string
  isSubmitting?: boolean
  errorMessage?: string | null
  onConfirm: (label: string) => void
}

/** "현재 버전으로 저장"을 누르면 뜨는 제목 입력 다이얼로그. */
export function CreateVersionDialog({
  open,
  onOpenChange,
  defaultLabel,
  isSubmitting,
  errorMessage,
  onConfirm,
}: CreateVersionDialogProps) {
  const [label, setLabel] = useState(defaultLabel)

  useEffect(() => {
    if (open) setLabel(defaultLabel)
  }, [open, defaultLabel])

  const trimmed = label.trim()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>현재 버전으로 저장</DialogTitle>
          <DialogDescription>
            지금 문서 상태를 나중에 다시 찾아볼 수 있는 이름 붙은 버전으로 남깁니다.
          </DialogDescription>
        </DialogHeader>

        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (!trimmed || isSubmitting) return
            onConfirm(trimmed)
          }}
        >
          <label htmlFor="version-label" className="text-[12.5px] font-semibold text-ink">
            버전 제목
          </label>
          <Input
            id="version-label"
            className="mt-1.5"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            maxLength={200}
            autoFocus
            placeholder="예: 1차 검토 완료본"
          />
          {errorMessage && <p className="mt-2 text-[12px] text-danger">{errorMessage}</p>}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              취소
            </Button>
            <Button type="submit" variant="gradient" disabled={!trimmed || isSubmitting}>
              {isSubmitting ? <Loader2 className="animate-spin" /> : <Save />}
              저장
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
