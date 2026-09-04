"use client"

import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

/**
 * Renders a playground answer as formatted Markdown - headings, bold, lists,
 * tables and code - instead of raw `**` / `1.` text. Compact `prose` sizing
 * tuned for chat bubbles (GitHub-flavoured markdown via remark-gfm).
 *
 * The API and MCP responses keep returning Markdown in the `answer` field on
 * purpose: it is the portable, structured format every consumer (this UI, an
 * app, or an agent's own renderer) can display or strip. This component is how
 * THIS surface renders it.
 */
export function AnswerMarkdown({ children }: { children: string }) {
  return (
    <div className="prose prose-sm max-w-none break-words dark:prose-invert prose-headings:mb-1 prose-headings:mt-3 prose-h1:text-base prose-h2:text-base prose-h3:text-sm prose-p:my-2 prose-p:leading-6 prose-p:text-foreground/90 prose-a:font-medium prose-a:text-sky-600 dark:prose-a:text-sky-400 prose-strong:font-semibold prose-strong:text-foreground prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-li:leading-6 prose-table:text-xs prose-pre:my-2 prose-pre:bg-muted prose-pre:text-foreground prose-code:rounded prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:text-[0.85em] prose-code:before:content-none prose-code:after:content-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  )
}
