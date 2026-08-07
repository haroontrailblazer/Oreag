"use client"

import {
  FingerprintIcon as Fingerprint,
  ShieldCheckIcon as ShieldCheck,
} from "@phosphor-icons/react/dist/ssr"
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
import { authErrorMessage, isPasskeyCancellation } from "@/lib/auth-errors"
import {
  NO_FACTORS,
  loadSecondFactors,
  preferredFactor,
  verifyPasskeyFactor,
  type SecondFactors,
} from "@/lib/mfa"
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
 * Both factor types are challengeable here. A webauthn FACTOR raises the
 * session to aal2 exactly as a code does, so an OAuth or emailed-code sign-in
 * on a passkey-protected account steps up in place rather than being told to
 * start over. (A LOGIN passkey is different - that signs in at aal2 already and
 * never reaches this page. See lib/mfa.ts.)
 */
export default function TwoFactorPage() {
  const router = useRouter()
  const supabase = createClient()

  const [code, setCode] = useState("")
  const [invalid, setInvalid] = useState(false)
  const [loading, setLoading] = useState(false)
  const [factorId, setFactorId] = useState<string | null>(null)
  const [factors, setFactors] = useState<SecondFactors>(NO_FACTORS)
  const [state, setState] = useState<"loading" | "ready" | "passkey" | "none">(
    "loading"
  )

  useEffect(() => {
    let alive = true
    void loadSecondFactors(supabase).then((found) => {
      if (!alive) return
      setFactors(found)
      const preferred = preferredFactor(found)
      if (preferred === "totp" && found.totp) {
        setFactorId(found.totp.id)
        setState("ready")
      } else if (preferred === "passkey") {
        setState("passkey")
      } else {
        setState("none")
      }
    })
    return () => {
      alive = false
    }
  }, [supabase])

  /** Clear the gate with a webauthn factor. Same aal2 outcome as a code. */
  const verifyPasskey = useCallback(async () => {
    const id = factors.passkey?.id
    if (!id || loading) return
    setLoading(true)
    try {
      await verifyPasskeyFactor(supabase, id)
      // Hard navigation for the same reason as the code path below: SWR caches
      // are holding 403s from before the step-up.
      window.location.replace("/dashboard")
    } catch (err) {
      setLoading(false)
      if (!isPasskeyCancellation(err)) {
        toast.error(authErrorMessage(err, "That passkey didn't work."))
      }
    }
  }, [factors.passkey?.id, loading, supabase])

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
          : state === "passkey"
            ? "Confirm with the passkey on this device"
            : "Enter the code from your authenticator app"
      }
      keyboardStable={state === "ready"}
    >
      <div className="space-y-5">
        <div className="flex justify-center">
          <span className="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
            {state === "passkey" ? (
              <Fingerprint weight="duotone" className="size-6" />
            ) : (
              <ShieldCheck weight="duotone" className="size-6" />
            )}
          </span>
        </div>

        {state === "loading" && (
          <p className="text-center text-sm text-muted-foreground">Loading…</p>
        )}

        {state === "passkey" && (
          <div className="space-y-4">
            <p className="text-center text-sm text-muted-foreground">
              Confirm it&rsquo;s you with{" "}
              {factors.passkey?.friendlyName || "your passkey"}.
            </p>
            <Button
              className="h-11 w-full gap-1.5 rounded-xl text-[15px] sm:h-12"
              disabled={loading}
              onClick={verifyPasskey}
            >
              {loading ? (
                <span className="inline-flex items-center gap-2">
                  Verifying
                  <Spin />
                </span>
              ) : (
                "Use passkey"
              )}
            </Button>
            <RecoveryCodeForm onSignOut={signOut} />
          </div>
        )}

        {state === "none" && (
          // Enforcement is on and the API refused, but this account has no
          // factor we can challenge - an unverified enrolment, or a factor
          // removed on another device since the token was minted. Signing in
          // again is the only honest instruction.
          <div className="space-y-4 text-center">
            <p className="text-sm">
              Sign in again to continue - this session can&apos;t be upgraded
              from here.
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
            <RecoveryCodeForm onSignOut={signOut} />
          </>
        )}
      </div>
    </AuthShell>
  )
}
