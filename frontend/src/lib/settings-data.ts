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

export const PASSKEYS_KEY = "auth:passkeys"
export const TOTP_KEY = "auth:totp"
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
  preload(RECOVERY_KEY, fetchRecoveryCount)
}
