import { useEffect, useLayoutEffect, useRef, type KeyboardEvent } from 'react'

export interface NotionTextEditorProps {
  id?: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  rows?: number
}

type LineKind = 'h1' | 'h2' | 'h3' | 'li' | 'oli' | 'p'

// 스페이스 자리에 일반 공백( )뿐 아니라 줄바꿈 없는 공백( )도
// 허용합니다 — 특정 상황(빈 편집기에 처음 입력하는 등)에서 크롬이 트레일링
// 스페이스를 그대로 두면 렌더링 시 사라지는 걸 막으려고 자동으로 &nbsp;로
// 바꿔버리는 경우가 있어, 리터럴 " "만 찾으면 그 순간 마커 인식이 조용히
// 실패할 수 있습니다.
const SPACE = '[ \u00A0]'
const MARKER_PATTERNS: Record<Exclude<LineKind, 'p' | 'oli'>, RegExp> = {
  h3: new RegExp(`^###${SPACE}`),
  h2: new RegExp(`^##${SPACE}`),
  h1: new RegExp(`^#${SPACE}`),
  li: new RegExp(`^[-*]${SPACE}`),
}
const OLI_PATTERN = /^\d+\.\s/

function kindOf(line: string): LineKind {
  if (MARKER_PATTERNS.h3.test(line)) return 'h3'
  if (MARKER_PATTERNS.h2.test(line)) return 'h2'
  if (MARKER_PATTERNS.h1.test(line)) return 'h1'
  if (MARKER_PATTERNS.li.test(line)) return 'li'
  if (OLI_PATTERN.test(line)) return 'oli'
  return 'p'
}

function markerLength(line: string, kind: LineKind): number {
  if (kind === 'h1') return 2
  if (kind === 'h2') return 3
  if (kind === 'h3') return 4
  if (kind === 'li') return 2
  if (kind === 'oli') return /^\d+\.\s/.exec(line)?.[0].length ?? 0
  return 0
}

const LINE_CLASS: Record<LineKind, string> = {
  h1: 'min-h-[30px] text-[21px] font-extrabold leading-[1.45] text-ink',
  h2: 'min-h-[26px] text-[18px] font-extrabold leading-[1.45] text-ink',
  h3: 'min-h-[23px] text-[15.5px] font-bold leading-[1.5] text-ink',
  li:
    "min-h-[23px] relative pl-5 text-[13px] leading-[1.75] text-ink before:absolute before:left-0.5 " +
    "before:font-bold before:text-primary before:content-['•']",
  oli:
    "min-h-[23px] relative pl-6 text-[13px] leading-[1.75] text-ink before:absolute before:left-0 " +
    "before:font-bold before:text-primary before:content-[attr(data-marker-label)]",
  p: 'min-h-[21px] text-[13px] leading-[1.65] text-ink',
}

/**
 * 줄 하나를 DOM으로 만듭니다. 마커(#, -, 1.)는 editable DOM 안에 아예 넣지
 * 않고 `data-marker` 속성에만 저장한 뒤 CSS `::before`(가상 요소)로만
 * 보여줍니다 — 값 재구성(`lineText`)에는 이 속성을 다시 앞에 붙입니다.
 *
 * 이전엔 마커를 `font-size:0` span으로 실제 DOM에 넣고 그 뒤에 별도
 * 텍스트 노드를 두는 방식이었는데, 실제 브라우저로 타이핑해보니 그 두
 * 노드의 경계에서 타이핑한 글자가 종종 (보여야 할 뒤쪽이 아니라) 숨겨진
 * 마커 노드 안으로 들어가버려 "글씨가 안 써지는" 문제가 있었습니다.
 * `::before`는 애초에 캐럿/선택 대상이 될 수 없는 순수 시각 요소라 이런
 * 경계 혼동이 구조적으로 불가능합니다 — 줄마다 진짜 텍스트 노드가 정확히
 * 하나(마커 이후 내용)뿐입니다.
 */
function buildLine(text: string): HTMLDivElement {
  const kind = kindOf(text)
  const markerLen = markerLength(text, kind)
  const marker = text.slice(0, markerLen)
  const rest = text.slice(markerLen)

  const div = document.createElement('div')
  div.className = LINE_CLASS[kind]
  div.dataset.lineKind = kind
  if (marker) {
    div.dataset.marker = marker
    if (kind === 'oli') div.dataset.markerLabel = marker.trim()
  }
  div.appendChild(document.createTextNode(rest))
  return div
}

