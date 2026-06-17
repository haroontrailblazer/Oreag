"use client"

import { Check } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { PasswordInput } from "@/components/ui/password-input"
import { createClient } from "@/lib/supabase/client"
import { cn } from "@/lib/utils"

const PASSWORD_RULES: { label: string; test: (p: string) => boolean }[] = [
  { label: "At least 12 characters", test: (p) => p.length >= 12 },
  { label: "One uppercase letter", test: (p) => /[A-Z]/.test(p) },
  { label: "One special character", test: (p) => /[^A-Za-z0-9]/.test(p) },
]

export default function SignupPage() {
  const router = useRouter()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [emailSent, setEmailSent] = useState(false)

  const passwordChecks = PASSWORD_RULES.map((r) => ({
    label: r.label,
    ok: r.test(password),
  }))
  const passwordValid = passwordChecks.every((c) => c.ok)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!passwordValid) {
      toast.error("Password doesn't meet the requirements below.")
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
    <div className="flex min-h-screen items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl">Create your account</CardTitle>
          <CardDescription>
            Build and query RAG APIs over your documents
          </CardDescription>
        </CardHeader>
        <CardContent>
          {emailSent ? (
            <p className="text-sm">
              Check your inbox — we sent a confirmation link to{" "}
              <span className="font-medium">{email}</span>.
            </p>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <PasswordInput
                  id="password"
                  required
                  minLength={12}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <ul className="space-y-1 pt-1">
                  {passwordChecks.map((c) => (
                    <li
                      key={c.label}
                      className={cn(
                        "flex items-center gap-1.5 text-xs transition-colors",
                        c.ok
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-muted-foreground"
                      )}
                    >
                      <Check
                        className={cn("size-3.5", c.ok ? "opacity-100" : "opacity-30")}
                      />
                      {c.label}
                    </li>
                  ))}
                </ul>
              </div>
              <Button
                type="submit"
                className="w-full"
                disabled={loading || !passwordValid}
              >
                {loading ? "Creating account…" : "Sign up"}
              </Button>
            </form>
          )}
          <p className="mt-4 text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link href="/login" className="underline">
              Sign in
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
