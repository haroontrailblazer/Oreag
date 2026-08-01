"use client"

import { LockKey } from "@phosphor-icons/react/dist/ssr"
import { useCallback, useState } from "react"

import { OtpField, isCompleteCode } from "@/components/auth/otp-field"
import { SetPasswordForm } from "@/components/set-password-form"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Spin } from "@/components/ui/loader"
import { authErrorMessage } from "@/lib/auth-errors"
import { useResendCooldown } from "@/lib/auth-hooks"
import { createClient } from "@/lib/supabase/client"
import { toast } from "@/lib/toast"

/**
 * Change password, gated behind an emailed reauthentication code.
 *
 * Why the gate exists: before this, a live session could change the password
 * with no re-check at all, so a stolen session became permanent account
 * takeover - the attacker sets a new password and the real owner is locked out.
 * Requiring a code proves the person at the keyboard still controls the inbox.
 *
 * The code is NOT verified as its own step. Supabase has no "check this nonce"
 * call; the nonce is passed straight to `updateUser`, which validates it and
 * the new password together. So the UI collects the code, then reveals the
 * password fields, and a wrong code surfaces on submit.
 */
export function ChangePasswordCard() {
  const supabase = createClient()
  const [sent, setSent] = useState(false)
  const [code, setCode] = useState("")
  const resend = useResendCooldown()

  const sendCode = useCallback(async () => {
    const ok = await resend.send(async () => {
      // Emails a one-time nonce to the signed-in user's confirmed address.
      const { error } = await supabase.auth.reauthenticate()
      if (error) {
        toast.error(authErrorMessage(error, "Could not send the code."))
        return false
      }
      return true
    })
    if (ok) setSent(true)
  }, [supabase, resend])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Change password</CardTitle>
        <CardDescription>
          Min 12 characters, one uppercase, one special character. We&apos;ll
          email a code first to confirm it&apos;s you.
        </CardDescription>
      </CardHeader>

      <CardContent>
        {!sent ? (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              For your security, changing your password needs a code from your
              email - even while you&apos;re signed in.
            </p>
            <Button
              type="button"
              className="w-full"
              disabled={resend.blocked}
              onClick={sendCode}
            >
              {resend.sending ? (
                <Spin />
              ) : (
                <>
                  <LockKey className="size-4" />
                  Email me a code
                </>
              )}
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">
                Enter the code we just emailed you.
              </p>
              <OtpField value={code} onChange={setCode} autoFocus={false} />
            </div>

            {/* Password fields stay hidden until a full code is present, so
                nobody fills in a password only to be told to go find an email. */}
            {isCompleteCode(code) && (
              <SetPasswordForm
                submitLabel="Update password"
                nonce={code}
                onSuccess={() => {
                  toast.success("Password updated")
                  setSent(false)
                  setCode("")
                }}
              />
            )}

            <div className="flex items-center justify-between">
              <button
                type="button"
                onClick={() => {
                  setSent(false)
                  setCode("")
                }}
                className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={sendCode}
                disabled={resend.blocked}
                className="text-xs font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:cursor-not-allowed disabled:opacity-50 disabled:no-underline disabled:hover:text-muted-foreground"
              >
                {resend.label}
              </button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
