import { createServerClient } from "@supabase/ssr"
import type { EmailOtpType } from "@supabase/supabase-js"
import { cookies } from "next/headers"
import { NextResponse } from "next/server"

/**
 * Email-confirmation handler (signup, recovery, email-change, etc.).
 *
 * The email template links here with `token_hash` + `type` instead of relying on
 * the PKCE `?code=` flow — `verifyOtp` works regardless of which browser/device
 * opens the link, which the `/auth/callback` code flow can't guarantee.
 */
export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url)
  const token_hash = searchParams.get("token_hash")
  const type = searchParams.get("type") as EmailOtpType | null
  const nextParam = searchParams.get("next") ?? "/dashboard"
  // only allow internal redirects (no open-redirect via ?next=https://evil.com)
  const next = nextParam.startsWith("/") ? nextParam : "/dashboard"

  if (token_hash && type) {
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
    const { error } = await supabase.auth.verifyOtp({ type, token_hash })
    if (!error) {
      return NextResponse.redirect(`${origin}${next}`)
    }
  }
  return NextResponse.redirect(`${origin}/login?error=confirmation_failed`)
}
