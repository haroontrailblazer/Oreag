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
 * Change password while signed in, gated behind an emailed code.
 *
 * Why the gate exists: before it, a live session could change the password
 * with no re-check at all, so a stolen session became permanent account
 * takeover - the attacker sets a new password and the real owner is locked out.
 *
 * Why `reauthenticate()` and NOT the recovery code:
 *
 * `verifyOtp({ type: 'recovery' })` establishes a NEW session, and a new
 * session starts at aal1. For an account with two-factor enabled that silently
 * downgrades an aal2 session, so the moment the password was changed the next
 * API call returned 403 and threw the user onto the step-up screen - being
 * asked for an authenticator code purely as a side effect of changing a
 * password. `reauthenticate()` issues a nonce against the CURRENT session and
 * creates nothing, so an aal2 session survives untouched and no second factor
 * is ever demanded here.
 *
 * It also sends Supabase's Reauthentication template, which is code-only with
 * no link - so this flow cannot be short-circuited by clicking through an
 * email, unlike the recovery one.
 *
 * The trade-off, stated plainly: Supabase exposes no way to validate a nonce on
 * its own (`EmailOtpType` has no 'reauthentication'), so a wrong code can only
 * be reported by `updateUser`. The password fields therefore stay hidden until
 * a full-length code is present, and a rejected code returns here with the
 * field cleared - nobody is left staring at a form that cannot succeed.
 */
export function ChangePasswordCard() {
  const supabase = createClient()
  const [sent, setSent] = useState(false)
  const [code, setCode] = useState("")
  const [invalid, setInvalid] = useState(false)
  const resend = useResendCooldown()

  const sendCode = useCallback(async () => {
    const ok = await resend.send(async () => {
      // Emails a one-time nonce to the signed-in user's confirmed address.
      // Does not touch the session.
      const { error } = await supabase.auth.reauthenticate()
      if (error) {
        toast.error(authErrorMessage(error, "Could not send the code."))
        return false
      }
      return true
    })
    if (ok) {
      setCode("")
      setInvalid(false)
      setSent(true)
    }
  }, [supabase, resend])

  function reset() {
    setSent(false)
    setCode("")
    setInvalid(false)
  }

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
              <OtpField
                value={code}
                onChange={(next) => {
                  setCode(next)
                  if (invalid) setInvalid(false)
                }}
                invalid={invalid}
                autoFocus={false}
              />
            </div>

            {/* Held back until the code is complete, so nobody picks a new
                password only to be told to go and find an email. */}
            {isCompleteCode(code) && (
              <SetPasswordForm
                submitLabel="Update password"
                nonce={code}
                onSuccess={() => {
                  toast.success("Password updated")
                  reset()
                }}
                onError={() => {
                  // Almost always a wrong or expired nonce. Clear the code and
                  // send them back to the field rather than leaving a password
                  // form on screen that will keep failing.
                  setInvalid(true)
                  setCode("")
                }}
              />
            )}

            <div className="flex items-center justify-between">
              <button
                type="button"
                onClick={reset}
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
