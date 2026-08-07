"use client"

import { cn } from "@/lib/utils"

/**
 * An on/off switch.
 *
 * `role="switch"` with `aria-checked` rather than a styled checkbox: a switch
 * takes effect immediately, where a checkbox implies a later Save. Screen
 * readers announce the two differently, and this control does the former.
 *
 * Disabled while `busy` so the state cannot be flipped again mid-request - a
 * double-tap on a security toggle is exactly where a race would be worst.
 */
export function Switch({
  checked,
  onCheckedChange,
  disabled = false,
  busy = false,
  label,
  className,
}: {
  checked: boolean
  onCheckedChange: (next: boolean) => void
  disabled?: boolean
  busy?: boolean
  /** Accessible name. Required - the track carries no text of its own. */
  label: string
  className?: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      aria-busy={busy || undefined}
      disabled={disabled || busy}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-foreground" : "bg-input",
        className
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "pointer-events-none block size-5 rounded-full bg-background shadow-sm ring-0 transition-transform",
          checked ? "translate-x-5" : "translate-x-0"
        )}
      />
    </button>
  )
}
