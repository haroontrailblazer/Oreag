"use client"

import type { SupabaseClient } from "@supabase/supabase-js"

/**
 * Second factors, as the sign-in gate needs to see them.
 *
 * THE DISTINCTION THAT MATTERS, because Supabase has two passkey mechanisms
 * that look identical to a user and are not remotely the same thing:
 *
 *   - `auth.webauthn_credentials` - a LOGIN passkey, registered with
 *     `registerPasskey()`. It signs in on its own and lands directly at aal2.
 *     It is NOT a factor: it never appears in `listFactors()`, it does not
 *     raise `nextLevel`, and `user_has_verified_mfa()` (migration 0019) cannot
 *     see it.
 *   - `auth.mfa_factors` with `factor_type = 'webauthn'` - a SECOND factor,
 *     enrolled with `auth.webauthn.register()`. This is the one the assurance
 *     level and the backend both understand.
 *
 * Gating on the first would have been theatre: `signInWithPassword` already
 * returns a fully valid session, and `backend/app/auth/jwt.py` only rejects
 * aal1 when a verified *factor* exists - so with only a login passkey the API
 * accepts the session regardless of what the UI drew. Anyone calling the API
 * directly, or closing the prompt, would be straight in.
 */
export type SecondFactors = {
  /** Verified TOTP factor, if any. */
  totp: { id: string; friendlyName: string | null } | null
  /** Verified webauthn FACTOR (not a login passkey), if any. */
  passkey: { id: string; friendlyName: string | null } | null
}

export const NO_FACTORS: SecondFactors = { totp: null, passkey: null }

/**
 * Read this account's verified second factors.
 *
 * Only `verified` counts. An abandoned enrolment leaves a `unverified` row
 * behind, and treating that as a gate would lock the user out with a factor
 * they never finished setting up.
 *
 * Returns NO_FACTORS on any error rather than throwing: the caller uses this
 * to decide what to DRAW, and the backend enforces the real rule on every
 * request. Failing closed in the UI would strand a user the server would have
 * happily let through.
 */
export async function loadSecondFactors(
  supabase: SupabaseClient
): Promise<SecondFactors> {
  try {
    const { data, error } = await supabase.auth.mfa.listFactors()
    if (error || !data) return NO_FACTORS
    const verified = (data.all ?? []).filter((f) => f.status === "verified")
    const totp = verified.find((f) => f.factor_type === "totp")
    const passkey = verified.find((f) => f.factor_type === "webauthn")
    return {
      totp: totp ? { id: totp.id, friendlyName: totp.friendly_name ?? null } : null,
      passkey: passkey
        ? { id: passkey.id, friendlyName: passkey.friendly_name ?? null }
        : null,
    }
  } catch {
    return NO_FACTORS
  }
}

/**
 * Which second factor the sign-in gate should present.
 *
 * TOTP wins when both are enrolled. That is a deliberate instruction rather
 * than a security judgement - an account holding both keeps exactly the flow it
 * had before this feature, so nobody's muscle memory breaks on an upgrade.
 */
export function preferredFactor(
  factors: SecondFactors
): "totp" | "passkey" | null {
  if (factors.totp) return "totp"
  if (factors.passkey) return "passkey"
  return null
}

/**
 * Run the passkey ceremony for a webauthn FACTOR and raise the session to aal2.
 *
 * `auth.webauthn.authenticate` performs challenge -> navigator.credentials.get
 * -> verify in one call. rpId is deliberately left unset so it defaults to the
 * current hostname: hardcoding it is how passkeys silently stop working on a
 * custom domain.
 */
export async function verifyPasskeyFactor(
  supabase: SupabaseClient,
  factorId: string
) {
  // `mfa.webauthn`, not `auth.webauthn`: WebAuthnApi hangs off GoTrueMFAApi.
  // `auth.passkey.*` is the LOGIN-passkey surface and a different table.
  const { error } = await supabase.auth.mfa.webauthn.authenticate({ factorId })
  if (error) throw error
}

/**
 * Sign-in methods that prove only "knows a secret" or "has a linked account".
 *
 * MUST match `_WEAK_AMR_METHODS` in backend/app/auth/jwt.py. The backend is the
 * enforcer; this copy exists purely so the middleware can redirect BEFORE a
 * protected page renders and shows a 403 the user did nothing to cause. If the
 * two ever disagree, the backend wins and the user sees an error instead of a
 * redirect - annoying, never insecure.
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
 * Fails OPEN on a missing or unreadable claim, exactly as the backend does -
 * see the reasoning in `_proved_email_control`. Here it matters less, because
 * the backend still refuses; a mismatch only costs a nicer redirect.
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
