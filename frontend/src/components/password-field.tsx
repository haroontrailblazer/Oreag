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
  className?: string
  onFocus?: () => void
  onBlur?: () => void
}) {
  const [visible, setVisible] = useState(false)
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
        className={cn("h-12 rounded-xl bg-muted/50", rightPad, className)}
      />
      <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center gap-1.5 pr-3">
        {right}
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
 * live hint that names the ONE next thing to fix, in order: character count ->
 * special character -> uppercase. Once every rule passes the hint disappears
 * entirely. The hint turns red after a failed submit while anything is unmet.
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
  const lengthOk = value.length >= LENGTH_TARGET
  const specialOk = /[^A-Za-z0-9]/.test(value)
  const capsOk = /[A-Z]/.test(value)
  const allOk = lengthOk && specialOk && capsOk

  let hint: string | null = null
  // Only guide once the user starts typing; the empty field stays clean. The
  // live n/12 count always trails the next missing rule (uppercase, then
  // special character); when every rule is met, nothing is shown.
  if (value.length > 0 && !allOk) {
    // Cap the display at the target so a long password reads "12/12", never
    // "15/12".
    const counter = `${Math.min(value.length, LENGTH_TARGET)}/${LENGTH_TARGET}`
    let rule = ""
    if (!capsOk) rule = "Add an uppercase letter"
    else if (!specialOk) rule = "Add a special character"
    hint = rule ? `${rule}, ${counter}` : counter
  }

  return (
    <BaseSecret
      id={id}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      invalid={attempted && Boolean(hint)}
      rightPad="pr-52"
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
