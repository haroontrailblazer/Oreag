"use client"

import { useEffect, useState } from "react"

import { LoaderOne } from "@/components/ui/loader"
import { onSessionExpired } from "@/lib/api"

/**
 * Covers the app while a signed-out session is being bounced to /login.
 *
 * Without it the user saw the backend's own words - "Could not load project:
 * Missing bearer token" - in red at the top of the page. That is a message for
 * whoever is holding a debugger; the person reading it had simply been signed
 * out, usually by signing out on another device. The state is transient and
 * already being handled, so the honest UI is "working on it", not an error.
 *
 * Mounted once in the dashboard layout rather than per page: `api()` is called
 * from loaders, event handlers and SWR internals alike, and any of them can be
 * the first to notice.
 */
export function SessionExpiredOverlay() {
  const [expired, setExpired] = useState(false)

  // Subscribe on mount, and never unsubscribe early: the redirect is a full
  // document load, so this component is torn down by the navigation itself.
  useEffect(() => onSessionExpired(() => setExpired(true)), [])

  if (!expired) return null

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-0 z-100 flex flex-col items-center justify-center gap-4 bg-background/90 backdrop-blur-sm"
    >
      <span aria-hidden="true">
        <LoaderOne />
      </span>
      <p className="text-sm text-muted-foreground">
        Your session ended - taking you to sign in…
      </p>
    </div>
  )
}