/** 마커(있다면) + 실제 DOM 텍스트를 합쳐 이 줄의 완전한(마크다운) 텍스트를 돌려줍니다. */
function lineText(div: HTMLDivElement): string {
  return (div.dataset.marker ?? '') + (div.textContent ?? '')
}

function markerLenOf(div: HTMLDivElement): number {
  return div.dataset.marker?.length ?? 0
}

/** "줄 전체 텍스트" 기준 오프셋 -> 이 줄 DOM(마커 이후만 존재) 기준 오프셋. */
function toDomOffset(div: HTMLDivElement, fullOffset: number): number {
  return Math.max(0, fullOffset - markerLenOf(div))
}

/** 이 줄 DOM 기준 오프셋 -> "줄 전체 텍스트" 기준 오프셋. */
function toFullOffset(div: HTMLDivElement, domOffset: number): number {
  return domOffset + markerLenOf(div)
}

/** `root`(보통 한 줄 div) 안에서 커서가 있는 지점까지의 문자 오프셋. */
function caretOffsetWithin(root: Node): number {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0) return 0
  const range = selection.getRangeAt(0)
  if (!root.contains(range.startContainer)) return 0
  const measuring = range.cloneRange()
  measuring.selectNodeContents(root)
  measuring.setEnd(range.startContainer, range.startOffset)
  return measuring.toString().length
}

/** `root` 안의 문자 오프셋 위치로 커서를 되돌립니다. */
function setCaretWithin(root: Node, offset: number) {
  const selection = window.getSelection()
  if (!selection) return
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let remaining = offset
  let node = walker.nextNode()
  let last: Text | null = null
  while (node) {
    const text = node as Text
    const len = text.data.length
    if (remaining <= len) {
      const range = document.createRange()
      range.setStart(text, Math.max(0, remaining))
      range.collapse(true)
      selection.removeAllRanges()
      selection.addRange(range)
      return
    }
    remaining -= len
    last = text
    node = walker.nextNode()
  }
  const range = document.createRange()
  if (last) range.setStart(last, last.data.length)
  else range.selectNodeContents(root)
  range.collapse(false)
  selection.removeAllRanges()
  selection.addRange(range)
}

function lineDivAt(root: HTMLElement, node: Node | null): HTMLDivElement | null {
  let current = node
  while (current && current.parentNode !== root) current = current.parentNode
  return current && current !== root ? (current as HTMLDivElement) : null
}

/** `div` 안에서 (node, offset) 지점까지의 DOM 기준(마커 제외) 문자 오프셋. */
function offsetWithinDiv(div: HTMLDivElement, node: Node, offset: number): number {
  const range = document.createRange()
  range.selectNodeContents(div)
  range.setEnd(node, offset)
  return range.toString().length
}

/**
 * 선택 범위의 한쪽 끝(anchor/focus)이 줄 div가 아니라 `root` 자체를 가리킬 때
 * (예: 전체 선택 시 브라우저가 컨테이너+자식 인덱스로 경계를 표현하는 경우)를
 * 포함해, "몇 번째 줄의 어느 지점"인지 + "줄 전체 텍스트 기준 오프셋"으로
 * 정규화합니다.
 *
 * `root` 경계(예: Ctrl+A 전체 선택)로 표현된 지점은 "그 줄의 진짜 시작/끝"을
 * 뜻하므로 마커까지 포함한 fullOffset을 그대로 0(시작) 또는 줄 전체 길이(끝)로
 * 계산합니다. 반면 줄 div 안의 실제 텍스트 노드 지점은 항상 마커 "다음"
 * 위치이므로 `toFullOffset`으로 마커 길이를 더해 변환합니다 — 이 둘을 섞어서
 * 같은 방식으로 계산하면, Ctrl+A 후 삭제해도 각 줄의 숨겨진 마커(#, -, 1. 등)가
 * 지워지지 않고 남아 값이 진짜로 빈 문자열이 되지 않는 문제가 생깁니다.
 */
