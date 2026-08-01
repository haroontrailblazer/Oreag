"use client"

import { useEffect, useRef } from "react"

import { cn } from "@/lib/utils"

const DIGITS = /^\d+$/

/**
 * How many digits Supabase actually sends.
 *
 * This is a PROJECT setting (Authentication -> Emails -> OTP length), not a
 * constant - it is adjustable from 6 to 10 and applies to every email OTP:
 * signup confirmation, recovery, magic link and the reauthentication nonce.
 * Hardcoding 6 makes an 8-digit code physically impossible to type, so the
 * value lives in the environment and must match the dashboard.
 *
 * Clamped rather than trusted: a typo in the env var would otherwise render
 * zero boxes, or two hundred.
 */
const CONFIGURED = Number(process.env.NEXT_PUBLIC_OTP_LENGTH)
export const OTP_LENGTH =
  Number.isFinite(CONFIGURED) && CONFIGURED >= 6 && CONFIGURED <= 10
    ? Math.trunc(CONFIGURED)
    : 6

/**
 * Authenticator-app codes are ALWAYS six digits.
 *
 * TOTP is six by specification (RFC 6238 / RFC 4226 default) and every
 * mainstream authenticator - Google Authenticator, 1Password, Authy - emits
 * six. It is a separate mechanism from the emailed OTP above and is completely
 * unaffected by the project's email OTP length setting.
 *
 * So this is a constant, not configuration. Letting OTP_LENGTH drive a TOTP
 * field would render eight boxes for a six-digit code the moment someone
 * changed an unrelated email setting.
 */
export const TOTP_LENGTH = 6

/**
 * Verification code input, one box per digit.
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
 * - **Auto-submit on the last digit.** Typing the code and then hunting for a
 *   button is the single most common complaint about code entry.
 * - **Boxes shrink past six digits.** Ten boxes at the six-digit size overflow
 *   a phone; the field stays on one line instead of wrapping mid-code.
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
  length = OTP_LENGTH,
}: {
  value: string
  onChange: (next: string) => void
  onComplete?: (code: string) => void
  disabled?: boolean
  invalid?: boolean
  autoFocus?: boolean
  label?: string
  /** Digits to render. Defaults to the project's configured OTP length. */
  length?: number
}) {
  const LENGTH = length
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
  }, [value, onComplete, LENGTH])

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
      className={cn(
        "flex items-center justify-center",
        LENGTH > 6 ? "gap-1 sm:gap-1.5" : "gap-2 sm:gap-2.5"
      )}
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
          // iOS offer the same autofill once per box.
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
            "rounded-xl border bg-muted/50 text-center font-mono tabular-nums transition-colors",
            LENGTH > 6
              ? "size-9 text-base sm:size-11 sm:text-lg"
              : "size-11 text-lg sm:size-12 sm:text-xl",
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
export function isCompleteCode(value: string, length = OTP_LENGTH): boolean {
  return value.length === length && DIGITS.test(value)
}
