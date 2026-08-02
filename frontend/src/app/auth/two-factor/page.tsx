"use client"

import { Key, ShieldCheck, SignOut } from "@phosphor-icons/react/dist/ssr"
import { useRouter } from "next/navigation"
import { useCallback, useEffect, useState } from "react"

import { AuthShell } from "@/components/auth-shell"
import {
  OtpField,
  TOTP_LENGTH,
  isCompleteCode,
} from "@/components/auth/otp-field"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Spin } from "@/components/ui/loader"
import { api } from "@/lib/api"
import { authErrorMessage } from "@/lib/auth-errors"
import { createClient } from "@/lib/supabase/client"
import { toast } from "@/lib/toast"

/**
 * Step-up two-factor.
 *
 * Reached when the API refuses a session with 403 + `X-MFA-Required` - that is,
 * the user is genuinely signed in but has not cleared their second factor, so
 * the token is `aal1` while the account demands `aal2`. Sending them back to
 * /login would be wrong twice over: they are not signed out, and the middleware
 * would bounce them straight to /dashboard and back into the same 403.
 *
 * Only the authenticator-app factor is challenged here. A passkey sign-in
 * already lands at aal2, so a passkey user never arrives on this page.
 */
export default function TwoFactorPage() {
  const router = useRouter()
  const supabase = createClient()

  const [code, setCode] = useState("")
  const [invalid, setInvalid] = useState(false)
  const [loading, setLoading] = useState(false)
  const [factorId, setFactorId] = useState<string | null>(null)
  const [state, setState] = useState<"loading" | "ready" | "none">("loading")
  // Lost-device path. Kept behind a link rather than shown up front: a recovery
  // code is single-use and burns a factor, so it should not be the obvious
  // choice when the phone is simply in another room.
  const [recovering, setRecovering] = useState(false)
  const [recoveryCode, setRecoveryCode] = useState("")
  const [recoveryBusy, setRecoveryBusy] = useState(false)

  useEffect(() => {
    let alive = true
    supabase.auth.mfa.listFactors().then(({ data, error }) => {
      if (!alive) return
      const totp = data?.totp?.[0]
      if (error || !totp) {
        setState("none")
        return
      }
      setFactorId(totp.id)
      setState("ready")
    })
    return () => {
      alive = false
    }
  }, [supabase])

  const verify = useCallback(
    async (value: string) => {
      if (!factorId || loading) return
      setLoading(true)
      setInvalid(false)
      const { error } = await supabase.auth.mfa.challengeAndVerify({
        factorId,
        code: value,
      })
      if (error) {
        setLoading(false)
        setInvalid(true)
        setCode("")
        toast.error(authErrorMessage(error, "That code isn't right."))
        return
      }

      // Verify the outcome. Navigating on a session that did not actually
      // reach aal2 sends the user to a dashboard that 403s and redirects
      // right back here - an invisible loop rather than an error.
      const { data: level } =
        await supabase.auth.mfa.getAuthenticatorAssuranceLevel()
      setLoading(false)
      if (level && level.currentLevel !== "aal2") {
        setInvalid(true)
        setCode("")
        toast.error("Could not complete two-factor. Please try again.")
        return
      }
      // The session is aal2 now. A hard navigation rather than router.push:
      // SWR caches across the app are holding 403s from before the step-up,
      // and a full load is the simplest way to be sure nothing stale survives.
      // replace, not assign: Back must not return to the code prompt.
      window.location.replace("/dashboard")
    },
    [supabase, factorId, loading]
  )

  async function redeemRecoveryCode() {
    const value = recoveryCode.trim()
    if (!value || recoveryBusy) return
    setRecoveryBusy(true)
    try {
      // Consuming a code REMOVES the account's second factors - a code cannot
      // grant aal2, only Supabase can. Afterwards the account genuinely has no
      // factor, so the session's aal1 becomes correct and the gate opens.
      await api("/api/account/recovery-codes/consume", {
        method: "POST",
        body: JSON.stringify({ code: value }),
      })
      toast.success("Recovery code accepted", {
        description: "Two-factor is now off. Set it up again from Settings.",
      })
      // Hard navigation: every SWR cache in the app is holding a 403 from
      // before this moment.
      window.location.replace("/settings/profile")
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "That recovery code isn't valid."
      )
      setRecoveryBusy(false)
    }
  }

  async function signOut() {
    await supabase.auth.signOut()
    router.push("/login")
    router.refresh()
  }

  return (
    <AuthShell
      title="Confirm it's you"
      subtitle={
        state === "none"
          ? "This account needs a second factor to continue"
          : "Enter the code from your authenticator app"
      }
    >
      <div className="space-y-5">
        <div className="flex justify-center">
          <span className="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
            <ShieldCheck weight="duotone" className="size-6" />
          </span>
        </div>

        {state === "loading" && (
          <p className="text-center text-sm text-muted-foreground">Loading…</p>
        )}

        {state === "none" && (
          // Enforcement is on and a verified factor exists (that is why the API
          // refused), but none of them is a TOTP factor we can challenge here -
          // a passkey-only account signed in some other way. Signing in again
          // with the passkey is the fix, so don't pretend a code will help.
          <div className="space-y-4 text-center">
            <p className="text-sm">
              Sign in again with your passkey to continue - this session
              can&apos;t be upgraded from here.
            </p>
            <Button className="w-full" onClick={signOut}>
              Back to sign in
            </Button>
          </div>
        )}

        {state === "ready" && (
          <>
            <OtpField
              value={code}
              onChange={setCode}
              onComplete={verify}
              disabled={loading}
              invalid={invalid}
              label="Authentication code"
              length={TOTP_LENGTH}
            />
            <Button
              type="button"
              className="h-11 w-full rounded-xl text-[15px] sm:h-12"
              disabled={!isCompleteCode(code, TOTP_LENGTH) || loading}
              onClick={() => verify(code)}
            >
              {loading ? (
                <span className="inline-flex items-center gap-2">
                  Verifying
                  <Spin />
                </span>
              ) : (
                "Verify"
              )}
            </Button>
            {recovering ? (
              <div className="space-y-3 rounded-xl border bg-muted/30 p-3">
                <p className="text-xs text-muted-foreground">
                  Enter one of the recovery codes you saved when you set up
                  two-factor. It can only be used once, and it will turn
                  two-factor off so you can set it up again.
                </p>
                <Input
                  value={recoveryCode}
                  onChange={(e) => setRecoveryCode(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && redeemRecoveryCode()}
                  placeholder="XXXXXXXXXX"
                  autoComplete="off"
                  autoCapitalize="characters"
                  className="text-center font-mono tracking-widest"
                />
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    className="flex-1"
                    onClick={() => setRecovering(false)}
                  >
                    Back
                  </Button>
                  <Button
                    type="button"
                    className="flex-1"
                    disabled={!recoveryCode.trim() || recoveryBusy}
                    onClick={redeemRecoveryCode}
                  >
                    {recoveryBusy ? <Spin /> : "Use code"}
                  </Button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setRecovering(true)}
                className="flex w-full items-center justify-center gap-1.5 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
              >
                <Key className="size-3.5" />
                Lost your device? Use a recovery code
              </button>
            )}

            <button
              type="button"
              onClick={signOut}
              className="flex w-full items-center justify-center gap-1.5 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            >
              <SignOut className="size-3.5" />
              Sign out instead
            </button>
          </>
        )}
      </div>
    </AuthShell>
  )
}