function resolveBoundary(
  root: HTMLElement,
  node: Node,
  offset: number,
): { lineIndex: number; fullOffset: number } | null {
  const lineDivs = Array.from(root.children) as HTMLDivElement[]
  if (node === root) {
    if (lineDivs.length === 0) return null
    if (offset >= lineDivs.length) {
      const lastDiv = lineDivs[lineDivs.length - 1]
      return {
        lineIndex: lineDivs.length - 1,
        fullOffset: toFullOffset(lastDiv, (lastDiv.textContent ?? '').length),
      }
    }
    return { lineIndex: offset, fullOffset: 0 }
  }
  const div = lineDivAt(root, node)
  if (!div) return null
  const lineIndex = lineDivs.indexOf(div)
  if (lineIndex < 0) return null
  return { lineIndex, fullOffset: toFullOffset(div, offsetWithinDiv(div, node, offset)) }
}

/**
 * `::before` 마커는 애초에 진짜 DOM이 아니라서 어떤 선택(Ctrl+A 포함)으로도
 * 절대 선택 범위 안에 들어올 수 없습니다 — 그래서 "전체 선택"의 시작점은
 * 항상 마커 "다음"(예: fullOffset 2)이 되고, `resolveBoundary` 기준으로는
 * 부분 선택과 구분이 안 돼 마커가 안 지워지는 문제가 생깁니다. 이 함수로
 * "선택 범위가 편집기의 실제 텍스트 노드 전부를 덮는다(=진짜 전체 선택)"를
 * 직접 판별해서, 이 경우에만 마커까지 포함해 통째로 비웁니다.
 */
function isEntireContentSelected(root: HTMLElement, range: Range): boolean {
  // 크롬이 편집 도중 실제 줄 텍스트 노드들 뒤에 빈("") 텍스트 노드를 캐럿
  // 앵커용으로 슬쩍 끼워 넣는 경우가 있어, 그런 빈 노드는 "실제 마지막 내용"
  // 판단에서 제외합니다 — 안 그러면 전체 선택(Ctrl+A)의 끝 지점이 그 빈
  // 노드가 아니라 진짜 마지막 글자에서 끝나는데도 서로 달라 보여 매칭에
  // 실패합니다.
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let first: Text | null = null
  let last: Text | null = null
  let node: Node | null
  while ((node = walker.nextNode())) {
    const text = node as Text
    if (text.data.length === 0) continue
    if (!first) first = text
    last = text
  }
  if (!first || !last) return true
  return (
    range.startContainer === first &&
    range.startOffset === 0 &&
    range.endContainer === last &&
    range.endOffset === last.data.length
  )
}

/**
 * 노션처럼 `#`, `##`, `-`, `1.`로 시작하는 줄을 입력하는 즉시 실제로 큰
 * 제목/목록 크기로 보여주고, 마커 글자 자체는 화면에서 숨깁니다(값에는
 * 그대로 남아있는 평문 마크다운). 진짜 `contentEditable`을 써서 커서·한글
 * IME 조합은 브라우저가 그대로 처리하게 합니다.
 *
 * 성능/안정성 핵심 규칙 두 가지:
 * 1. 매 입력마다 줄 DOM을 통째로 다시 그리지 않습니다 — 그 줄의 종류(kind)가
 *    실제로 바뀔 때만(예: "- "를 막 완성한 순간) DOM을 손댑니다. 평소 타이핑은
 *    브라우저 네이티브 편집을 절대 방해하지 않습니다.
 * 2. 그 DOM 변경조차 같은 이벤트 틱 안에서 하지 않고 다음 애니메이션 프레임으로
 *    미룹니다 — 방금 브라우저가 처리 중이던 바로 그 키 입력과 겹쳐서 "한 글자
 *    더 입력해야 적용되는" 현상이 생기지 않도록 하기 위해서입니다.
 */
