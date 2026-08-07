/**
 * Reading the `amr` claim - which sign-in methods minted a session.
 *
 * DELIBERATELY runtime-neutral: no "use client", no imports, no browser or Node
 * globals. This module is pulled into the EDGE MIDDLEWARE bundle (src/proxy.ts)
 * as well as into client components, and middleware cannot take a dependency on
 * a "use client" module - doing so is what turned every signed-in page into an
 * Internal Server Error while the public pages stayed fine, because the branch
 * that imports it only runs for an authenticated request.
 *
 * Keep it that way: if this ever needs a Supabase client, it belongs elsewhere.
 */

/**
 * Sign-in methods that prove only "knows a secret" or "has a linked account".
 *
 * MUST match `_WEAK_AMR_METHODS` in backend/app/auth/jwt.py. The backend is the
 * enforcer; this copy exists so the middleware can redirect BEFORE a protected
 * page renders and shows a 403 the user did nothing to cause. If the two ever
 * disagree the backend wins, and the user sees an error rather than a redirect -
 * annoying, never insecure.
 */
export const WEAK_AMR_METHODS = new Set([
  "password",
  "oauth",
  "sso/saml",
  "web3",
  "anonymous",
])

/**
 * Did this session use a method stronger than password/OAuth alone?
 *
 * Fails OPEN on a missing or unreadable claim, exactly as the backend does: the
 * cost of the two failure modes is wildly asymmetric, and locking every user
 * out over an unexpected token shape is far worse than one skipped email.
 */
export function provedEmailControl(amr: unknown): boolean {
  if (!Array.isArray(amr) || amr.length === 0) return true
  const methods = new Set<string>()
  for (const entry of amr) {
    if (typeof entry === "string") methods.add(entry)
    else if (entry && typeof entry === "object" && "method" in entry) {
      const m = (entry as { method?: unknown }).method
      if (typeof m === "string") methods.add(m)
    }
  }
  if (methods.size === 0) return true
  return [...methods].some((m) => !WEAK_AMR_METHODS.has(m))
}
