"use client"

import { Check, Copy } from "@phosphor-icons/react/dist/ssr"
import { useState } from "react"

import { Button } from "@/components/ui/button"

export type OsTab = { os: string; code: string }

const OS_LABELS: Record<string, string> = {
  linux: "Linux",
  macos: "macOS",
  windows: "Windows",
}

/**
 * Parse an ```oscmd code block whose body is split by `@@@linux` / `@@@macos` /
 * `@@@windows` markers (each on its own line) into per-OS tabs.
 */
export function parseOscmd(raw: string): OsTab[] {
  const tokens = raw.split(/^@@@(\w+)[^\n]*$/m)
  const tabs: OsTab[] = []
  for (let i = 1; i < tokens.length; i += 2) {
    const os = tokens[i].toLowerCase()
    const code = (tokens[i + 1] ?? "").replace(/^\n+|\n+$/g, "")
    if (code) tabs.push({ os, code })
  }
  return tabs.length ? tabs : [{ os: "shell", code: raw.trim() }]
}

export function CodeTabs({ tabs }: { tabs: OsTab[] }) {
  const [active, setActive] = useState(0)
  const [copied, setCopied] = useState(false)
  const current = tabs[active] ?? tabs[0]

  async function copy() {
    await navigator.clipboard.writeText(current.code)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="not-prose my-4 overflow-hidden rounded-lg border bg-muted">
      <div className="flex items-center justify-between border-b bg-background/40 pl-1 pr-1.5">
        <div className="flex">
          {tabs.map((t, i) => (
            <button
              key={t.os}
              type="button"
              onClick={() => setActive(i)}
              className={
                "-mb-px border-b-2 px-3 py-2 text-xs font-medium transition-colors " +
                (i === active
                  ? "border-foreground text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground")
              }
            >
              {OS_LABELS[t.os] ?? t.os}
            </button>
          ))}
        </div>
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          onClick={copy}
          aria-label="Copy"
          className="my-1 bg-background dark:bg-input dark:hover:bg-input/70"
        >
          {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
        </Button>
      </div>
      <pre className="overflow-x-auto p-3 text-xs leading-relaxed">
        <code>{current.code}</code>
      </pre>
    </div>
  )
}
