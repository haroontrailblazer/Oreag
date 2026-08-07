"use client"

import {
  ArrowRightIcon as ArrowRight,
  EnvelopeSimpleIcon as EnvelopeSimple,
  FingerprintIcon as Fingerprint,
  PencilSimpleIcon as PencilSimple,
  ShieldCheckIcon as ShieldCheck,
} from "@phosphor-icons/react/dist/ssr"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useCallback, useState } from "react"

import { AuthShell } from "@/components/auth-shell"
import {
  OtpField,
  TOTP_LENGTH,
  isCompleteCode,
} from "@/components/auth/otp-field"
import { OAuthButtons, OrDivider } from "@/components/auth/oauth-buttons"
import { RecoveryCodeForm } from "@/components/auth/recovery-code-form"
import { SetPasswordForm } from "@/components/set-password-form"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Spin } from "@/components/ui/loader"
import { PasswordInput } from "@/components/ui/password-input"
import {
  authErrorMessage,
  isPasskeyCancellation,
} from "@/lib/auth-errors"
import { usePasskeySupport, useResendCooldown } from "@/lib/auth-hooks"
import {
  NO_FACTORS,
  loadSecondFactors,
  preferredFactor,
  verifyPasskeyFactor,
  type SecondFactors,
} from "@/lib/mfa"
import { createClient } from "@/lib/supabase/client"
import { toast } from "@/lib/toast"

const FIELD = "h-11 sm:h-12 rounded-xl bg-muted/50"
const ALTERNATE_METHOD =
  "h-10 min-w-32 flex-1 basis-[calc(50%-0.25rem)] rounded-xl bg-card px-3 text-sm"

type Provider = "google" | "github"
type AuthMethods = {
  exists: boolean
  has_password: boolean
  providers: Provider[]
  /**
   * Whether this account has a login passkey (auth.webauthn_credentials).
   * Optional because an environment running migration 0017 but not 0020 does
   * not return it - in which case the passkey button simply stays hidden
   * rather than appearing and failing.
   */
  has_passkey?: boolean
  /** Whether any verified second factor exists. Informational only. */
  has_mfa?: boolean
}
const PROVIDER_LABEL: Record<Provider, string> = {
  google: "Google",
  github: "GitHub",
}

/**
 * Steps, in the order a user can meet them.
 *
 * `mfa` is reachable from `password`, `code` and OAuth alike - the gate is a
 * property of the account, not of how they got here.
 */
type Step = "email" | "password" | "oauth" | "code" | "reset" | "mfa"

/**
 * Identifier-first login with layered authentication.
 *
 * The layering rule, which is the whole design: **the strongest method that
 * succeeds ends the ceremony.** A passkey is already possession plus user
 * verification and is phishing-resistant, so it signs in alone. Password,
 * emailed code and magic link are weaker, so they pass through the second-factor
 * gate when the account has one enrolled.
 *
 * Everything degrades: an unreachable methods lookup falls back to the password
 * field, an unsupported browser simply never sees the passkey button, and a
 * missing second factor skips the gate entirely.
 */
