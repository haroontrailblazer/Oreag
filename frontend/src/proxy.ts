import { createServerClient } from "@supabase/ssr"

import { provedEmailControl } from "@/lib/mfa"
import { NextResponse, type NextRequest } from "next/server"

/**
 * Paths reachable WITHOUT a session.
 *
 * Every landing page named in an email link belongs here. A link is clicked by
 * someone who is, by definition, not signed in yet - that is the whole point of
 * the link - so if its target is missing from this list the middleware bounces
 * them to /login and the email appears broken. `/auth/confirm` was exactly that
 * bug: the signup and password-reset emails point at it, and without this entry
 * every link in every auth email dead-ended on the sign-in page.
 *
 * scripts/check_docs_sync.py enforces this: it extracts every `redirectTo` /
 * `emailRedirectTo` target in the source and fails the build if one is not
 * listed here.
 */
const PUBLIC_PATHS = [
  "/",
  "/email-preview/verify-email-email.html",
  "/email-preview/sign-in-code-email.html",
  "/email-preview/password-reset-email.html",
  "/docs",
  "/login",
  "/signup",
  "/auth/callback", // PKCE ?code= exchange (OAuth)
  "/auth/confirm", // token_hash links: signup confirm, password recovery
  "/auth/reset-password", // landed on after /auth/confirm; checks its own session
  "/api/auth/methods", // pre-auth identifier-first login lookup
]

/**
 * Where a session that still owes a second factor is sent.
 *
 * Excluded from the pending-2FA redirect below for the obvious reason: sending
 * the step-up page to itself is an infinite loop.
 */
const STEP_UP_PATH = "/auth/two-factor"

/**
 * Where a session with NO second factor but no proof of mailbox control is
 * sent. Excluded from its own redirect for the same loop reason as above.
 */
const VERIFY_EMAIL_PATH = "/auth/verify-email"


export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request })

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll()
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value)
          )
          response = NextResponse.next({ request })
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options)
          )
        },
      },
    }
  )

  // Establishes identity, and refreshes the session cookie if expired - do not
  // remove the call.
  //
  // getClaims(), NOT getUser(): getUser() asks the Supabase Auth server on
  // EVERY navigation, so each page load paid for a network round trip before
  // any HTML moved. getClaims() verifies the JWT signature locally with
  // WebCrypto against the cached JWKS key, which this project has because it
  // uses asymmetric signing keys (jwt_mode=jwks). It is equally trustworthy -
  // the signature is cryptographically checked, unlike a bare getSession() -
  // and it still calls getSession() internally first, so the expired-cookie
  // refresh this comment has always warned about is preserved.
  //
  // It self-heals: if the algorithm were ever symmetric, or WebCrypto were
  // unavailable, auth-js falls back to getUser() on its own.
  const { data: claimsData } = await supabase.auth.getClaims()
  const user = claimsData?.claims?.sub ? claimsData.claims : null

  const path = request.nextUrl.pathname
  const isPublic = PUBLIC_PATHS.includes(path)

  if (!user && !isPublic) {
    return NextResponse.redirect(new URL("/login", request.url))
  }

  // Send a session that still owes a second factor straight to the step-up
  // page, BEFORE any protected page renders.
  //
  // Without this the dashboard loaded, its first API call came back 403, and
  // the user read "could not load projects: two-factor authentication
  // required" before being bounced - an error for something they had done
  // nothing wrong to cause. The client-side redirect in lib/api.ts still
  // exists as a backstop for a session that lapses mid-visit, but it should
  // never be what a user actually sees.
  //
  // `aal` comes from the verified claims; whether a factor EXISTS does not,
  // so it is read from the session's user object. getSession() is a local
  // cookie read - no network - so this costs nothing on the hot path.
  if (user && !isPublic && path !== STEP_UP_PATH && claimsData?.claims?.aal !== "aal2") {
    const {
      data: { session },
    } = await supabase.auth.getSession()
    const owesSecondFactor = (session?.user?.factors ?? []).some(
      (factor) => factor.status === "verified"
    )
    if (owesSecondFactor) {
      return NextResponse.redirect(new URL(STEP_UP_PATH, request.url))
    }
    // No factor enrolled. Then the emailed code is the only step between a
    // leaked password - or a compromised Google/GitHub account - and this
    // session, so require proof of the mailbox before anything protected
    // renders. The backend refuses these sessions regardless
    // (X-Email-Verification-Required); this only decides whether the user
    // meets a form or an error.
    if (
      path !== VERIFY_EMAIL_PATH &&
      !provedEmailControl(claimsData?.claims?.amr)
    ) {
      return NextResponse.redirect(new URL(VERIFY_EMAIL_PATH, request.url))
    }
  }
  // Signed-in users have no business on the SIGN-IN pages. "/" is deliberately
  // NOT in this list: the marketing page stays readable when signed in, and
  // swaps its call to action to "Go to dashboard" instead (see app/page.tsx).
  // Redirecting it would mean a logged-in user could never read their own
  // landing page, and Back after a sign-in would have nowhere sensible to go.
  //
  // NOTE: never add /auth/two-factor here. That page is reached BY a signed-in
  // user whose session has not yet cleared its second factor; bouncing it to
  // /dashboard deadlocks the app, because the dashboard's first API call
  // returns the 403 that sent them there in the first place.
  if (user && (path === "/login" || path === "/signup")) {
    return NextResponse.redirect(new URL("/dashboard", request.url))
  }
  return response
}

export const config = {
  matcher: [
    // Skip Next internals, static assets, AND the metadata file-convention routes
    // (opengraph-image, twitter-image, icon, apple-icon, sitemap, robots,
    // manifest). Those render with NO file extension, so without listing them
    // here the auth check below redirects unauthenticated social crawlers to
    // /login - which is why the OG preview image never loaded.
    "/((?!_next/static|_next/image|favicon.ico|opengraph-image|twitter-image|icon|apple-icon|sitemap\\.xml|robots\\.txt|manifest\\.webmanifest|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
}
