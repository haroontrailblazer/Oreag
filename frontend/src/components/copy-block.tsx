"use client"

import { Check, Copy } from "@phosphor-icons/react/dist/ssr"
import { useState } from "react"

import { Button } from "@/components/ui/button"

/**
 * Multi-line copyable code block - a <pre> with a one-click copy button in the
 * corner. The single-line sibling is CopyField; this preserves newlines for
 * snippets (curl, fetch, the `claude mcp add` command, etc.).
 */
export function CopyBlock({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    await navigator.clipboard.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="not-prose relative">
      <pre className="overflow-x-auto rounded-lg bg-muted p-3 pr-12 text-xs">
        {value}
      </pre>
      <Button
        type="button"
        variant="outline"
        size="icon-sm"
        onClick={copy}
        aria-label="Copy"
        className="absolute right-2 top-2 bg-background dark:bg-input dark:hover:bg-input/70"
      >
        {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
      </Button>
    </div>
  )
}
