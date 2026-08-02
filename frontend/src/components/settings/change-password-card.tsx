"use client"

import { ArrowRight, LockKey } from "@phosphor-icons/react/dist/ssr"
import { useCallback, useState } from "react"

import { OtpField, isCompleteCode } from "@/components/auth/otp-field"
import { ConfirmPasswordField, PasswordField } from "@/components/password-field"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Spin } from "@/components/ui/loader"
import { authErrorMessage } from "@/lib/auth-errors"
import { useResendCooldown } from "@/lib/auth-hooks"
import { passwordFailures } from "@/lib/password"
import { createClient } from "@/lib/supabase/client"
import { toast } from "@/lib/toast"

/**
 * Change password while signed in: choose the password, then confirm with an
 * emailed code.
 *
 * WHY THIS ORDER, AND NOT "code first, fields after"
 *
 * The obvious design - verify the code, then reveal the password fields - needs
 * a code that can be checked on its own. Only `verifyOtp({ type: 'recovery' })`
 * can do that, and it establishes a NEW session, which starts at aal1. Supabase
 * then refuses to change the password of an account that has a verified second
 * factor from an aal1 session, so the fields appeared and the update could
 * never succeed: the user typed a password twice and got a two-factor error.
 * That flow was structurally broken for exactly the accounts it mattered for.
 *
 * `reauthenticate()` avoids it by issuing a nonce against the CURRENT session
 * and creating nothing - an aal2 session survives, so the update goes through
 * and no second factor is ever demanded here. The cost is that its nonce has no
 * standalone verify endpoint (`EmailOtpType` has no 'reauthentication'); it is
 * validated by `updateUser` itself.
 *
 * So the code moves to the END. It is the last thing entered and the thing that
 * submits, which means a wrong code fails on the code field - where the mistake
 * actually is - and the password survives the retry. Nobody types a password
 * twice only to be told the wrong thing was wrong.
 *
 * It also uses Supabase's Reauthentication template, which is code-only with no
 * link, so this flow cannot be short-circuited by clicking through an email.
 */
export function ChangePasswordCard() {
  const supabase = createClient()

  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [attempted, setAttempted] = useState(false)

  const [stage, setStage] = useState<"password" | "code">("password")
  const [code, setCode] = useState("")
  const [invalid, setInvalid] = useState(false)
  const [saving, setSaving] = useState(false)
  const resend = useResendCooldown()

  const failing = passwordFailures(password)
  const mismatch = password !== confirm
  const passwordReady = failing.length === 0 && !mismatch && password.length > 0

  const sendCode = useCallback(async () => {
    const ok = await resend.send(async () => {
      // Emails a one-time nonce to the signed-in user's confirmed address.
      // Does not touch the session, which is the whole point.
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
      setStage("code")
    }
  }, [supabase, resend])

  function startOver() {
    setStage("password")
    setPassword("")
    setConfirm("")
    setCode("")
    setInvalid(false)
    setAttempted(false)
  }

  const submit = useCallback(
    async (value: string) => {
      if (saving) return
      setSaving(true)
      setInvalid(false)
      // The nonce is checked here, by the server, together with the password.
      const { error } = await supabase.auth.updateUser({
        password,
        nonce: value,
      })
      setSaving(false)
      if (error) {
        // Nearly always a wrong or expired code. Keep the password - only the
        // code is cleared, so the retry is one field, not three.
        setInvalid(true)
        setCode("")
        toast.error(authErrorMessage(error, "That code isn't right."))
        return
      }
      toast.success("Password updated")
      startOver()
    },
    [supabase, password, saving]
  )

  return (
    <Card>
      <CardHeader>
        <CardTitle>Change password</CardTitle>
        <CardDescription>
          Min 12 characters, one uppercase, one special character. We&apos;ll
          email a code to confirm it&apos;s you.
        </CardDescription>
      </CardHeader>

      <CardContent>
        {stage === "password" ? (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              if (!passwordReady) {
                setAttempted(true)
                return
              }
              void sendCode()
            }}
          >
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
            <Button type="submit" className="w-full" disabled={resend.blocked}>
              {resend.sending ? (
                <Spin />
              ) : (
                <>
                  <LockKey className="size-4" />
                  Continue
                  <ArrowRight className="size-4" weight="bold" />
                </>
              )}
            </Button>
          </form>
        ) : (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              We emailed you a code. Enter it to confirm the change.
            </p>
            <OtpField
              value={code}
              onChange={(next) => {
                setCode(next)
                if (invalid) setInvalid(false)
              }}
              onComplete={submit}
              disabled={saving}
              invalid={invalid}
            />
            <Button
              type="button"
              className="w-full"
              disabled={!isCompleteCode(code) || saving}
              onClick={() => submit(code)}
            >
              {saving ? <Spin /> : "Update password"}
            </Button>
            <div className="flex items-center justify-between">
              <button
                type="button"
                onClick={startOver}
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
