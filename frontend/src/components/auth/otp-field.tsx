"use client"

import { useEffect, useRef } from "react"

import { cn } from "@/lib/utils"

const LENGTH = 6
const DIGITS = /^\d+$/

/**
 * Six-box verification code input.
 *
 * Behaviours that matter and are easy to get wrong:
 *
 * - **Paste anywhere.** Codes are copied out of a mail client, so a paste into
 *   box 4 must still fill the whole field, not drop five characters. The paste
 *   handler reads the clipboard itself rather than relying on per-box input.
 * - **One real input per box, not a masked single field.** `autoComplete`
 *   `one-time-code` on the first box is what makes iOS and Android offer the
 *   code from the Mail app; a single input with letter-spacing does not get it.
 * - **Backspace on an empty box moves back and clears.** Without this, fixing a
 *   typo means clicking the box you want, which nobody does.
 * - **Auto-submit on the last digit.** Typing six digits and then hunting for a
 *   button is the single most common complaint about code entry.
 *
 * Controlled: the parent owns `value` so it can clear the field after a failed
 * attempt without remounting (which would drop focus).
 */
export function OtpField({
  value,
  onChange,
  onComplete,
  disabled,
  invalid,
  autoFocus = true,
  label = "Verification code",
}: {
  value: string
  onChange: (next: string) => void
  onComplete?: (code: string) => void
  disabled?: boolean
  invalid?: boolean
  autoFocus?: boolean
  label?: string
}) {
  const inputs = useRef<Array<HTMLInputElement | null>>([])
  // Guards against firing onComplete twice for the same code - React can
  // re-render between the state update and the effect on a fast paste.
  const submitted = useRef<string | null>(null)

  useEffect(() => {
    if (autoFocus) inputs.current[0]?.focus()
  }, [autoFocus])

  useEffect(() => {
    if (value.length === LENGTH && submitted.current !== value) {
      submitted.current = value
      onComplete?.(value)
    }
    if (value.length < LENGTH) submitted.current = null
  }, [value, onComplete])

  function focusBox(index: number) {
    const clamped = Math.max(0, Math.min(LENGTH - 1, index))
    const el = inputs.current[clamped]
    el?.focus()
    el?.select()
  }

  function setDigit(index: number, digit: string) {
    const next = value.split("")
    // Pad so writing into box 4 of an empty field doesn't produce "4" at 0.
    while (next.length < index) next.push("")
    next[index] = digit
    onChange(next.join("").slice(0, LENGTH))
  }

  function handleChange(index: number, raw: string) {
    // Some Android keyboards deliver the whole autofilled code to one box.
    const digits = raw.replace(/\D/g, "")
    if (!digits) {
      setDigit(index, "")
      return
    }
    if (digits.length > 1) {
      const merged = (value.slice(0, index) + digits).slice(0, LENGTH)
      onChange(merged)
      focusBox(merged.length)
      return
    }
    setDigit(index, digits)
    if (index < LENGTH - 1) focusBox(index + 1)
  }

  function handleKeyDown(index: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace") {
      if (value[index]) {
        setDigit(index, "")
        return
      }
      // Empty box: step back and clear the one behind it in a single press.
      e.preventDefault()
      setDigit(index - 1, "")
      focusBox(index - 1)
      return
    }
    if (e.key === "ArrowLeft") {
      e.preventDefault()
      focusBox(index - 1)
    }
    if (e.key === "ArrowRight") {
      e.preventDefault()
      focusBox(index + 1)
    }
  }

  function handlePaste(e: React.ClipboardEvent<HTMLInputElement>) {
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "")
    if (!pasted) return
    e.preventDefault()
    const next = pasted.slice(0, LENGTH)
    onChange(next)
    focusBox(next.length)
  }

  return (
    <div
      role="group"
      aria-label={label}
      className="flex items-center justify-center gap-2 sm:gap-2.5"
    >
      {Array.from({ length: LENGTH }, (_, i) => (
        <input
          key={i}
          ref={(el) => {
            inputs.current[i] = el
          }}
          // type=text + inputMode=numeric, never type=number: number inputs
          // add spinners, accept "e"/"+"/"-", and silently reject leading zeros
          // in some browsers.
          type="text"
          inputMode="numeric"
          pattern="\d*"
          maxLength={LENGTH}
          // Only the first box advertises one-time-code; repeating it makes
          // iOS offer the same autofill six times.
          autoComplete={i === 0 ? "one-time-code" : "off"}
          aria-label={`${label}, digit ${i + 1} of ${LENGTH}`}
          aria-invalid={invalid || undefined}
          disabled={disabled}
          value={value[i] ?? ""}
          onChange={(e) => handleChange(i, e.target.value)}
          onKeyDown={(e) => handleKeyDown(i, e)}
          onPaste={handlePaste}
          onFocus={(e) => e.currentTarget.select()}
          className={cn(
            "size-11 rounded-xl border bg-muted/50 text-center font-mono text-lg tabular-nums transition-colors sm:size-12 sm:text-xl",
            "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
            "disabled:cursor-not-allowed disabled:opacity-60",
            invalid && "border-destructive text-destructive focus-visible:ring-destructive/40"
          )}
        />
      ))}
    </div>
  )
}

/** True when a string is a complete, well-formed code. */
export function isCompleteCode(value: string): boolean {
  return value.length === LENGTH && DIGITS.test(value)
}

export const OTP_LENGTH = LENGTH
