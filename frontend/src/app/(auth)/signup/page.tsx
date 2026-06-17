"use client"

import { X } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { toast } from "sonner"

import { AuthShell } from "@/components/auth-shell"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { PasswordInput } from "@/components/ui/password-input"
import { passwordFailures } from "@/lib/password"
import { createClient } from "@/lib/supabase/client"

export default function SignupPage() {
  const router = useRouter()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [attempted, setAttempted] = useState(false)
  const [emailSent, setEmailSent] = useState(false)

  const failing = passwordFailures(password)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (failing.length > 0) {
      setAttempted(true)
      return
    }
    setLoading(true)
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
    if (data.session) {
      // email confirmation disabled — signed in immediately
      router.push("/dashboard")
      router.refresh()
    } else {
      setEmailSent(true)
    }
  }

  return (
    <AuthShell active="signup">
      {emailSent ? (
        <p className="text-sm">
          Check your inbox — we sent a confirmation link to{" "}
          <span className="font-medium">{email}</span>.
        </p>
      ) : (
        <>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                required
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="bg-muted/50"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <PasswordInput
                id="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="bg-muted/50"
              />
              {attempted && failing.length > 0 && (
                <div className="rounded-md border border-destructive/40 bg-destructive/5 p-2.5">
                  <p className="text-xs font-medium text-destructive">
                    Your password needs:
                  </p>
                  <ul className="mt-1.5 space-y-1">
                    {failing.map((r) => (
                      <li
                        key={r.label}
                        className="flex items-center gap-1.5 text-xs text-destructive"
                      >
                        <X className="size-3.5 shrink-0" />
                        {r.label}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Creating account…" : "Sign Up"}
            </Button>
          </form>
          <p className="text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link href="/login" className="font-medium text-foreground underline">
              Sign in
            </Link>
          </p>
        </>
      )}
    </AuthShell>
  )
}
