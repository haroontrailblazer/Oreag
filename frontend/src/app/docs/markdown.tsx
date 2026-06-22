"use client"

import { Image as ImageIcon } from "@phosphor-icons/react/dist/ssr"
import type { ReactNode } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

import { CopyBlock } from "@/components/copy-block"

import { CodeTabs, parseOscmd } from "./code-tabs"

/** Flatten heading children to plain text (for slugified anchor ids). */
function nodeText(node: ReactNode): string {
  if (node == null || node === false || node === true) return ""
  if (typeof node === "string" || typeof node === "number") return String(node)
  if (Array.isArray(node)) return node.map(nodeText).join("")
  if (typeof node === "object" && "props" in node) {
    return nodeText((node as { props: { children?: ReactNode } }).props.children)
  }
  return ""
}

const slug = (s: string) =>
  s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "")

/**
 * Renders one docs section's markdown. Headings get stable ids (`<sectionId>` for
 * the H2 title, `<sectionId>-<slug>` for sub-headings) so the sidebar TOC and
 * scroll-spy can target them. Code fences become copyable blocks, and the special
 * ```oscmd fence becomes Linux/macOS/Windows tabs. Screenshot placeholders render
 * as labeled slots.
 */
export function Markdown({
  sectionId,
  children,
}: {
  sectionId: string
  children: string
}) {
  return (
    <div className="prose prose-lg max-w-[68ch] dark:prose-invert prose-headings:scroll-mt-24 prose-h2:mt-0 prose-h2:border-b prose-h2:pb-3 prose-h2:text-3xl prose-h2:font-bold prose-h2:tracking-tight prose-h3:mt-10 prose-h3:text-xl prose-h3:font-semibold prose-h3:tracking-tight prose-p:leading-[1.8] prose-p:text-foreground/90 prose-li:leading-[1.8] prose-li:my-1 prose-li:text-foreground/90 prose-strong:text-foreground prose-strong:font-semibold prose-a:font-medium prose-a:text-sky-600 dark:prose-a:text-sky-400 prose-a:underline-offset-2 prose-table:text-base prose-code:before:content-none prose-code:after:content-none">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h2: ({ children }) => <h2 id={sectionId}>{children}</h2>,
          h3: ({ children }) => (
            <h3 id={`${sectionId}-${slug(nodeText(children))}`}>{children}</h3>
          ),
          h4: ({ children }) => (
            <h4 id={`${sectionId}-${slug(nodeText(children))}`}>{children}</h4>
          ),
          pre: ({ children }) => <>{children}</>,
          code: ({ className, children }) => {
            const text = String(children ?? "")
            const lang = /language-(\w+)/.exec(className || "")?.[1]
            const isBlock = Boolean(lang) || text.includes("\n")
            if (!isBlock) {
              return (
                <code className="rounded bg-muted px-1 py-0.5 text-[0.85em] font-normal">
                  {children}
                </code>
              )
            }
            const value = text.replace(/\n$/, "")
            if (lang === "oscmd") return <CodeTabs tabs={parseOscmd(value)} />
            return <CopyBlock value={value} />
          },
          img: ({ src, alt }) => {
            const label = alt ?? ""
            if (src === "placeholder" || label.startsWith("SCREENSHOT:")) {
              const caption = label.replace(/^SCREENSHOT:\s*/, "")
              return (
                <span className="not-prose my-3 flex flex-col items-center gap-2 rounded-lg border border-dashed bg-muted/40 px-4 py-6 text-center text-xs text-muted-foreground">
                  <ImageIcon className="size-6" />
                  <span>
                    <strong className="text-foreground">Screenshot:</strong>{" "}
                    {caption}
                  </span>
                </span>
              )
            }
            // eslint-disable-next-line @next/next/no-img-element
            return <img src={src} alt={label} className="rounded-lg border" />
          },
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
