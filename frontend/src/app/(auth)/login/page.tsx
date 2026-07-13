"use client"

import { ArrowRight } from "@phosphor-icons/react/dist/ssr"
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

const FIELD = "h-12 rounded-xl bg-muted/50"

export default function LoginPage() {
  const router = useRouter()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    const { error } = await createClient().auth.signInWithPassword({
      email,
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
    if (!email) {
      toast.error("Enter your email above first")
      return
    }
    const { error } = await createClient().auth.resetPasswordForEmail(email, {
      redirectTo: `${location.origin}/auth/callback?next=/auth/reset-password`,
    })
    if (error) toast.error(error.message)
    else toast.success("Password reset email sent - check your inbox")
  }

  return (
    <AuthShell
      title="Welcome back"
      subtitle="Sign in to your workspace to continue"
    >
      <form onSubmit={handleSubmit} className="space-y-3">
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
            onChange={(e) => setEmail(e.target.value)}
            className={FIELD}
          />
        </div>
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
              className="text-xs font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            >
              Forgot password?
            </button>
          </div>
        </div>
        <Button
          type="submit"
          className="h-12 w-full rounded-xl gap-1.5 text-[15px]"
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

      <OrDivider />
      <OAuthButtons />

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
