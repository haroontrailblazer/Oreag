"use client"

import { X } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { AuthShell } from "@/components/auth-shell"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { PasswordInput } from "@/components/ui/password-input"
import { passwordFailures } from "@/lib/password"
import { createClient } from "@/lib/supabase/client"

export default function ResetPasswordPage() {
  const router = useRouter()
  const [ready, setReady] = useState(false)
  const [hasSession, setHasSession] = useState(false)
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [attempted, setAttempted] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    createClient()
      .auth.getSession()
      .then(({ data }) => {
        setHasSession(!!data.session)
        setReady(true)
      })
  }, [])

  const failing = passwordFailures(password)
  const mismatch = password !== confirm

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (failing.length > 0 || mismatch) {
      setAttempted(true)
      return
    }
    setLoading(true)
    const { error } = await createClient().auth.updateUser({ password })
    setLoading(false)
    if (error) {
      toast.error(error.message)
      return
    }
    toast.success("Password updated — you're signed in")
    router.push("/dashboard")
    router.refresh()
  }

  return (
    <AuthShell>
      {!ready ? (
        <p className="text-center text-sm text-muted-foreground">Loading…</p>
      ) : !hasSession ? (
        <div className="space-y-4 text-center">
          <p className="text-sm">
            This password reset link is invalid or has expired.
          </p>
          <Button asChild className="w-full">
            <Link href="/login">Back to login</Link>
          </Button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1 text-center">
            <h2 className="text-base font-semibold">Set a new password</h2>
            <p className="text-sm text-muted-foreground">
              Choose a new password for your account.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-password">New password</Label>
            <PasswordInput
              id="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="bg-muted/50"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm-password">Confirm password</Label>
            <PasswordInput
              id="confirm-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="bg-muted/50"
            />
          </div>
          {attempted && (failing.length > 0 || mismatch) && (
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
                {mismatch && (
                  <li className="flex items-center gap-1.5 text-xs text-destructive">
                    <X className="size-3.5 shrink-0" />
                    Passwords must match
                  </li>
                )}
              </ul>
            </div>
          )}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? "Updating…" : "Update password"}
          </Button>
        </form>
      )}
    </AuthShell>
  )
}
