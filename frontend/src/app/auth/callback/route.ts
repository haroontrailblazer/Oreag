import { createServerClient } from "@supabase/ssr"
import { cookies } from "next/headers"
import { NextResponse } from "next/server"

import { STEP_UP_PATH, needsStepUp } from "@/lib/auth-step-up"

/**
 * Closes the OAuth popup and tells the tab that opened it how it went.
 *
 * Returned instead of a redirect when the flow ran in a popup, so the provider's
 * consent and account-chooser pages stay in the POPUP's history and never enter
 * the main tab's. That is what stops Back, after signing in with Google or
 * GitHub, landing on the account chooser.
 *
 * `postMessage` is targeted at this exact origin - never "*" - so nothing else
 * embedding the page can read the result. If there is no opener (the popup was
 * detached, or someone opened this URL directly) it falls back to navigating
 * normally, so the flow still completes rather than leaving a blank window.
 */
function popupResult(origin: string, ok: boolean, next: string): Response {
  const payload = JSON.stringify({ type: "oreag-oauth", ok })
  const fallback = JSON.stringify(ok ? next : "/login?error=oauth_failed")
  return new Response(
    `<!doctype html><meta charset="utf-8"><title>Signing you in…</title>
<body style="font:14px system-ui;padding:2rem;color:#666">Signing you in…</body>
<script>
  (function () {
    var payload = ${payload};
    try {
      if (window.opener && !window.opener.closed) {
        window.opener.postMessage(payload, ${JSON.stringify(origin)});
        window.close();
        return;
      }
    } catch (e) {}
    window.location.replace(${fallback});
  })();
</script>`,
    { headers: { "content-type": "text/html; charset=utf-8" } }
  )
}

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url)
  const code = searchParams.get("code")
  const popup = searchParams.get("popup") === "1"
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
      const destination = needsStepUp(data.session) ? STEP_UP_PATH : next
      if (popup) return popupResult(origin, true, destination)
      return NextResponse.redirect(`${origin}${destination}`)
    }
  }
  if (popup) return popupResult(origin, false, next)
  return NextResponse.redirect(`${origin}/login`)
}
