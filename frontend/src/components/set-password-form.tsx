"use client"

import { useState } from "react"
import { toast } from "@/lib/toast"

import { ConfirmPasswordField, PasswordField } from "@/components/password-field"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { LoaderOne } from "@/components/ui/loader"
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
        {loading ? <LoaderOne /> : submitLabel}
      </Button>
    </form>
  )
}
