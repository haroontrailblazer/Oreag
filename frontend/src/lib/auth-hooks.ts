"use client"

import { useCallback, useEffect, useRef, useState } from "react"

/**
 * Resend-with-cooldown state machine.
 *
 * Every "send me a code" button in the app shares this, because Supabase caps
 * auth emails aggressively and a double-tap burns the quota for an hour. The
 * existing login page already hand-rolled a three-state guard for exactly this
 * reason; this generalises it and adds the visible countdown people need in
 * order to not keep tapping.
 */
export function useResendCooldown(seconds = 45) {
  const [remaining, setRemaining] = useState(0)
  const [sending, setSending] = useState(false)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    return () => {
      if (timer.current) clearInterval(timer.current)
    }
  }, [])

  const start = useCallback(() => {
    setRemaining(seconds)
    if (timer.current) clearInterval(timer.current)
    timer.current = setInterval(() => {
      setRemaining((r) => {
        if (r <= 1 && timer.current) {
          clearInterval(timer.current)
          timer.current = null
        }
        return Math.max(0, r - 1)
      })
    }, 1000)
  }, [seconds])

  /**
   * Wraps a send. Returns true when the send succeeded, so callers can advance
   * a step. The cooldown starts only on success - a failed send must not lock
   * the user out of retrying.
   */
  const send = useCallback(
    async (fn: () => Promise<boolean>) => {
      if (sending || remaining > 0) return false
      setSending(true)
      try {
        const ok = await fn()
        if (ok) start()
        return ok
      } finally {
        setSending(false)
      }
    },
    [sending, remaining, start]
  )

  const label = sending
    ? "Sending…"
    : remaining > 0
      ? `Resend in ${remaining}s`
      : "Resend code"

  return { send, sending, remaining, label, blocked: sending || remaining > 0 }
}

/**
 * Whether this browser can do WebAuthn at all.
 *
 * Returns null while unknown (SSR and first paint) so callers can render
 * nothing rather than flashing a passkey button that then disappears. A dead
 * "Continue with passkey" button is worse than no button.
 */
export function usePasskeySupport(): boolean | null {
  const [supported, setSupported] = useState<boolean | null>(null)

  useEffect(() => {
    let alive = true

    // Resolved through a promise rather than assigned in the effect body: this
    // is external state being read, and a synchronous setState here is both a
    // cascading render and a lint error.
    const probe = async () => {
      const hasApi =
        typeof window !== "undefined" &&
        typeof window.PublicKeyCredential !== "undefined" &&
        typeof navigator?.credentials?.get === "function"
      if (!hasApi) return false
      try {
        // Having the API is not the same as having a usable authenticator.
        // Advisory only: this resolves false on a desktop with no platform
        // authenticator but a perfectly good security key or phone, so a false
        // answer still permits sign-in - it only stops us leading with it.
        const available =
          await window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable?.()
        return Boolean(available)
      } catch {
        return true // the API exists; let the user try
      }
    }

    probe().then((result) => {
      if (alive) setSupported(result)
    })

    return () => {
      alive = false
    }
  }, [])

  return supported
}
