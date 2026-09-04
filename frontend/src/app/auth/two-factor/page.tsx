"use client"

import { ShieldCheckIcon as ShieldCheck} from "@phosphor-icons/react/dist/ssr"
import { useRouter } from "next/navigation"
import { useCallback, useEffect, useState } from "react"

import { AuthShell } from "@/components/auth-shell"
import { RecoveryCodeForm } from "@/components/auth/recovery-code-form"
import {
  OtpField,
  TOTP_LENGTH,
  isCompleteCode,
} from "@/components/auth/otp-field"
import { Button } from "@/components/ui/button"
import { Spin } from "@/components/ui/loader"
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

  async function signOut() {
    // This device only - see components/user-menu.tsx.
    await supabase.auth.signOut({ scope: "local" })
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
      keyboardStable={state === "ready"}
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
              className="h-11 w-full rounded-none text-[15px] sm:h-12"
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
            <RecoveryCodeForm onSignOut={signOut} />
          </>
        )}
      </div>
    </AuthShell>
  )
}
