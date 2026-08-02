"use client"

import { useState } from "react"
import { toast } from "@/lib/toast"

import { ConfirmPasswordField, PasswordField } from "@/components/password-field"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Spin } from "@/components/ui/loader"
import { authErrorMessage } from "@/lib/auth-errors"
import { passwordFailures } from "@/lib/password"
import { createClient } from "@/lib/supabase/client"

/**
 * New-password + confirm form with strength rules. Used by the password-reset
 * flow and the Profile "Change password" card.
 *
 * Two callers, two ways of proving the person is who they say:
 *
 * - The reset flow verifies an emailed recovery code first, which establishes a
 *   recovery session. No `nonce` needed - control of the inbox was proven
 *   moments earlier.
 * - The signed-in profile card passes a `nonce` from
 *   `supabase.auth.reauthenticate()`. That deliberately does NOT create a new
 *   session, so an existing aal2 session survives the password change intact.
 *
 * `beforeSubmit` runs immediately before `updateUser`. The profile card uses it
 * to restore the session the user had before the recovery code replaced it -
 * Supabase refuses a password change on the fresh aal1 session that
 * `verifyOtp` creates when the account has a second factor, so without this the
 * update fails at the last step with a two-factor error.
 */
export function SetPasswordForm({
  submitLabel = "Update password",
  nonce,
  beforeSubmit,
  onSuccess,
  onError,
}: {
  submitLabel?: string
  nonce?: string
  beforeSubmit?: () => Promise<void> | void
  onSuccess?: () => void
  onError?: (error: unknown) => void
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
    await beforeSubmit?.()
    const { error } = await createClient().auth.updateUser(
      nonce ? { password, nonce } : { password }
    )
    setLoading(false)
    if (error) {
      toast.error(authErrorMessage(error))
      onError?.(error)
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
        <PasswordField
          id="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          attempted={attempted}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="confirm-password">Confirm password</Label>
        <ConfirmPasswordField
          id="confirm-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          password={password}
        />
      </div>
      <Button type="submit" className="w-full" disabled={loading}>
        {loading ? <Spin /> : submitLabel}
      </Button>
    </form>
  )
}
