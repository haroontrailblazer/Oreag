"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { toast } from "@/lib/toast"

import { AuthShell } from "@/components/auth-shell"
import { SetPasswordForm } from "@/components/set-password-form"
import { Button } from "@/components/ui/button"
import { createClient } from "@/lib/supabase/client"

export default function ResetPasswordPage() {
  const router = useRouter()
  const [ready, setReady] = useState(false)
  const [hasSession, setHasSession] = useState(false)

  useEffect(() => {
    createClient()
      .auth.getSession()
      .then(({ data }) => {
        setHasSession(!!data.session)
        setReady(true)
      })
  }, [])

  return (
    <AuthShell
      title="Reset password"
      subtitle="Choose a new password for your account"
    >
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
        <div className="space-y-4">
          <div className="space-y-1 text-center">
            <h2 className="text-base font-semibold">Set a new password</h2>
            <p className="text-sm text-muted-foreground">
              Choose a new password for your account.
            </p>
          </div>
          <SetPasswordForm
            submitLabel="Update password"
            onSuccess={() => {
              toast.success("Password updated - you're signed in")
              router.push("/dashboard")
              router.refresh()
            }}
          />
        </div>
      )}
    </AuthShell>
  )
}
