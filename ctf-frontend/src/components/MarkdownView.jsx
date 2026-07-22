import { useMemo } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({ gfm: true, breaks: true })

/**
 * Рендерит Markdown в безопасный HTML.
 * Используется и в редакторе (превью), и на странице просмотра занятия.
 */
export function renderMarkdown(md) {
  const raw = marked.parse(md || '')
  return DOMPurify.sanitize(raw)
}

export function MarkdownView({ source, className = '' }) {
  const html = useMemo(() => renderMarkdown(source), [source])
  return (
    <div
      className={`markdown-body ${className}`}
      // HTML выше прошёл санитизацию через DOMPurify
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
