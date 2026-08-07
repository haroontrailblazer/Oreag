import { preload } from "swr"

import { api, fetcher } from "@/lib/api"
import { createClient } from "@/lib/supabase/client"

/**
 * Shared SWR keys + fetchers for the Settings pages, and the warm-up that
 * fills them before the user navigates.
 *
 * These used to be inline closures inside two-factor-card.tsx, which meant
 * nothing outside that component could populate them: SWR pairs a key with
 * whatever fetcher the FIRST subscriber supplies, so a preload with a
 * different function is a different fetch. Hoisting them here is what makes
 * warming possible at all.
 */

export type Passkey = {
  id: string
  friendly_name?: string
  created_at: string
  last_used_at?: string
}

export type TotpFactor = {
  id: string
  friendly_name?: string
  created_at: string
}

/** Any second factor: `totp` or `webauthn` (a passkey used as a GATE). */
export type MfaFactor = {
  id: string
  factor_type: "totp" | "phone" | "webauthn"
  status: "verified" | "unverified"
  friendly_name?: string
  created_at: string
}

export const PASSKEYS_KEY = "auth:passkeys"
export const TOTP_KEY = "auth:totp"
export const MFA_FACTORS_KEY = "auth:mfa-factors"
export const SECURITY_PREFS_KEY = "/api/account/security-prefs"
export const RECOVERY_KEY = "auth:recovery"
export const PROVIDER_KEYS_KEY = "/api/provider-keys"

/**
 * Every one of these swallows its own failure and resolves to an empty value.
 *
 * Deliberate: a rejected promise is what SWR CACHES when preloading, so a
 * transient error during warm-up would greet the user with a broken Settings
 * page they never asked to load yet. An empty list simply renders "none set
 * up", and the component's own revalidation corrects it. Errors that matter
 * surface from the mutating actions, which do report them.
 */
export async function fetchPasskeys(): Promise<Passkey[]> {
  try {
    const { data, error } = await createClient().auth.passkey.list()
    if (error) return []
    return (data ?? []) as Passkey[]
  } catch {
    return []
  }
}

export async function fetchTotpFactors(): Promise<TotpFactor[]> {
  try {
    const { data, error } = await createClient().auth.mfa.listFactors()
    if (error) return []
    return (data?.totp ?? []) as TotpFactor[]
  } catch {
    return []
  }
}

/**
 * EVERY MFA factor, not just TOTP.
 *
 * `listFactors()` splits its response into `totp` / `phone` / `all`, and a
 * webauthn factor appears only in `all` - so the TOTP-only fetcher above is
 * blind to a passkey enrolled as a second factor. Reading `all` is what lets
 * the settings card show one honest list.
 */
export async function fetchMfaFactors(): Promise<MfaFactor[]> {
  try {
    const { data, error } = await createClient().auth.mfa.listFactors()
    if (error) return []
    return (data?.all ?? []) as MfaFactor[]
  } catch {
    return []
  }
}

export type SecurityPrefs = { two_factor_prompt: boolean }

/**
 * Whether sign-in should challenge this account's second factor.
 *
 * Defaults to TRUE on any failure, matching the backend: the value is only
 * consulted to decide whether to SKIP a prompt, so an unreadable preference
 * must never be the reason one is dropped.
 */
export async function fetchSecurityPrefs(): Promise<SecurityPrefs> {
  try {
    return await api<SecurityPrefs>(SECURITY_PREFS_KEY)
  } catch {
    return { two_factor_prompt: true }
  }
}

export async function fetchRecoveryCount(): Promise<{ remaining: number }> {
  try {
    return await api<{ remaining: number }>("/api/account/recovery-codes")
  } catch {
    return { remaining: 0 }
  }
}

/**
 * Fill the Settings caches once, on entering the dashboard.
 *
 * Settings pages are reached by a deliberate click from a sidebar that is
 * already on screen, so the fetch can happen long before the click - by which
 * point the page renders populated instead of spinning. Four requests, once
 * per session, none of them large.
 *
 * NOT Next.js route prefetching: prefetching a protected route makes the
 * middleware answer with a redirect that then gets served from the router
 * cache. This warms DATA only and never touches routing.
 */
export function warmSettingsData(): void {
  preload(PROVIDER_KEYS_KEY, fetcher)
  preload(PASSKEYS_KEY, fetchPasskeys)
  preload(TOTP_KEY, fetchTotpFactors)
  preload(MFA_FACTORS_KEY, fetchMfaFactors)
  preload(SECURITY_PREFS_KEY, fetchSecurityPrefs)
  preload(RECOVERY_KEY, fetchRecoveryCount)
}
