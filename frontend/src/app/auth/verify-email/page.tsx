"use client"

import { EnvelopeSimpleIcon as EnvelopeSimple } from "@phosphor-icons/react/dist/ssr"
import { useRouter } from "next/navigation"
import { useCallback, useEffect, useRef, useState } from "react"

import { AuthShell } from "@/components/auth-shell"
import { OtpField, isCompleteCode } from "@/components/auth/otp-field"
import { Button } from "@/components/ui/button"
import { Spin } from "@/components/ui/loader"
import { authErrorMessage, isBadCode } from "@/lib/auth-errors"
import { useResendCooldown } from "@/lib/auth-hooks"
import { createClient } from "@/lib/supabase/client"
import { toast } from "@/lib/toast"

const OTP_LENGTH = Number(process.env.NEXT_PUBLIC_OTP_LENGTH) || 6

/**
 * Confirm control of the mailbox before a session is usable.
 *
 * Reached when the account has NO second factor and the session was minted
 * from a password or an OAuth provider alone - neither of which proves the
 * person signing in can read the address on file. A password is a shared
 * secret that leaks in breaches; Google/GitHub prove the provider account
 * rather than this mailbox.
 *
 * Both the middleware (src/proxy.ts) and the API 403
 * (`X-Email-Verification-Required`) route here, so this page MUST exist for
 * every one of those users - it is the only way out of that state, and its
 * absence is a 404 the user cannot navigate away from.
 *
 * Not a login page. The user IS signed in; the session is simply unfinished,
 * so signing them out would discard the thing they are here to complete.
 */
export default function VerifyEmailPage() {
  const router = useRouter()
  const supabase = createClient()
  const resend = useResendCooldown()

  const [email, setEmail] = useState<string | null>(null)
  const [code, setCode] = useState("")
  const [invalid, setInvalid] = useState(false)
  const [loading, setLoading] = useState(false)
  // A ref, not state: this only guards against sending twice, and nothing
  // renders from it. As state it would be a setState inside an effect, which
  // is both a lint error and an extra render for no visible change.
  const autoSent = useRef(false)

  const send = useCallback(
    async (to: string | null) => {
      if (!to) return
      await resend.send(async () => {
        const { error } = await supabase.auth.signInWithOtp({
          email: to,
          // Never create an account from here - this address already has one.
          options: { shouldCreateUser: false },
        })
        if (error) {
          toast.error(authErrorMessage(error))
          return false
        }
        return true
      })
    },
    [resend, supabase]
  )

  // Latest `send` without making it an effect dependency. `resend` changes
  // identity every time its countdown ticks, so depending on it directly would
  // re-run the session lookup once a second.
  //
  // Assigned in an effect, never during render: a render can be thrown away or
  // replayed, and a ref written there would carry a value from a render that
  // never committed.
  const sendRef = useRef(send)
  useEffect(() => {
    sendRef.current = send
  }, [send])

  // Read the address off the session rather than asking for it - they are
  // already signed in, so retyping it would be theatre, and a typo would send
  // the code to an address they do not control. The first code goes out from
  // here too, so the common path is "open page, read code" rather than "open
  // page, hunt for a button".
  useEffect(() => {
    let alive = true
    void supabase.auth.getSession().then(({ data }) => {
      if (!alive) return
      const address = data.session?.user.email ?? null
      setEmail(address)
      if (address && !autoSent.current) {
        autoSent.current = true
        void sendRef.current(address)
      }
    })
    return () => {
      alive = false
    }
  }, [supabase])

  const verify = useCallback(
    async (value: string) => {
      if (!email || loading) return
      setLoading(true)
      setInvalid(false)
      const { error } = await supabase.auth.verifyOtp({
        email,
        token: value,
        type: "email",
      })
      if (error) {
        setLoading(false)
        setInvalid(true)
        setCode("")
        toast.error(
          isBadCode(error)
            ? "That code isn't right."
            : authErrorMessage(error, "Could not confirm that code.")
        )
        return
      }
      // The new session carries `otp` in its amr, which is what the middleware
      // and the backend both read. A HARD navigation: SWR caches are holding
      // 403s from before this step, and a full load is the only reliable way
      // to drop them. replace, not assign - Back must not return here.
      window.location.replace("/dashboard")
    },
    [email, loading, supabase]
  )

  return (
    <AuthShell
      title="Confirm it's you"
      subtitle={
        email
          ? `We sent a ${OTP_LENGTH}-digit code to ${email}`
          : "Loading your account…"
      }
      keyboardStable
    >
      <div className="space-y-5">
        <div className="flex justify-center">
          <span className="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
            <EnvelopeSimple weight="duotone" className="size-6" />
          </span>
        </div>

        <OtpField
          value={code}
          onChange={setCode}
          onComplete={verify}
          disabled={loading || !email}
          invalid={invalid}
          label="Confirmation code"
          length={OTP_LENGTH}
        />

        <Button
          type="button"
          className="h-11 w-full gap-1.5 rounded-xl text-[15px] sm:h-12"
          disabled={!isCompleteCode(code, OTP_LENGTH) || loading}
          onClick={() => verify(code)}
        >
          {loading ? (
            <span className="inline-flex items-center gap-2">
              Confirming
              <Spin />
            </span>
          ) : (
            "Confirm"
          )}
        </Button>

        <div className="flex items-center justify-center gap-3 text-xs text-muted-foreground">
          <button
            type="button"
            onClick={() => send(email)}
            disabled={resend.blocked || !email}
            className="font-medium underline-offset-2 hover:text-foreground hover:underline disabled:cursor-not-allowed disabled:opacity-50 disabled:no-underline"
          >
            {resend.label}
          </button>
          <span aria-hidden="true">·</span>
          {/* Local scope: this device only. A global sign-out here would take
              their other devices down for what is a routine step. */}
          <button
            type="button"
            onClick={async () => {
              await supabase.auth.signOut({ scope: "local" })
              router.replace("/login")
            }}
            className="font-medium underline-offset-2 hover:text-foreground hover:underline"
          >
            Use a different account
          </button>
        </div>
      </div>
    </AuthShell>
  )
}
