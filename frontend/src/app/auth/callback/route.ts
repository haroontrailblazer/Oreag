import { createServerClient } from "@supabase/ssr"
import { cookies } from "next/headers"
import { NextResponse } from "next/server"

import { STEP_UP_PATH, needsStepUp } from "@/lib/auth-step-up"

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url)
  const code = searchParams.get("code")
  const nextParam = searchParams.get("next") ?? "/dashboard"
  // only allow internal redirects (no open-redirect via ?next=https://evil.com)
  const next = nextParam.startsWith("/") ? nextParam : "/dashboard"

  if (code) {
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
    const { data, error } = await supabase.auth.exchangeCodeForSession(code)
    if (!error) {
      // Same reasoning as /auth/confirm: an OAuth round trip bypasses the
      // login page's gate entirely, so it is enforced here as well.
      if (needsStepUp(data.session)) {
        return NextResponse.redirect(`${origin}${STEP_UP_PATH}`)
      }
      return NextResponse.redirect(`${origin}${next}`)
    }
  }
  return NextResponse.redirect(`${origin}/login`)
}
