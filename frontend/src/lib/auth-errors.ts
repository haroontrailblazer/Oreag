import type { AuthError } from "@supabase/supabase-js"

/**
 * Turn a Supabase auth error into something worth showing a person.
 *
 * Raw GoTrue messages leak implementation ("AAL2 required", "invalid flow
 * state") or are actively misleading under rate limiting ("For security
 * purposes, you can only request this after 54 seconds"). Every user-facing
 * auth surface routes through here so the wording is consistent and nobody
 * has to guess what went wrong.
 *
 * Unknown errors fall through to the raw message on purpose: a vague
 * "Something went wrong" is worse than an odd-sounding but specific one, and
 * silently swallowing an unmapped case would hide real bugs.
 */

/** Supabase caps auth emails hard, and says so in several different shapes. */
export function isRateLimited(error: unknown): boolean {
  if (!error) return false
  const status = (error as { status?: number }).status
  const code = (error as { code?: string }).code
  const message = (error as { message?: string }).message ?? ""
  return (
    status === 429 ||
    code === "over_email_send_rate_limit" ||
    code === "over_request_rate_limit" ||
    /rate limit|too many|for security purposes/i.test(message)
  )
}

/** The user typed the wrong code, as opposed to anything being broken. */
export function isBadCode(error: unknown): boolean {
  const code = (error as { code?: string })?.code
  const message = (error as { message?: string })?.message ?? ""
  return (
    code === "otp_expired" ||
    code === "invalid_credentials" ||
    /token has expired|invalid.*(token|code|otp)/i.test(message)
  )
}

/**
 * The user abandoned the WebAuthn prompt, or the browser refused it.
 *
 * This is NOT an error worth a red toast - dismissing the passkey sheet is a
 * normal thing to do, and shouting about it trains people to ignore warnings.
 * Callers should return quietly when this is true.
 */
export function isPasskeyCancellation(error: unknown): boolean {
  const name = (error as { name?: string })?.name
  return (
    name === "NotAllowedError" ||
    name === "AbortError" ||
    /aborted|not allowed|cancell?ed|timed out/i.test(
      (error as { message?: string })?.message ?? ""
    )
  )
}

const MESSAGES: Record<string, string> = {
  invalid_credentials: "That email and password don't match an account.",
  email_not_confirmed: "Confirm your email first - check your inbox.",
  otp_expired: "That code has expired. Request a new one.",
  over_email_send_rate_limit:
    "Too many emails requested. Try again in about an hour.",
  over_request_rate_limit: "Too many attempts. Wait a moment and try again.",
  same_password: "That's already your current password.",
  weak_password: "Pick a stronger password.",
  mfa_verification_failed: "That code isn't right. Check your app and retry.",
  mfa_challenge_expired: "That took too long - start again.",
  // GoTrue enforces friendly-name uniqueness per user. The UI picks a free
  // name automatically, so reaching this means something raced or an old
  // factor is holding the name.
  mfa_factor_name_conflict:
    "You already have a method with that name. Remove it first, or try again.",
  too_many_enrolled_mfa_factors:
    "You've reached the limit for authentication methods. Remove one first.",
  insufficient_aal: "Finish two-factor authentication to continue.",
  reauthentication_needed: "Confirm it's you before changing this.",
  reauthentication_not_valid: "That code isn't right. Request a new one.",
}

export function authErrorMessage(
  error: AuthError | Error | unknown,
  fallback = "Something went wrong. Please try again."
): string {
  if (!error) return fallback

  const code = (error as { code?: string }).code
  if (code && MESSAGES[code]) return MESSAGES[code]

  // Rate limiting is checked after the code map so a specific message wins.
  if (isRateLimited(error)) {
    return "Too many requests. Please wait a little and try again."
  }

  const message = (error as { message?: string }).message
  return message && message.trim() ? message : fallback
}
