import { createServerClient } from "@supabase/ssr"
import type { EmailOtpType } from "@supabase/supabase-js"
import { cookies } from "next/headers"
import { NextResponse } from "next/server"

import { STEP_UP_PATH, needsStepUp } from "@/lib/auth-step-up"

/**
 * Landing point for every link in an auth email: signup confirmation, password
 * recovery, email change.
 *
 * It accepts BOTH shapes a Supabase link can arrive in, because which one you
 * get depends on how the email template is written - and getting that wrong
 * silently breaks every link in every email:
 *
 *   ?token_hash=&type=   the template links straight here with
 *                        {{ .TokenHash }}. Preferred: verifyOtp works no
 *                        matter which browser opens the link.
 *
 *   ?code=               the template used the default {{ .ConfirmationURL }},
 *                        so the click went to Supabase's own /auth/v1/verify
 *                        first, which consumed the token and redirected here
 *                        with a PKCE code. Works, but ONLY in the browser that
 *                        started the flow - the code_verifier lives in that
 *                        browser's storage. Open it on a phone after
 *                        requesting on a laptop and it fails.
 *
 * Supporting both means the template can be improved later without a code
 * change, and a default template still works today.
 */
export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url)
  const token_hash = searchParams.get("token_hash")
  const type = searchParams.get("type") as EmailOtpType | null
  const code = searchParams.get("code")
  const nextParam = searchParams.get("next") ?? "/dashboard"
  // only allow internal redirects (no open-redirect via ?next=https://evil.com)
  const next = nextParam.startsWith("/") ? nextParam : "/dashboard"

  if (!token_hash && !code) {
    return NextResponse.redirect(`${origin}/login?error=confirmation_failed`)
  }

  const cookieStore = await cookies()
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll()
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options)
          )
        },
      },
    }
  )

  const { data, error } =
    token_hash && type
      ? await supabase.auth.verifyOtp({ type, token_hash })
      : await supabase.auth.exchangeCodeForSession(code as string)

  if (error) {
    // A recovery link that fails here is nearly always one of two things: it
    // was already used, or a PKCE code was opened in a different browser. The
    // code path on the login page recovers from both, so send them there
    // rather than to a dead end.
    return NextResponse.redirect(`${origin}/login?error=confirmation_failed`)
  }

  // A link sign-in never passes through the login page, so the second-factor
  // gate has to be applied here too. Otherwise the user lands on the dashboard,
  // its first API call 403s, and they get bounced - correct, but only after
  // seeing a page they had not earned yet.
  //
  // RECOVERY IS EXEMPT, deliberately. Sending a password reset through the
  // two-factor prompt would mean anyone who lost their authenticator can never
  // reset their password either - and Supabase ships no backup codes, so that
  // is a permanent, unrecoverable lockout. Nothing is given away by the
  // exemption: setting a password leaves the session at aal1, so the very next
  // API call still returns 403 and still demands the second factor before the
  // account can actually be used.
  if (type !== "recovery" && needsStepUp(data.session)) {
    return NextResponse.redirect(`${origin}${STEP_UP_PATH}`)
  }

  return NextResponse.redirect(`${origin}${next}`)
}
