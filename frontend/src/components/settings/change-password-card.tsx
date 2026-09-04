"use client"

import { CheckCircleIcon as CheckCircle, LockKeyIcon as LockKey} from "@phosphor-icons/react/dist/ssr"
import { useCallback, useEffect, useRef, useState } from "react"

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
 * Change password while signed in:
 *
 *     Email me a code  ->  enter code  ->  code correct  ->  password fields
 *
 * The code is verified on its own with `verifyOtp({ type: 'recovery' })`, which
 * is the only Supabase call that can check a code WITHOUT a password attached.
 * That is what lets the fields stay hidden until the code is right.
 *
 * THE CATCH, AND THE FIX
 *
 * `verifyOtp` establishes a NEW session, and a new session starts at aal1.
 * Supabase refuses to change the password of an account with a verified second
 * factor from an aal1 session - so on a 2FA account the fields appeared, the
 * user typed a password twice, and `updateUser` came back with a two-factor
 * error. The flow looked right and could never finish.
 *
 * So the session the user ALREADY had is captured before the code is sent and
 * restored just before the update. That session is theirs and is typically
 * aal2, so the update is allowed. Nothing is granted that they did not already
 * hold - it is put back, not escalated - and the emailed code still had to be
 * correct to get this far.
 */
export function ChangePasswordCard() {
  const supabase = createClient()
  const [stage, setStage] = useState<Stage>("idle")
  const [email, setEmail] = useState<string | null>(null)
  const [code, setCode] = useState("")
  const [invalid, setInvalid] = useState(false)
  const [verifying, setVerifying] = useState(false)
  const resend = useResendCooldown()

  // The pre-recovery session, held only for the length of this flow. A ref, not
  // state: it must never trigger a render, and it must not be readable from a
  // stale closure after the stage changes.
  const priorSession = useRef<{
    access_token: string
    refresh_token: string
  } | null>(null)

  useEffect(() => {
    let alive = true
    supabase.auth.getUser().then(({ data }) => {
      if (alive) setEmail(data.user?.email ?? null)
    })
    return () => {
      alive = false
      priorSession.current = null
    }
  }, [supabase])

  const sendCode = useCallback(async () => {
    if (!email) {
      toast.error("No email address on this account.")
      return
    }
    const ok = await resend.send(async () => {
      // Capture the current session BEFORE anything replaces it.
      const { data: current } = await supabase.auth.getSession()
      if (current.session) {
        priorSession.current = {
          access_token: current.session.access_token,
          refresh_token: current.session.refresh_token,
        }
      }
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
      setVerifying(false)
      if (error) {
        setInvalid(true)
        setCode("")
        toast.error(authErrorMessage(error, "That code isn't right."))
        return
      }
      setStage("verified")
    },
    [supabase, email, verifying]
  )

  /**
   * Put the pre-recovery session back, so the update runs at the assurance
   * level the user already had. Best effort: if it fails, the recovery session
   * is still in place and the update is simply attempted with that instead.
   */
  const restorePriorSession = useCallback(async () => {
    const saved = priorSession.current
    if (!saved) return
    try {
      await supabase.auth.setSession(saved)
    } catch {
      /* keep the recovery session and let updateUser report the truth */
    }
  }, [supabase])

  function reset() {
    priorSession.current = null
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
              onChange={(next) => {
                setCode(next)
                if (invalid) setInvalid(false)
              }}
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

        {/* Only reachable once the code was accepted. */}
        {stage === "verified" && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 rounded-xl border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-900 dark:border-emerald-900/50 dark:bg-emerald-950/30 dark:text-emerald-200">
              <CheckCircle weight="fill" className="size-4 shrink-0" />
              <p>Code confirmed. Choose your new password.</p>
            </div>
            <SetPasswordForm
              submitLabel="Update password"
              beforeSubmit={restorePriorSession}
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
