import type { DocBlock, MergedDocument } from '@/types'

/** Convert the current merged-document surface into a portable Markdown file. */
export function mergedDocumentToMarkdown(document: MergedDocument): string {
  const lines: string[] = [`# ${document.title}`, '']

  for (const block of document.blocks) {
    appendBlock(lines, block)
    lines.push('')
  }

  return `${lines.join('\n').trimEnd()}\n`
}

/** Download the current merged document without adding a server export surface. */
export function downloadMergedDocument(document: MergedDocument): void {
  const blob = new Blob([mergedDocumentToMarkdown(document)], {
    type: 'text/markdown;charset=utf-8',
  })
  const objectUrl = URL.createObjectURL(blob)
  const link = window.document.createElement('a')
  link.href = objectUrl
  link.download = `${safeFilename(document.title)}.md`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
}

function appendBlock(lines: string[], block: DocBlock): void {
  switch (block.type) {
    case 'heading':
      lines.push(`${'#'.repeat(block.level)} ${block.text}`)
      return
    case 'paragraph':
      lines.push(block.text)
      return
    case 'list':
      lines.push(...block.items.map((item) => `- ${item}`))
      return
    case 'table':
      lines.push(`| ${block.columns.map(escapeCell).join(' | ')} |`)
      lines.push(`| ${block.columns.map(() => '---').join(' | ')} |`)
      lines.push(...block.rows.map((row) => `| ${row.map(escapeCell).join(' | ')} |`))
      return
    case 'callout':
      lines.push(`> ${block.text}`)
      return
  }
}

function escapeCell(value: string): string {
  return value.replaceAll('|', '\\|').replaceAll('\n', ' ')
}

function safeFilename(value: string): string {
  const withoutControls = Array.from(value, (character) =>
    (character.codePointAt(0) ?? 0) < 32 ? '_' : character,
  ).join('')
  const normalized = withoutControls.trim().replace(/[<>:"/\\|?*]/g, '_')
  return normalized || '통합문서'
}
