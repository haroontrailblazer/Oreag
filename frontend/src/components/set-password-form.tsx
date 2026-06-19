"use client"

import { X } from "@phosphor-icons/react/dist/ssr"
import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { PasswordInput } from "@/components/ui/password-input"
import { passwordFailures } from "@/lib/password"
import { createClient } from "@/lib/supabase/client"

/**
 * New-password + confirm form with strength rules. Used by the password-reset
 * page and the Profile "Change password" card. Requires an active session
 * (recovery session or a signed-in user); calls supabase.auth.updateUser.
 */
export function SetPasswordForm({
  submitLabel = "Update password",
  onSuccess,
}: {
  submitLabel?: string
  onSuccess?: () => void
}) {
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [attempted, setAttempted] = useState(false)
  const [loading, setLoading] = useState(false)

  const failing = passwordFailures(password)
  const mismatch = password !== confirm

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (failing.length > 0 || mismatch) {
      setAttempted(true)
      return
    }
    setLoading(true)
    const { error } = await createClient().auth.updateUser({ password })
    setLoading(false)
    if (error) {
      toast.error(error.message)
      return
    }
    setPassword("")
    setConfirm("")
    setAttempted(false)
    onSuccess?.()
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="new-password">New password</Label>
        <PasswordInput
          id="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="bg-muted/50"
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="confirm-password">Confirm password</Label>
        <PasswordInput
          id="confirm-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          className="bg-muted/50"
        />
      </div>
      {attempted && (failing.length > 0 || mismatch) && (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-2.5">
          <p className="text-xs font-medium text-destructive">
            Your password needs:
          </p>
          <ul className="mt-1.5 space-y-1">
            {failing.map((r) => (
              <li
                key={r.label}
                className="flex items-center gap-1.5 text-xs text-destructive"
              >
                <X className="size-3.5 shrink-0" />
                {r.label}
              </li>
            ))}
            {mismatch && (
              <li className="flex items-center gap-1.5 text-xs text-destructive">
                <X className="size-3.5 shrink-0" />
                Passwords must match
              </li>
            )}
          </ul>
        </div>
      )}
      <Button type="submit" className="w-full" disabled={loading}>
        {loading ? "Updating…" : submitLabel}
      </Button>
    </form>
  )
}
