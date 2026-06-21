"use client"

import { Check, Copy } from "@phosphor-icons/react/dist/ssr"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

export function CopyField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    await navigator.clipboard.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="relative">
      <Input readOnly value={value} className="pr-12 font-mono text-xs" />
      <Button
        type="button"
        variant="outline"
        size="icon-sm"
        onClick={copy}
        aria-label="Copy"
        className="absolute top-1/2 right-2 -translate-y-1/2"
      >
        {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
      </Button>
    </div>
  )
}
