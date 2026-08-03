"use client"

import {
  Check,
  Eye,
  EyeSlash,
  Lock,
} from "@phosphor-icons/react/dist/ssr"
import { useState } from "react"

import { Input } from "@/components/ui/input"
import { PASSWORD_RULES, passwordFailures } from "@/lib/password"
import { cn } from "@/lib/utils"

const LENGTH_TARGET =
  PASSWORD_RULES.find((r) => r.key === "length")?.target ?? 12

/** Secret input with a show/hide eye plus a right-aligned indicator slot. */
function BaseSecret({
  id,
  value,
  onChange,
  placeholder,
  disabled,
  invalid,
  right,
  rightPad,
  collapseRightWhenVisible,
  className,
  onFocus,
  onBlur,
}: {
  id: string
  value: string
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void
  placeholder?: string
  disabled?: boolean
  invalid?: boolean
  right?: React.ReactNode
  rightPad: string
  /**
   * Drop the indicator while the password is REVEALED, and give the text back
   * the full width.
   *
   * The indicator is an overlay, so `rightPad` permanently reserves its width
   * inside the field. With a wordy hint that reservation swallowed most of the
   * box, and clicking the eye to CHECK a password showed only the first half of
   * it - the one moment the text matters more than the hint. Revealing is a
   * deliberate "let me read this", so the hint yields.
   */
  collapseRightWhenVisible?: boolean
  className?: string
  onFocus?: () => void
  onBlur?: () => void
}) {
  const [visible, setVisible] = useState(false)
  const showRight = !(visible && collapseRightWhenVisible)
  return (
    <div className="relative">
      <Input
        id={id}
        type={visible ? "text" : "password"}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        disabled={disabled}
        aria-invalid={invalid}
        onFocus={onFocus}
        onBlur={onBlur}
        className={cn(
          "h-11 rounded-xl bg-muted/50 sm:h-12",
          // Only the eye needs clearance once the indicator is gone.
          showRight ? rightPad : "pr-12",
          className
        )}
      />
      <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center gap-1.5 pr-3">
        {showRight ? right : null}
        <button
          type="button"
          tabIndex={-1}
          disabled={disabled}
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? "Hide password" : "Show password"}
          className="pointer-events-auto flex text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
        >
          {visible ? <EyeSlash className="size-4" /> : <Eye className="size-4" />}
        </button>
      </div>
    </div>
  )
}

/**
 * Password input whose requirement feedback lives INSIDE the field as a single
 * live hint naming the ONE next thing to fix, taken from PASSWORD_RULES in
 * order. Once every rule passes the hint disappears entirely, and it turns red
 * after a failed submit while anything is unmet.
 *
 * The hint also yields the moment the password is revealed - see
 * collapseRightWhenVisible - because clicking the eye means "let me read what
 * I typed", and a hint that clips it defeats the button.
 */
export function PasswordField({
  id,
  value,
  onChange,
  attempted = false,
  placeholder = "Password",
  className,
}: {
  id: string
  value: string
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void
  attempted?: boolean
  placeholder?: string
  className?: string
}) {
  // Derived from PASSWORD_RULES, never re-implemented here.
  //
  // This used to hard-code its own length/uppercase/special checks, so when
  // lowercase and number were added to the shared rules it kept reporting
  // success without them: the hint vanished, the user believed they were
  // finished, and ConfirmPasswordField - which asks passwordFailures() -
  // stayed LOCKED behind a padlock with nothing on screen explaining why.
  // Two copies of one policy will always drift; there is now one copy.
  const failures = passwordFailures(value)
  const allOk = failures.length === 0

  let hint: string | null = null
  // Only guide once the user starts typing; the empty field stays clean. The
  // live n/12 count trails the next unmet rule, in PASSWORD_RULES order; when
  // everything passes, nothing is shown.
  if (value.length > 0 && !allOk) {
    // Cap the display at the target so a long password reads "12/12", never
    // "15/12".
    const counter = `${Math.min(value.length, LENGTH_TARGET)}/${LENGTH_TARGET}`
    // `short` ("Uppercase"), not `label` ("One uppercase letter") - the hint
    // is an overlay competing with the password for width, so every character
    // it saves is a character of password left readable. The length rule is
    // already expressed by the counter, so it never names itself.
    const next = failures.find((rule) => rule.key !== "length")
    hint = next ? `${next.short}, ${counter}` : counter
  }

  return (
    <BaseSecret
      id={id}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      invalid={attempted && Boolean(hint)}
      // Sized for the longest hint the short labels can produce
      // ("Special character, 12/12") plus the eye - was pr-52, which reserved
      // 208px of a field that is often only ~380px wide.
      rightPad="pr-44"
      collapseRightWhenVisible
      className={className}
      right={
        hint ? (
          <span
            className={cn(
              "pointer-events-none whitespace-nowrap text-[11px] font-medium transition-colors duration-200",
              attempted ? "text-destructive" : "text-muted-foreground"
            )}
          >
            {hint}
          </span>
        ) : null
      }
    />
  )
}

/**
 * Retype-password field. Locked until the password satisfies every rule (so
 * users can't confirm a password that will be rejected), and the match state
 * is shown INSIDE the field: a lock while disabled, "Don't match" in red on a
 * mismatch, an emerald check when it matches.
 */
export function ConfirmPasswordField({
  id,
  value,
  onChange,
  password,
  placeholder = "Retype password",
  className,
}: {
  id: string
  value: string
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void
  password: string
  placeholder?: string
  className?: string
}) {
  const passwordReady = passwordFailures(password).length === 0
  const match = value.length > 0 && value === password
  const mismatch = value.length > 0 && value !== password

  let indicator: React.ReactNode = null
  if (!passwordReady) {
    indicator = (
      <Lock className="size-4 text-muted-foreground" aria-label="Locked" />
    )
  } else if (match) {
    indicator = (
      <span className="flex size-5 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
        <Check weight="bold" className="size-3" />
      </span>
    )
  } else if (mismatch) {
    indicator = (
      <span className="text-[11px] font-medium text-destructive">
        Don&apos;t match
      </span>
    )
  }

  return (
    <BaseSecret
      id={id}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      disabled={!passwordReady}
      invalid={mismatch}
      rightPad="pr-24"
      className={className}
      right={<span className="pointer-events-none flex items-center">{indicator}</span>}
    />
  )
}
