"use client"

import { useId } from "react"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

export function FilterSelect({ label, value, onChange, options, hideLabel = false, ariaLabel }: {
  label: string
  value: string
  onChange: (value: string) => void
  options: readonly { value: string; label: string }[]
  hideLabel?: boolean
  ariaLabel?: string
}) {
  const id = useId()
  // Radix reserves an empty value for its placeholder. Prefix every option
  // so existing empty-string filters remain controlled and resettable.
  const prefix = "filter:"
  return <div className="flex min-w-0 flex-col gap-1.5">
    <label htmlFor={id} className={hideLabel ? "sr-only" : "text-xs text-muted-foreground"}>{label}</label>
    <Select value={prefix + value} onValueChange={next => onChange(next.slice(prefix.length))}>
      <SelectTrigger id={id} aria-label={ariaLabel} title={options.find(option => option.value === value)?.label} className="w-full min-w-0 text-left [&_[data-slot=select-value]]:block [&_[data-slot=select-value]]:truncate">
        <SelectValue />
      </SelectTrigger>
      <SelectContent position="popper" align="start" className="w-[var(--radix-select-trigger-width)] min-w-48 max-w-[calc(100vw-2rem)]">
        {options.map(option => <SelectItem key={option.value} value={prefix + option.value} title={option.label} className="[&>span:last-child]:min-w-0 [&>span:last-child]:line-clamp-3 [&>span:last-child]:whitespace-normal [&>span:last-child]:[overflow-wrap:anywhere]">
          {option.label}
        </SelectItem>)}
      </SelectContent>
    </Select>
  </div>
}
