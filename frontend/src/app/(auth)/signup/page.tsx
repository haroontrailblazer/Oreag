"use client"

import { ArrowRightIcon as ArrowRight} from "@phosphor-icons/react/dist/ssr"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useCallback, useState } from "react"
import { api } from "@/lib/api"
import { toast } from "@/lib/toast"

import { AuthShell } from "@/components/auth-shell"
import { OtpField, isCompleteCode } from "@/components/auth/otp-field"
import { OAuthButtons, OrDivider } from "@/components/auth/oauth-buttons"
import { ConfirmPasswordField, PasswordField } from "@/components/password-field"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Spin } from "@/components/ui/loader"
import { authErrorMessage } from "@/lib/auth-errors"
import { useResendCooldown } from "@/lib/auth-hooks"
import { passwordFailures } from "@/lib/password"
import { createClient } from "@/lib/supabase/client"

const FIELD = "h-11 sm:h-12 rounded-none bg-muted/50"

/**
 * Tell the backend to register this account with Langfuse.
 *
 * Fired from BOTH signup success paths - the immediate-session one and the
 * email-confirmation one - because those are the two moments a new account
 * first holds a session, and the endpoint needs one to know who it is.
 *
 * Swallows its own failure on purpose. Observability is bookkeeping; a signup
 * that worked must never look like it failed because a tracing backend was
 * unreachable. The endpoint is idempotent, and any query the account makes
 * later would register it anyway - this only makes it appear immediately.
 */
async function registerObservability(): Promise<void> {
  try {
    await api("/api/account/observability", { method: "POST" })
  } catch {
    // deliberately ignored - see above
  }
}

export default function SignupPage() {
  const router = useRouter()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [loading, setLoading] = useState(false)
  const [attempted, setAttempted] = useState(false)
  const [emailSent, setEmailSent] = useState(false)
  const [existing, setExisting] = useState(false)
  const [code, setCode] = useState("")
  const [codeError, setCodeError] = useState(false)
  const [verifying, setVerifying] = useState(false)
  const resend = useResendCooldown()

  const failing = passwordFailures(password)

  /**
   * Confirm the account with the emailed code.
   *
   * `verifyOtp` with `token` is the same call the link handler at
   * /auth/confirm makes with `token_hash` - one code path, two carriers - so
   * whichever the user reaches for, the outcome is identical.
   */
  const verifyCode = useCallback(
    async (value: string) => {
      if (verifying) return
      setVerifying(true)
      setCodeError(false)
      const { error } = await createClient().auth.verifyOtp({
        email: email.trim().toLowerCase(),
        token: value,
        type: "signup",
      })
      setVerifying(false)
      if (error) {
        setCodeError(true)
        setCode("")
        toast.error(authErrorMessage(error, "That code isn't right."))
        return
      }
      toast.success("Email confirmed - welcome to Oreag")
      void registerObservability()
      router.replace("/dashboard")  // see login/page.tsx: never leave signup in history
      router.refresh()
    },
    [email, verifying, router]
  )

  async function resendCode() {
    await resend.send(async () => {
      const { error } = await createClient().auth.resend({
        type: "signup",
        email: email.trim().toLowerCase(),
      })
      if (error) {
        toast.error(authErrorMessage(error))
        return false
      }
      return true
    })
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (failing.length > 0 || password !== confirm) {
      setAttempted(true)
      return
    }
    setLoading(true)
    setExisting(false)
    const supabase = createClient()
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      // /auth/confirm rather than /auth/callback: the token_hash route works
      // regardless of which browser opens the link, which the PKCE ?code=
      // route cannot guarantee. The same email also carries a typeable code.
      options: { emailRedirectTo: `${location.origin}/auth/confirm` },
    })
    setLoading(false)
    if (error) {
      toast.error(authErrorMessage(error))
      return
    }
    // Supabase hides already-registered emails (enumeration protection): instead
    // of erroring it returns a user with an empty `identities` array. Detect that
    // and tell the user to sign in, rather than pretending we sent a new email.
    if (data.user && (data.user.identities?.length ?? 0) === 0) {
      setExisting(true)
      return
    }
    if (data.session) {
      // email confirmation disabled - signed in immediately
      void registerObservability()
      router.replace("/dashboard")  // see login/page.tsx: never leave signup in history
      router.refresh()
    } else {
      setEmailSent(true)
    }
  }

  return (
    <AuthShell
      title="Create your account"
      subtitle="Start building RAG APIs over your documents"
      keyboardStable={emailSent}
    >
      {emailSent ? (
        <div className="space-y-4">
          <p className="text-center text-sm text-muted-foreground">
            We sent a 6-digit code to{" "}
            <span className="font-medium text-foreground">{email}</span>. Enter
            it below, or use the link in the same email.
          </p>
          <OtpField
            value={code}
            onChange={setCode}
            onComplete={verifyCode}
            disabled={verifying}
            invalid={codeError}
          />
          <Button
            type="button"
            className="h-11 w-full gap-1.5 rounded-none text-[15px] sm:h-12"
            disabled={!isCompleteCode(code) || verifying}
            onClick={() => verifyCode(code)}
          >
            {verifying ? <Spin /> : "Confirm email"}
          </Button>
          <div className="flex justify-center">
            <button
              type="button"
              onClick={resendCode}
              disabled={resend.blocked}
              className="text-xs font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:cursor-not-allowed disabled:opacity-50 disabled:no-underline disabled:hover:text-muted-foreground"
            >
              {resend.label}
            </button>
          </div>
        </div>
      ) : (
        <>
          <form onSubmit={handleSubmit} className="space-y-3">
            {existing && (
              <div className="rounded-none border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-300">
                You already have an account with this email.{" "}
                <Link href="/login" className="font-medium underline">
                  Sign in instead
                </Link>
                .
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="email" className="sr-only">
                Email
              </Label>
              <Input
                id="email"
                type="email"
                required
                placeholder="Email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value)
                  setExisting(false)
                }}
                className={FIELD}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password" className="sr-only">
                Password
              </Label>
              <PasswordField
                id="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                attempted={attempted}
                className={FIELD}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="confirm-password" className="sr-only">
                Retype password
              </Label>
              <ConfirmPasswordField
                id="confirm-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                password={password}
                className={FIELD}
              />
            </div>
            <Button
              type="submit"
              className="h-11 w-full gap-1.5 rounded-none text-[15px] sm:h-12"
              disabled={loading}
            >
              {loading ? (
                <Spin />
              ) : (
                <>
                  Sign Up
                  <ArrowRight className="size-4" weight="bold" />
                </>
              )}
            </Button>
          </form>

          <OrDivider />
          <OAuthButtons />

          <p className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
            Already have an account?
            <Link
              href="/login"
              className="font-medium text-primary underline-offset-4 hover:underline"
            >
              Login
            </Link>
          </p>
        </>
      )}
    </AuthShell>
  )
}
