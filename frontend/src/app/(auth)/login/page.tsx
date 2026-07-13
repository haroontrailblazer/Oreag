"use client"

import { ArrowRight, PencilSimple } from "@phosphor-icons/react/dist/ssr"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { toast } from "@/lib/toast"

import { AuthShell } from "@/components/auth-shell"
import { OAuthButtons, OrDivider } from "@/components/auth/oauth-buttons"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoaderOne } from "@/components/ui/loader"
import { PasswordInput } from "@/components/ui/password-input"
import { createClient } from "@/lib/supabase/client"

const FIELD = "h-11 sm:h-12 rounded-xl bg-muted/50"

type Provider = "google" | "github"
type AuthMethods = {
  exists: boolean
  has_password: boolean
  providers: Provider[]
}
const PROVIDER_LABEL: Record<Provider, string> = {
  google: "Google",
  github: "GitHub",
}

/**
 * Identifier-first login (the flow Google / Amazon / Slack use): the user
 * enters their email first, the server reports which sign-in methods that
 * account actually has, and we route them to the password field or the right
 * OAuth button - so a Google-only user is never dead-ended on "invalid
 * credentials". Degrades to the classic password field if the lookup fails.
 */
export default function LoginPage() {
  const router = useRouter()
  const [step, setStep] = useState<"email" | "password" | "oauth">("email")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [methods, setMethods] = useState<AuthMethods | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [checking, setChecking] = useState(false)
  const [loading, setLoading] = useState(false)
  // "Forgot password?" / "Set one via email" send state - disables the button
  // after one tap so a double-tap can't fire two emails (which trips Supabase's
  // email rate limit).
  const [forgot, setForgot] = useState<"idle" | "sending" | "sent">("idle")
  const forgotLabel = (base: string) =>
    forgot === "sending" ? "Sending…" : forgot === "sent" ? "Email sent" : base

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

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    const { error } = await createClient().auth.signInWithPassword({
      email: email.trim().toLowerCase(),
      password,
    })
    setLoading(false)
    if (error) {
      toast.error(error.message)
      return
    }
    router.push("/dashboard")
    router.refresh()
  }

  async function handleForgot() {
    if (forgot !== "idle") return // guard against double-taps
    const value = email.trim().toLowerCase()
    if (!value) {
      toast.error("Enter your email first")
      return
    }
    setForgot("sending")
    const { error } = await createClient().auth.resetPasswordForEmail(value, {
      redirectTo: `${location.origin}/auth/callback?next=/auth/reset-password`,
    })
    if (error) {
      const rateLimited =
        // Supabase caps auth emails; surface a human message, not the raw one.
        (error as { status?: number }).status === 429 ||
        /rate limit|too many|security purposes/i.test(error.message)
      toast.error(
        rateLimited
          ? "Too many email requests - please try again in about an hour."
          : error.message
      )
      setForgot("idle") // let them retry later
      return
    }
    toast.success("Password reset email sent - check your inbox")
    setForgot("sent") // stays disabled so a second tap can't re-send
  }

  function backToEmail() {
    setStep("email")
    setPassword("")
    setMethods(null)
    setNotFound(false)
    setForgot("idle")
  }

  // The email, shown as a compact chip on step 2/3 with a "change" affordance.
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

  return (
    <AuthShell
      title="Welcome back"
      subtitle="Sign in to your workspace to continue"
    >
      {/* key={step} remounts this on every step change so the fade+slide
          replays; the footer below stays put and doesn't re-animate. */}
      <div
        key={step}
        className="space-y-6 animate-[auth-step-in_0.28s_ease-out]"
      >
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
                <LoaderOne />
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
                  onClick={handleForgot}
                  disabled={forgot !== "idle"}
                  className="text-xs font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:cursor-not-allowed disabled:opacity-50 disabled:no-underline disabled:hover:text-muted-foreground"
                >
                  {forgotLabel("Forgot password?")}
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
                  <LoaderOne />
                </span>
              ) : (
                <>
                  Log In
                  <ArrowRight className="size-4" weight="bold" />
                </>
              )}
            </Button>
          </form>

          {methods && methods.providers.length > 0 && (
            <>
              <OrDivider label="or login with" />
              <OAuthButtons only={methods.providers} />
            </>
          )}
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
          <p className="text-center text-xs text-muted-foreground">
            Prefer a password?{" "}
            <button
              type="button"
              onClick={handleForgot}
              disabled={forgot !== "idle"}
              className="font-medium text-foreground underline underline-offset-2 disabled:cursor-not-allowed disabled:no-underline disabled:opacity-50"
            >
              {forgotLabel("Set one via email")}
            </button>
          </p>
        </div>
        )}
      </div>

      <p className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
        Don&apos;t have an account?
        <Link
          href="/signup"
          className="rounded-lg border bg-muted/60 px-3 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted"
        >
          Sign up
        </Link>
      </p>
    </AuthShell>
  )
}