export default function LoginPage() {
  const router = useRouter()
  const supabase = createClient()
  const passkeySupported = usePasskeySupport()

  const [step, setStep] = useState<Step>("email")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [methods, setMethods] = useState<AuthMethods | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [checking, setChecking] = useState(false)
  const [loading, setLoading] = useState(false)

  const [code, setCode] = useState("")
  const [codeError, setCodeError] = useState(false)
  // Recovery code accepted -> render the new-password form instead of the code
  // field. Lives here rather than in a nested component: a component declared
  // inside this one is a new type on every render, so React would remount it
  // and lose exactly this flag.
  const [recovered, setRecovered] = useState(false)
  // A recovery code establishes an aal1 session. Supabase REFUSES to change the
  // password of an account with a verified factor from aal1
  // (401 insufficient_aal), so a 2FA account has to clear its second factor
  // between entering the emailed code and choosing a new password. Without this
  // step, Forgot password was a dead end for exactly those accounts: the fields
  // appeared and the update always failed.
  const [resetNeedsMfa, setResetNeedsMfa] = useState(false)
  // Loaded while the user is typing their code, not when they press Verify.
  // listFactors() is a network round trip; doing it on the click put three
  // sequential auth requests between the button and any visible progress.
  const [mfaFactorId, setMfaFactorId] = useState<string | null>(null)
  // Which second factor this account actually has. A webauthn FACTOR is not
  // the same thing as a login passkey - see lib/mfa.ts.
  const [factors, setFactors] = useState<SecondFactors>(NO_FACTORS)
  const resend = useResendCooldown()

  // NOTE: do NOT prefetch /dashboard from here. It is behind the middleware,
  // so a prefetch issued while still signed out is answered with a redirect to
  // /login - and Next caches that. The push after a successful sign-in would
  // then replay the cached redirect and bounce the user back to this page.
  const finish = useCallback(() => {
    // replace, NOT push: the sign-in page must not stay in history. With push,
    // one tap of Back re-opens the email / code / password screens of an
    // already-completed sign-in, which looks broken and invites people to
    // re-enter a code that has been consumed.
    router.replace("/dashboard")
    router.refresh()
  }, [router])

  /**
   * Route to the second factor when the account has one and this session
   * hasn't cleared it.
   *
   * `nextLevel > currentLevel` is the whole condition. A passkey sign-in
   * already lands at aal2, so this naturally returns false for it - no
   * special-casing, and no double prompt.
   *
   * Fails OPEN on error: if the assurance lookup itself breaks we let the user
   * through rather than stranding them, because the backend enforces the same
   * rule on every request anyway (see backend/app/auth/jwt.py). The UI gate is
   * for a good experience; the server gate is for security.
   */
  const routeAfterSignIn = useCallback(async () => {
    const { data, error } =
      await supabase.auth.mfa.getAuthenticatorAssuranceLevel()
    if (error || !data) {
      finish()
      return
    }
    if (data.nextLevel === "aal2" && data.nextLevel !== data.currentLevel) {
      setCode("")
      setCodeError(false)
      setStep("mfa")
      // Deliberately not awaited: show the gate immediately and resolve which
      // factor it is in the background while the user reaches for their phone
      // (or their fingerprint reader).
      void loadSecondFactors(supabase).then((found) => {
        setFactors(found)
        if (found.totp) setMfaFactorId(found.totp.id)
      })
      return
    }
    finish()
  }, [supabase, finish])

  async function handleContinue(e: React.FormEvent) {
    e.preventDefault()
    const value = email.trim().toLowerCase()
    if (!value) return
    setChecking(true)
    setNotFound(false)
    try {
      // Same-origin Next.js route (always up with this page), so the routing
      // works even when the FastAPI backend is asleep.
      const res = await fetch("/api/auth/methods", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: value }),
      })
      if (res.status === 429) {
        toast.error("Too many attempts - please wait a moment and retry.")
        return
      }
      if (!res.ok) {
        // Lookup unavailable (not configured / DB error) - degrade to the
        // classic password step so login is never blocked by this hint.
        setStep("password")
        return
      }
      const m = (await res.json()) as AuthMethods
      if (!m.exists) {
        setNotFound(true)
      } else if (m.providers.length > 0 && !m.has_password) {
        // OAuth-only account -> steer to the provider, never a dead-end.
        setMethods(m)
        setStep("oauth")
      } else {
        setMethods(m)
        setStep("password")
      }
    } catch {
      setStep("password") // network error - degrade gracefully
    } finally {
      setChecking(false)
    }
  }

  async function handlePasskey() {
    setLoading(true)
    try {
      // Discoverable credential. signInWithPasskey takes no email - the
      // authenticator supplies the identity - so the typed address only
      // decides WHETHER to offer this, never which credential is used.
      const { error } = await supabase.auth.signInWithPasskey()
      if (error) throw error
      await routeAfterSignIn()
    } catch (err) {
      // Dismissing the system sheet is a normal action, not an error.
      if (isPasskeyCancellation(err)) return
      toast.error(
        authErrorMessage(err, "That passkey didn't work. Try another way.")
      )
    } finally {
      setLoading(false)
    }
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    const { error } = await supabase.auth.signInWithPassword({
      email: email.trim().toLowerCase(),
      password,
    })
    setLoading(false)
    if (error) {
      toast.error(authErrorMessage(error))
      return
    }
    await routeAfterSignIn()
  }

  /** Email a sign-in code. Never creates an account - see shouldCreateUser. */
  async function sendLoginCode() {
    const ok = await resend.send(async () => {
      const { error } = await supabase.auth.signInWithOtp({
        email: email.trim().toLowerCase(),
        // Load-bearing: without this an unknown address silently gets a NEW
        // account, turning the login form into a signup and enumeration vector.
        options: { shouldCreateUser: false },
      })
      if (error) {
        toast.error(authErrorMessage(error))
        return false
      }
      return true
    })
    if (ok) {
      setCode("")
      setCodeError(false)
      setStep("code")
    }
  }

  const verifyLoginCode = useCallback(
    async (value: string) => {
      if (loading) return
      setLoading(true)
      setCodeError(false)
      const { error } = await supabase.auth.verifyOtp({
        email: email.trim().toLowerCase(),
        token: value,
        type: "email",
      })
      setLoading(false)
      if (error) {
        setCodeError(true)
        setCode("")
        toast.error(authErrorMessage(error, "That code isn't right."))
        return
      }
      await routeAfterSignIn()
    },
    [supabase, email, loading, routeAfterSignIn]
  )

  /** Send a password-reset code (the same email also carries a link). */
  async function sendResetCode() {
    const value = email.trim().toLowerCase()
    if (!value) {
      toast.error("Enter your email first")
      return
    }
    const ok = await resend.send(async () => {
      const { error } = await supabase.auth.resetPasswordForEmail(value, {
        // /auth/confirm, not /auth/callback: the token_hash route survives the
        // link being opened in a different browser, which PKCE cannot.
        redirectTo: `${location.origin}/auth/confirm?next=/auth/reset-password`,
      })
      if (error) {
        toast.error(authErrorMessage(error))
        return false
      }
      return true
    })
    if (ok) {
      setCode("")
      setCodeError(false)
      setStep("reset")
    }
  }

  /**
   * Verify a recovery code. Success establishes a recovery session, which is
   * what lets SetPasswordForm call updateUser - so the session is re-read
   * rather than trusted, and only a real session flips to the password form.
   */
  const submitResetCode = useCallback(
    async (value: string) => {
      if (loading) return
      setLoading(true)
      setCodeError(false)
      const { error } = await supabase.auth.verifyOtp({
        email: email.trim().toLowerCase(),
        token: value,
        type: "recovery",
      })
      if (error) {
        setLoading(false)
        setCodeError(true)
        setCode("")
        toast.error(authErrorMessage(error, "That code isn't right."))
        return
      }
      const { data } = await supabase.auth.getSession()
      if (data.session) {
        const { data: level } =
          await supabase.auth.mfa.getAuthenticatorAssuranceLevel()
        setLoading(false)
        if (level?.nextLevel === "aal2" && level.nextLevel !== level.currentLevel) {
          // Ask for the authenticator BEFORE showing the password fields, so
          // the update cannot fail after the password has been typed twice.
          setCode("")
          setCodeError(false)
          setResetNeedsMfa(true)
          void supabase.auth.mfa.listFactors().then(({ data: list }) => {
            const factor = list?.totp?.[0]
            if (factor) setMfaFactorId(factor.id)
          })
          return
        }
        setRecovered(true)
        return
      }
      setLoading(false)
      // Verified but no session: nothing useful can happen next, so say so
      // instead of showing a password form that would fail on submit.
      setCodeError(true)
      toast.error("Could not start a reset session. Request a new code.")
    },
    [supabase, email, loading]
  )

  /**
   * Clear the gate with a webauthn FACTOR instead of a TOTP code.
   *
   * This raises the session to aal2 exactly as a code would, so the backend
   * check in jwt.py is satisfied by the same mechanism - there is no
   * client-only branch that a caller could skip.
   */
  const verifyPasskeyGate = useCallback(async () => {
    const factorId = factors.passkey?.id
    if (!factorId || loading) return
    setLoading(true)
    try {
      await verifyPasskeyFactor(supabase, factorId)
      finish()
    } catch (err) {
      // Dismissing the system sheet is a normal action, not an error.
      if (!isPasskeyCancellation(err)) {
        toast.error(authErrorMessage(err, "That passkey didn't work."))
      }
    } finally {
      setLoading(false)
    }
  }, [factors.passkey?.id, loading, supabase, finish])

  const verifyMfa = useCallback(
    async (value: string) => {
      if (loading) return
      setLoading(true)
      setCodeError(false)
      // Normally already primed above; the lookup is a fallback for a very
      // fast typist who beat the background fetch.
      let factorId = mfaFactorId
      if (!factorId) {
        const { data: list } = await supabase.auth.mfa.listFactors()
        factorId = list?.totp?.[0]?.id ?? null
      }
      if (!factorId) {
        setLoading(false)
        toast.error("No authenticator app is set up for this account.")
        return
      }
      // Supabase recomputes the TOTP HMAC server-side; nothing here can
      // approve a code.
      const { error } = await supabase.auth.mfa.challengeAndVerify({
        factorId,
        code: value,
      })
      if (error) {
        setLoading(false)
        setCodeError(true)
        setCode("")
        toast.error(authErrorMessage(error, "That code isn't right."))
        return
      }

      // Confirm the session actually reached aal2 rather than trusting the
      // absence of an error. If it did not, the dashboard would load and then
      // 403 on its first request, bouncing the user straight back here.
      const { data: level } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel()
      setLoading(false)
      if (level && level.currentLevel !== "aal2") {
        setCodeError(true)
        setCode("")
        toast.error("Could not complete two-factor. Please try again.")
        return
      }
      // Reached from a password reset: the point of the step-up was to make
      // updateUser legal, so continue to the password form rather than the
      // dashboard.
      if (resetNeedsMfa) {
        setResetNeedsMfa(false)
        setRecovered(true)
        return
      }
      finish()
    },
    [supabase, loading, finish, mfaFactorId, resetNeedsMfa]
  )

  function backToEmail() {
    setStep("email")
    setResetNeedsMfa(false)
    setRecovered(false)
    setPassword("")
    setCode("")
    setCodeError(false)
    setMethods(null)
    setNotFound(false)
  }

  /**
   * "Continue with a passkey", offered only once we know the account has one.
   *
   * Two conditions, both necessary. `has_passkey` comes from the identifier
   * lookup (migration 0020, read from auth.webauthn_credentials): showing this
   * to an account without a passkey opens the system prompt and then fails with
   * nothing to select, which reads as broken software. `passkeySupported`
   * covers browsers that cannot do WebAuthn at all.
   *
   * Absent on the email step by design - there is nothing to gate on until an
   * address has been entered.
   */
  const passkeyButton =
    methods?.has_passkey && passkeySupported !== false ? (
      <Button
        type="button"
        variant="outline"
        className="h-11 w-full gap-2 rounded-xl text-[15px] sm:h-12"
        disabled={loading || passkeySupported === null}
        onClick={handlePasskey}
      >
        {loading ? (
          <span className="inline-flex items-center gap-2">
            Signing you in
            <Spin />
          </span>
        ) : (
          <>
            <Fingerprint weight="duotone" className="size-5" />
            Continue with a passkey
          </>
        )}
      </Button>
    ) : null

  const compactPasskeyButton =
    methods?.has_passkey && passkeySupported !== false ? (
      <Button
        type="button"
        variant="outline"
        className={ALTERNATE_METHOD}
        disabled={loading || passkeySupported === null}
        onClick={handlePasskey}
      >
        {loading ? (
          <Spin />
        ) : (
          <>
            <Fingerprint weight="duotone" className="size-4" />
            Passkey
          </>
        )}
      </Button>
    ) : null

  // The email, shown as a compact chip on later steps with a "change" affordance.
  const emailChip = (
    <button
      type="button"
      onClick={backToEmail}
      className="flex w-full items-center justify-between gap-2 rounded-xl border bg-muted/40 px-4 py-2.5 text-left text-sm transition-colors hover:bg-muted"
    >
      <span className="min-w-0 truncate font-medium">{email}</span>
      <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
        <PencilSimple className="size-3.5" />
        Change
      </span>
    </button>
  )

  const resendButton = (
    <button
      type="button"
      onClick={step === "reset" ? sendResetCode : sendLoginCode}
      disabled={resend.blocked}
      className="text-xs font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:cursor-not-allowed disabled:opacity-50 disabled:no-underline disabled:hover:text-muted-foreground"
    >
      {resend.label}
    </button>
  )

  return (
    <AuthShell
      title={step === "mfa" ? "One more step" : "Welcome back"}
      subtitle={
        step !== "mfa"
          ? "Sign in to your workspace to continue"
          : preferredFactor(factors) === "passkey"
            ? "Confirm with the passkey on this device"
            : "Enter the code from your authenticator app"
      }
      keyboardStable={
        step === "code" ||
        step === "mfa" ||
        (step === "reset" && !recovered)
      }
    >
      {/* key={step} remounts this on every step change so the fade+slide
          replays; the footer below stays put and doesn't re-animate. */}
      <div key={step} className="space-y-6 animate-[auth-step-in_0.28s_ease-out]">
        {step === "email" && (
          <>
            <form onSubmit={handleContinue} className="space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="email" className="sr-only">
                  Email
                </Label>
                <Input
                  id="email"
                  type="email"
                  required
                  autoComplete="username webauthn"
                  placeholder="Email"
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value)
                    setNotFound(false)
                  }}
                  className={FIELD}
                />
              </div>
              {notFound && (
                <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-300">
                  No account found for this email.{" "}
                  <Link href="/signup" className="font-medium underline">
                    Create one
                  </Link>
                  .
                </div>
              )}
              <Button
                type="submit"
                className="h-11 w-full gap-1.5 rounded-xl text-[15px] sm:h-12"
                disabled={checking}
              >
                {checking ? (
                  <Spin />
                ) : (
                  <>
                    Continue
                    <ArrowRight className="size-4" weight="bold" />
                  </>
                )}
              </Button>
            </form>

            <OrDivider label="or login with" />
            <OAuthButtons />
          </>
        )}

        {step === "password" && (
          <>
            <form onSubmit={handleLogin} className="space-y-3">
              {emailChip}
              <div className="space-y-1.5">
                <Label htmlFor="password" className="sr-only">
                  Password
                </Label>
                <PasswordInput
                  id="password"
                  required
                  placeholder="Password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className={FIELD}
                />
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={sendResetCode}
                    disabled={resend.blocked}
                    className="text-xs font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:cursor-not-allowed disabled:opacity-50 disabled:no-underline disabled:hover:text-muted-foreground"
                  >
                    {resend.sending ? "Sending…" : "Forgot password?"}
                  </button>
                </div>
              </div>
              <Button
                type="submit"
                className="h-11 w-full gap-1.5 rounded-xl text-[15px] sm:h-12"
                disabled={loading}
              >
                {loading ? (
                  <span className="inline-flex items-center gap-1">
                    Signing in
                    <Spin />
                  </span>
                ) : (
                  <>
                    Log In
                    <ArrowRight className="size-4" weight="bold" />
                  </>
                )}
              </Button>
            </form>

            <div className="space-y-3">
              <OrDivider label="Other ways to sign in" />
              <div className="flex flex-wrap gap-2">
                {compactPasskeyButton}
                <Button
                  type="button"
                  variant="outline"
                  onClick={sendLoginCode}
                  disabled={resend.blocked}
                  className={ALTERNATE_METHOD}
                >
                  {resend.sending ? (
                    <>
                      <Spin />
                      Sending
                    </>
                  ) : (
                    <>
                      <EnvelopeSimple className="size-4" />
                      Email code
                    </>
                  )}
                </Button>
                {methods && methods.providers.length > 0 && (
                  <OAuthButtons
                    only={methods.providers}
                    className="contents"
                    buttonClassName={ALTERNATE_METHOD}
                  />
                )}
              </div>
            </div>
          </>
        )}

        {step === "oauth" && methods && (
          <div className="space-y-3">
            {emailChip}
            <p className="text-center text-sm text-muted-foreground">
              You usually sign in with{" "}
              <span className="font-medium text-foreground">
                {methods.providers.map((p) => PROVIDER_LABEL[p]).join(" or ")}
              </span>
              . Continue below to sign in.
            </p>
            <OAuthButtons only={methods.providers} />
            {passkeyButton}
            <p className="text-center text-xs text-muted-foreground">
              Prefer email?{" "}
              <button
                type="button"
                onClick={sendLoginCode}
                disabled={resend.blocked}
                className="font-medium text-foreground underline underline-offset-2 disabled:cursor-not-allowed disabled:no-underline disabled:opacity-50"
              >
                {resend.sending ? "Sending…" : "Send me a code"}
              </button>
            </p>
          </div>
        )}

        {step === "code" && (
          <div className="space-y-4">
            {emailChip}
            <p className="text-center text-sm text-muted-foreground">
              We sent a 6-digit code to your email. It expires shortly.
            </p>
            <OtpField
              value={code}
              onChange={setCode}
              onComplete={verifyLoginCode}
              disabled={loading}
              invalid={codeError}
            />
            <Button
              type="button"
              className="h-11 w-full gap-1.5 rounded-xl text-[15px] sm:h-12"
              disabled={!isCompleteCode(code) || loading}
              onClick={() => verifyLoginCode(code)}
            >
              {loading ? <Spin /> : "Continue"}
            </Button>
            <div className="flex justify-center">{resendButton}</div>
          </div>
        )}

        {step === "reset" && resetNeedsMfa && (
          <div className="space-y-4">
            <div className="flex justify-center">
              <span className="flex size-11 items-center justify-center rounded-full bg-muted text-muted-foreground">
                <ShieldCheck weight="duotone" className="size-6" />
              </span>
            </div>
            <p className="text-center text-sm text-muted-foreground">
              Your code checked out. Enter the code from your authenticator app
              to finish resetting your password.
            </p>
            <OtpField
              value={code}
              onChange={setCode}
              onComplete={verifyMfa}
              disabled={loading}
              invalid={codeError}
              label="Authentication code"
              length={TOTP_LENGTH}
            />
            <Button
              type="button"
              className="h-11 w-full gap-1.5 rounded-xl text-[15px] sm:h-12"
              disabled={!isCompleteCode(code, TOTP_LENGTH) || loading}
              onClick={() => verifyMfa(code)}
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
            {/* Lost the authenticator too? Spending a recovery code removes the
                factor, after which aal1 is acceptable and the reset completes. */}
            <RecoveryCodeForm
              onSignOut={async () => {
                // This device only - see components/user-menu.tsx.
                await supabase.auth.signOut({ scope: "local" })
                backToEmail()
              }}
            />
          </div>
        )}

        {step === "reset" && !resetNeedsMfa &&
          (recovered ? (
            <SetPasswordForm
              submitLabel="Update password"
              onSuccess={() => {
                toast.success("Password updated - you're signed in")
                finish()
              }}
            />
          ) : (
            <div className="space-y-4">
              {emailChip}
              {/* Both routes are live and land in the same place, so say so.
                  The code continues here; the link goes through /auth/confirm
                  to /auth/reset-password. */}
              <p className="text-center text-sm text-muted-foreground">
                Enter the code we emailed you, then choose a new password - or
                just click the link in the same email.
              </p>
              <OtpField
                value={code}
                onChange={setCode}
                onComplete={submitResetCode}
                disabled={loading}
                invalid={codeError}
              />
              <Button
                type="button"
                className="h-11 w-full gap-1.5 rounded-xl text-[15px] sm:h-12"
                disabled={!isCompleteCode(code) || loading}
                onClick={() => submitResetCode(code)}
              >
                {loading ? <Spin /> : "Continue"}
              </Button>
              <div className="flex justify-center">{resendButton}</div>
            </div>
          ))}

        {step === "mfa" && preferredFactor(factors) === "passkey" && (
          <div className="space-y-4">
            <div className="flex justify-center">
              <span className="flex size-11 items-center justify-center rounded-full bg-muted text-muted-foreground">
                <Fingerprint weight="duotone" className="size-6" />
              </span>
            </div>
            <p className="text-center text-sm text-muted-foreground">
              Confirm it&rsquo;s you with{" "}
              {factors.passkey?.friendlyName || "your passkey"}.
            </p>
            <Button
              type="button"
              className="h-11 w-full gap-1.5 rounded-xl text-[15px] sm:h-12"
              disabled={loading}
              onClick={verifyPasskeyGate}
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
            <RecoveryCodeForm
              onSignOut={async () => {
                await supabase.auth.signOut({ scope: "local" })
                backToEmail()
              }}
            />
          </div>
        )}

        {/* TOTP keeps the gate whenever it is enrolled, even alongside a
            passkey factor - an account holding both sees exactly the flow it
            had before passkeys became a factor. */}
        {step === "mfa" && preferredFactor(factors) !== "passkey" && (
          <div className="space-y-4">
            <div className="flex justify-center">
              <span className="flex size-11 items-center justify-center rounded-full bg-muted text-muted-foreground">
                <ShieldCheck weight="duotone" className="size-6" />
              </span>
            </div>
            <OtpField
              value={code}
              onChange={setCode}
              onComplete={verifyMfa}
              disabled={loading}
              invalid={codeError}
              label="Authentication code"
              // Authenticator codes are six by RFC 6238, whatever the email
              // OTP length happens to be set to.
              length={TOTP_LENGTH}
            />
            <Button
              type="button"
              className="h-11 w-full gap-1.5 rounded-xl text-[15px] sm:h-12"
              disabled={!isCompleteCode(code, TOTP_LENGTH) || loading}
              onClick={() => verifyMfa(code)}
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
            {/* The same escape hatch as the step-up page. Without it, anyone
                who lost their phone mid-sign-in had no way forward from here -
                the option existed only on a page they had no reason to visit. */}
            <RecoveryCodeForm
              onSignOut={async () => {
                // This device only - see components/user-menu.tsx.
                await supabase.auth.signOut({ scope: "local" })
                backToEmail()
              }}
            />
          </div>
        )}
      </div>

      {step === "email" && (
        <p className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
          Don&apos;t have an account?
          <Link
            href="/signup"
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            Sign up
          </Link>
        </p>
      )}
    </AuthShell>
  )
}
