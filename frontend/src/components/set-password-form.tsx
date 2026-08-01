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
 * flow and the Profile "Change password" card. Requires an active session
 * (recovery session or a signed-in user); calls supabase.auth.updateUser.
 *
 * `nonce` is the reauthentication code from `supabase.auth.reauthenticate()`.
 * Supplying it is what lets a SIGNED-IN user change their password: without it
 * a stolen live session is enough to take an account over permanently. The
 * reset flow omits it, because verifying the emailed recovery code already
 * proved control of the inbox moments earlier.
 */
export function SetPasswordForm({
  submitLabel = "Update password",
  nonce,
  onSuccess,
}: {
  submitLabel?: string
  nonce?: string
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
    const { error } = await createClient().auth.updateUser(
      nonce ? { password, nonce } : { password }
    )
    setLoading(false)
    if (error) {
      toast.error(authErrorMessage(error))
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