export function NotionTextEditor({ id, value, onChange, placeholder, rows = 8 }: NotionTextEditorProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const isComposingRef = useRef(false)
  const lastValueRef = useRef<string | null>(null)
  const pendingFrameRef = useRef<number | null>(null)

  useLayoutEffect(() => {
    const root = rootRef.current
    if (!root || value === lastValueRef.current) return
    lastValueRef.current = value
    root.replaceChildren(...value.split('\n').map(buildLine))
  }, [value])

  useEffect(
    () => () => {
      if (pendingFrameRef.current !== null) cancelAnimationFrame(pendingFrameRef.current)
    },
    [],
  )

  const commit = (nextValue: string) => {
    lastValueRef.current = nextValue
    onChange(nextValue)
  }

  const cancelScheduledSync = () => {
    if (pendingFrameRef.current !== null) {
      cancelAnimationFrame(pendingFrameRef.current)
      pendingFrameRef.current = null
    }
  }

  const syncFromDom = () => {
    const root = rootRef.current
    if (!root) return

    // 줄 div가 하나도 없는 경우를 한 줄짜리 입력으로 보정합니다 — 완전히
    // 빈 상태에서 첫 글자를 칠 때(브라우저가 div 없이 텍스트 노드만 넣는
    // 경우) 뿐 아니라, 전체 선택 후 삭제해서 내용이 통째로 사라졌을 때도
    // 여기로 올 수 있습니다. 후자일 때 value를 갱신하지 않고 그냥
    // 돌아가버리면 부모가 "다 지워졌다"는 걸 못 받아서 플레이스홀더가
    // 다시 뜨지 않는 문제가 있었습니다 — 이제 빈 텍스트여도 항상 commit합니다.
    if (root.children.length === 0) {
      const text = root.textContent ?? ''
      const fullOffset = caretOffsetWithin(root)
      commit(text)
      const rebuilt = buildLine(text)
      root.replaceChildren(rebuilt)
      setCaretWithin(rebuilt, toDomOffset(rebuilt, fullOffset))
      return
    }

    const lineDivs = Array.from(root.children) as HTMLDivElement[]

    const selection = window.getSelection()
    const caretLine =
      selection && selection.rangeCount > 0
        ? lineDivAt(root, selection.getRangeAt(0).startContainer)
        : null
    const caretLineIndex = caretLine ? lineDivs.indexOf(caretLine) : -1

    const nextValue = lineDivs.map(lineText).join('\n')
    commit(nextValue)

    // 커서가 있는 줄의 kind가 실제로 바뀌었을 때만 그 줄의 DOM을 다시
    // 그립니다 — 평소 타이핑에서는 여기까지 오지 않습니다.
    if (caretLineIndex < 0) return
    const activeDiv = lineDivs[caretLineIndex]
    const currentText = lineText(activeDiv)
    const newKind = kindOf(currentText)
    if (activeDiv.dataset.lineKind === newKind) return

    const fullOffset = toFullOffset(activeDiv, caretOffsetWithin(activeDiv))
    const rebuiltLine = buildLine(currentText)
    root.replaceChild(rebuiltLine, activeDiv)
    setCaretWithin(rebuiltLine, toDomOffset(rebuiltLine, fullOffset))
  }

  const scheduleSync = () => {
    if (pendingFrameRef.current !== null) return
    pendingFrameRef.current = requestAnimationFrame(() => {
      pendingFrameRef.current = null
      syncFromDom()
    })
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (isComposingRef.current) return
    const root = rootRef.current
    if (!root) return
    const selection = window.getSelection()
    if (!selection || selection.rangeCount === 0) return
    const range = selection.getRangeAt(0)
    const currentValue = lastValueRef.current ?? value

    if (event.key === 'Enter') {
      event.preventDefault()
      cancelScheduledSync()
      const lineDivs = Array.from(root.children) as HTMLDivElement[]
      const lineDiv = lineDivAt(root, range.startContainer)
      const lineIndex = lineDiv ? lineDivs.indexOf(lineDiv) : lineDivs.length - 1
      if (lineIndex < 0) return
      const fullOffset = toFullOffset(lineDivs[lineIndex], caretOffsetWithin(lineDivs[lineIndex]))
      const text = lineText(lineDivs[lineIndex])

      const lines = currentValue.split('\n')
      lines.splice(lineIndex, 1, text.slice(0, fullOffset), text.slice(fullOffset))
      const nextValue = lines.join('\n')
      commit(nextValue)

      const rebuilt = nextValue.split('\n').map(buildLine)
      root.replaceChildren(...rebuilt)
      setCaretWithin(rebuilt[lineIndex + 1], toDomOffset(rebuilt[lineIndex + 1], 0))
      return
    }

    // 마커는 실제 DOM(선택/삭제 대상)이 아니라 data-marker 속성에만 있어서,
    // 브라우저가 직접 처리하는 범위 선택 삭제(예: 전체 선택 후 Backspace/Delete)는
    // 실제 텍스트 노드만 지우고 이제는 의미 없는 data-marker 속성을 가진 줄
    // div를 그대로 남겨버립니다 — 값이 ""가 되지 않아 플레이스홀더가 다시 뜨지
    // 않는 원인이었습니다. 선택 범위가 있는 Backspace/Delete는 직접 계산해서
    // 처리하고, 항상 buildLine으로 다시 만들어 낡은 마커가 남지 않게 합니다.
    if ((event.key === 'Backspace' || event.key === 'Delete') && !range.collapsed) {
      event.preventDefault()
      cancelScheduledSync()

      if (isEntireContentSelected(root, range)) {
        commit('')
        const rebuilt = buildLine('')
        root.replaceChildren(rebuilt)
        setCaretWithin(rebuilt, 0)
        return
      }

      const start = resolveBoundary(root, range.startContainer, range.startOffset)
      const end = resolveBoundary(root, range.endContainer, range.endOffset)
      if (!start || !end) return

      const lines = currentValue.split('\n')
      const startFull = start.fullOffset
      const endFull = end.fullOffset
      const startLineText = lines[start.lineIndex] ?? ''
      const endLineText = lines[end.lineIndex] ?? ''
      const mergedLine = startLineText.slice(0, startFull) + endLineText.slice(endFull)
      lines.splice(start.lineIndex, end.lineIndex - start.lineIndex + 1, mergedLine)
      const nextValue = lines.join('\n')
      commit(nextValue)

      const rebuilt = nextValue.split('\n').map(buildLine)
      root.replaceChildren(...rebuilt)
      const mergedDiv = rebuilt[start.lineIndex]
      setCaretWithin(mergedDiv, toDomOffset(mergedDiv, startFull))
      return
    }

    if (event.key === 'Backspace' && range.collapsed) {
      const lineDivs = Array.from(root.children) as HTMLDivElement[]
      const lineDiv = lineDivAt(root, range.startContainer)
      const lineIndex = lineDiv ? lineDivs.indexOf(lineDiv) : -1
      if (lineIndex < 0) return
      if (caretOffsetWithin(lineDivs[lineIndex]) !== 0) return

      // 마커는 DOM에 없는 가상 요소라서, 마커 직후의 캐럿은 DOM 기준으로
      // 줄의 시작(offset 0)입니다. 이 상태에서 브라우저 기본 Backspace를
      // 허용하면 이전 줄로 이동한 뒤 앞 글자를 지워버립니다. 활성 마커를
      // 먼저 일반 문장으로 되돌리고, 같은 줄의 시작에 캐럿을 둡니다.
      const activeMarkerLength = markerLenOf(lineDivs[lineIndex])
      if (activeMarkerLength > 0) {
        event.preventDefault()
        cancelScheduledSync()
        const lines = lineDivs.map(lineText)
        const currentText = lineText(lineDivs[lineIndex])
        lines[lineIndex] = currentText.slice(activeMarkerLength)
        const nextValue = lines.join('\n')
        commit(nextValue)

        const rebuilt = nextValue.split('\n').map(buildLine)
        root.replaceChildren(...rebuilt)
        setCaretWithin(rebuilt[lineIndex], 0)
        return
      }

      if (lineIndex <= 0) return

      event.preventDefault()
      cancelScheduledSync()
      const lines = currentValue.split('\n')
      const previousText = lines[lineIndex - 1] ?? ''
      const currentText = lines[lineIndex] ?? ''
      lines.splice(lineIndex - 1, 2, previousText + currentText)
      const nextValue = lines.join('\n')
      commit(nextValue)

      const rebuilt = nextValue.split('\n').map(buildLine)
      root.replaceChildren(...rebuilt)
      const mergedDiv = rebuilt[lineIndex - 1]
      setCaretWithin(mergedDiv, toDomOffset(mergedDiv, previousText.length))
    }
  }

  return (
    <div className="relative">
      {value.length === 0 && placeholder && (
        <span className="pointer-events-none absolute top-2 left-3 select-none text-[13px] text-ink-subtle">
          {placeholder}
        </span>
      )}
      <div
        ref={rootRef}
        id={id}
        role="textbox"
        aria-multiline="true"
        contentEditable
        suppressContentEditableWarning
        onInput={() => {
          if (!isComposingRef.current) scheduleSync()
        }}
        onCompositionStart={() => {
          cancelScheduledSync()
          isComposingRef.current = true
        }}
        onCompositionEnd={() => {
          isComposingRef.current = false
          scheduleSync()
        }}
        onKeyDown={handleKeyDown}
        className="min-h-[1.5em] overflow-y-auto rounded-lg border border-line-soft bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-primary"
        style={{ height: rows * 26 + 16 }}
      />
    </div>
  )
}
