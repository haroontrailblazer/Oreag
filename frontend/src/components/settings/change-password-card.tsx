"use client"

import { CheckCircle, LockKey } from "@phosphor-icons/react/dist/ssr"
import { useCallback, useEffect, useState } from "react"

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

type Stage = "idle" | "code" | "verified"

/**
 * Change password, gated behind an emailed code that is **verified before the
 * password fields appear**.
 *
 * Why the gate exists: before it, a live session could change the password
 * with no re-check at all, so a stolen session became permanent account
 * takeover - the attacker sets a new password and the real owner is locked out.
 *
 * Why this uses the RECOVERY code rather than `auth.reauthenticate()`:
 * reauthentication issues a nonce that Supabase will only validate as part of
 * `updateUser({ password, nonce })`. There is no "is this nonce correct?" call,
 * so a reauth-based flow can only reveal a wrong code *after* the user has
 * chosen and typed a new password twice - which is exactly the dead end this
 * component is meant to avoid. `verifyOtp({ type: 'recovery' })` validates on
 * its own and establishes a recovery session, so the form below can be shown
 * only once the code is genuinely correct, and `updateUser` then needs no nonce.
 */
export function ChangePasswordCard() {
  const supabase = createClient()
  const [stage, setStage] = useState<Stage>("idle")
  const [email, setEmail] = useState<string | null>(null)
  const [code, setCode] = useState("")
  const [invalid, setInvalid] = useState(false)
  const [verifying, setVerifying] = useState(false)
  const resend = useResendCooldown()

  useEffect(() => {
    let alive = true
    supabase.auth.getUser().then(({ data }) => {
      if (alive) setEmail(data.user?.email ?? null)
    })
    return () => {
      alive = false
    }
  }, [supabase])

  const sendCode = useCallback(async () => {
    if (!email) {
      toast.error("No email address on this account.")
      return
    }
    const ok = await resend.send(async () => {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: `${location.origin}/auth/confirm?next=/auth/reset-password`,
      })
      if (error) {
        toast.error(authErrorMessage(error, "Could not send the code."))
        return false
      }
      return true
    })
    if (ok) {
      setCode("")
      setInvalid(false)
      setStage("code")
    }
  }, [supabase, email, resend])

  const verify = useCallback(
    async (value: string) => {
      if (!email || verifying) return
      setVerifying(true)
      setInvalid(false)
      const { error } = await supabase.auth.verifyOtp({
        email,
        token: value,
        type: "recovery",
      })
      if (error) {
        setVerifying(false)
        setInvalid(true)
        setCode("")
        toast.error(authErrorMessage(error, "That code isn't right."))
        return
      }
      // Confirm a session actually exists rather than trusting the absence of
      // an error - the password form is useless without one.
      const { data } = await supabase.auth.getSession()
      setVerifying(false)
      if (!data.session) {
        setInvalid(true)
        setCode("")
        toast.error("Could not confirm it's you. Request a new code.")
        return
      }
      setStage("verified")
    },
    [supabase, email, verifying]
  )

  function reset() {
    setStage("idle")
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
        {stage === "idle" && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              For your security, changing your password needs a code from your
              email - even while you&apos;re signed in.
            </p>
            <Button
              type="button"
              className="w-full"
              disabled={resend.blocked || !email}
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
        )}

        {stage === "code" && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Enter the code we sent to{" "}
              <span className="font-medium text-foreground">{email}</span>.
            </p>
            <OtpField
              value={code}
              onChange={setCode}
              onComplete={verify}
              disabled={verifying}
              invalid={invalid}
              autoFocus={false}
            />
            <Button
              type="button"
              className="w-full"
              disabled={!isCompleteCode(code) || verifying}
              onClick={() => verify(code)}
            >
              {verifying ? <Spin /> : "Verify code"}
            </Button>
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

        {/* Only reachable once the code was accepted, so nobody fills in a
            password and is then told to go find an email. */}
        {stage === "verified" && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 rounded-xl border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-900 dark:border-emerald-900/50 dark:bg-emerald-950/30 dark:text-emerald-200">
              <CheckCircle weight="fill" className="size-4 shrink-0" />
              <p>Code confirmed. Choose your new password.</p>
            </div>
            <SetPasswordForm
              submitLabel="Update password"
              onSuccess={() => {
                toast.success("Password updated")
                reset()
              }}
            />
          </div>
        )}
      </CardContent>
    </Card>
  )
}
