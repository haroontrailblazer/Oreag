import { createServerClient } from "@supabase/ssr"
import { NextResponse, type NextRequest } from "next/server"

const PUBLIC_PATHS = ["/", "/docs", "/login", "/signup", "/auth/callback"]

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

  // refreshes the session cookie if expired — do not remove
  const {
    data: { user },
  } = await supabase.auth.getUser()

  const path = request.nextUrl.pathname
  const isPublic = PUBLIC_PATHS.includes(path)

  if (!user && !isPublic) {
    return NextResponse.redirect(new URL("/login", request.url))
  }
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
    // /login — which is why the OG preview image never loaded.
    "/((?!_next/static|_next/image|favicon.ico|opengraph-image|twitter-image|icon|apple-icon|sitemap\\.xml|robots\\.txt|manifest\\.webmanifest|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
}
