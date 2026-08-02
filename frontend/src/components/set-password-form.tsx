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
 * `onError` exists because a wrong nonce is only detectable here: Supabase has
 * no standalone "check this nonce" call, so `updateUser` is where it surfaces
 * and the caller needs to know in order to send the user back to the code step.
 */
export function SetPasswordForm({
  submitLabel = "Update password",
  nonce,
  onSuccess,
  onError,
}: {
  submitLabel?: string
  nonce?: string
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
