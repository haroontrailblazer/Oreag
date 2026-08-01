import type { Session } from "@supabase/supabase-js"

/** Where a session that still owes a second factor must be sent. */
export const STEP_UP_PATH = "/auth/two-factor"

/**
 * Read the `aal` (authenticator assurance level) claim out of an access token.
 *
 * Decode only - the signature is NOT checked here, and that is fine because
 * this is used to decide which page to show, never to grant access. The
 * authority is `backend/app/auth/jwt.py`, which verifies the signature and
 * refuses an under-levelled token outright. If this function were somehow
 * fooled, the worst outcome is a user routed to the wrong page and then
 * corrected by the API.
 */
function readAal(accessToken: string): string | null {
  try {
    const payload = accessToken.split(".")[1]
    if (!payload) return null
    // base64url -> base64, then pad. atob rejects the URL-safe alphabet.
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/")
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4)
    const json = JSON.parse(
      typeof atob === "function"
        ? atob(padded)
        : Buffer.from(padded, "base64").toString("utf8")
    )
    return typeof json.aal === "string" ? json.aal : null
  } catch {
    return null
  }
}

/**
 * Whether this freshly established session still owes a second factor.
 *
 * Needed because the email-link and OAuth routes are SERVER handlers: they
 * establish a session and redirect, never touching the client-side gate on the
 * login page. Without this check a user with two-factor enabled who clicks a
 * magic link lands on the dashboard, whose first API call returns 403, which
 * bounces them to the step-up page - correct in the end, but only after a
 * flash of a page they were never entitled to see.
 *
 * Deliberately conservative: if the token cannot be read, assume no step-up is
 * required and let the API be the judge. Guessing "yes" here would strand
 * users who have no second factor at all.
 */
export function needsStepUp(session: Session | null | undefined): boolean {
  if (!session?.access_token) return false
  const verified = (session.user?.factors ?? []).filter(
    (factor) => factor.status === "verified"
  )
  if (verified.length === 0) return false
  return readAal(session.access_token) !== "aal2"
}
