"use client"

import { ArrowRight } from "@phosphor-icons/react/dist/ssr"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { toast } from "@/lib/toast"

import { AuthShell } from "@/components/auth-shell"
import { OAuthButtons, OrDivider } from "@/components/auth/oauth-buttons"
import { ConfirmPasswordField, PasswordField } from "@/components/password-field"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Spin } from "@/components/ui/loader"
import { passwordFailures } from "@/lib/password"
import { createClient } from "@/lib/supabase/client"

const FIELD = "h-11 sm:h-12 rounded-xl bg-muted/50"

export default function SignupPage() {
  const router = useRouter()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [loading, setLoading] = useState(false)
  const [attempted, setAttempted] = useState(false)
  const [emailSent, setEmailSent] = useState(false)
  const [existing, setExisting] = useState(false)

  const failing = passwordFailures(password)

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
      options: { emailRedirectTo: `${location.origin}/auth/callback` },
    })
    setLoading(false)
    if (error) {
      toast.error(error.message)
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
      router.push("/dashboard")
      router.refresh()
    } else {
      setEmailSent(true)
    }
  }

  return (
    <AuthShell
      title="Create your account"
      subtitle="Start building RAG APIs over your documents"
    >
      {emailSent ? (
        <p className="text-sm">
          Check your inbox - we sent a confirmation link to{" "}
          <span className="font-medium">{email}</span>.
        </p>
      ) : (
        <>
          <form onSubmit={handleSubmit} className="space-y-3">
            {existing && (
              <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-300">
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
              className="h-11 w-full gap-1.5 rounded-xl text-[15px] sm:h-12"
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
              className="rounded-lg border bg-muted/60 px-3 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted"
            >
              Login
            </Link>
          </p>
        </>
      )}
    </AuthShell>
  )
}
