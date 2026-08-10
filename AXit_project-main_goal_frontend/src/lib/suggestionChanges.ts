import type { AiSuggestion, DocBlock } from '@/types'

const RAG_TAG_PATTERN = /\[RAG:([0-9a-f]{8}-[0-9a-f-]{27})\]/gi

function blockText(block: DocBlock) {
  return 'text' in block ? block.text : ''
}

export function visibleSuggestionText(text: string) {
  return text.replace(RAG_TAG_PATTERN, '').replace(/\s+$/g, '')
}

export function findSuggestionTargetIndex(blocks: DocBlock[], suggestion: AiSuggestion) {
  if (suggestion.targetBlockId) {
    const pinnedIndex = blocks.findIndex((block) => block.id === suggestion.targetBlockId)
    if (pinnedIndex >= 0) return pinnedIndex
  }
  const suggestedText = visibleSuggestionText(suggestion.detail).trim()
  const exactTextIndex = blocks.findIndex((block) => {
    const text = visibleSuggestionText(blockText(block)).trim()
    return Boolean(suggestedText) && (text === suggestedText || text.includes(suggestedText))
  })
  if (exactTextIndex >= 0) return exactTextIndex

  if (suggestion.sourceAnchorId) {
    const tag = `[rag:${suggestion.sourceAnchorId.toLowerCase()}]`
    const anchoredIndex = blocks.findIndex((block) => blockText(block).toLowerCase().includes(tag))
    if (anchoredIndex >= 0) return anchoredIndex
  }

  return suggestion.kind === 'add' ? Math.max(0, blocks.length - 1) : -1
}

function suggestedBlockText(suggestion: AiSuggestion) {
  const text = visibleSuggestionText(suggestion.detail).trim()
  if (!suggestion.sourceAnchorId) return text
  return `${text} [RAG:${suggestion.sourceAnchorId}]`
}

/** Apply the exact inline diff shown in the editor to the editable merged-document blocks. */
export function applySuggestionToBlocks(blocks: DocBlock[], suggestion: AiSuggestion): DocBlock[] {
  const targetIndex = findSuggestionTargetIndex(blocks, suggestion)
  const target = targetIndex >= 0 ? blocks[targetIndex] : undefined

  if (suggestion.kind === 'add') {
    const visibleText = visibleSuggestionText(suggestion.detail).trim()
    if (
      !visibleText ||
      blocks.some((block) => visibleSuggestionText(blockText(block)).trim() === visibleText)
    ) {
      return blocks
    }
    const addition: DocBlock = {
      id: `ai-${suggestion.id}`,
      type: 'paragraph',
      text: suggestedBlockText(suggestion),
      tag: 'AI 추천 반영',
    }
    const insertAt = targetIndex >= 0 ? targetIndex + 1 : blocks.length
    return [...blocks.slice(0, insertAt), addition, ...blocks.slice(insertAt)]
  }

  if (!target || !('text' in target)) return blocks
  if (suggestion.kind === 'remove') {
    return blocks.filter((_, index) => index !== targetIndex)
  }

  if (target.type !== 'heading' && target.type !== 'paragraph') return blocks
  return blocks.map((block, index) =>
    index === targetIndex ? { ...block, text: suggestedBlockText(suggestion) } : block,
  )
}

export function suggestionTargetBlockId(blocks: DocBlock[], suggestion: AiSuggestion) {
  const index = findSuggestionTargetIndex(blocks, suggestion)
  return index >= 0 ? blocks[index]?.id : undefined
}
