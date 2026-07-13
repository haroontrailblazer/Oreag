import { createClient } from "@supabase/supabase-js"
import { NextResponse } from "next/server"

/**
 * Identifier-first login helper. Reports which sign-in methods an email has
 * (password and/or which OAuth providers) so the login page can route the user
 * to the right step. Runs in the always-on Next.js app (not the FastAPI
 * backend, which sleeps) via the SECURITY DEFINER `auth_methods_for_email`
 * RPC, called with the service-role key that never reaches the browser.
 *
 * When the service key isn't configured this returns 503 so the login page
 * degrades to showing the password field - the feature "activates" once the
 * key + migration 0017 are in place, and nothing breaks in the meantime.
 */
export const runtime = "nodejs"

// Best-effort per-IP limiter (a single warm instance). Enough to blunt casual
// enumeration; harden with Upstash if you need cross-instance guarantees.
const hits = new Map<string, number>()
function rateLimited(ip: string, limit = 30): boolean {
  const now = Math.floor(Date.now() / 1000)
  const key = `${ip}:${now - (now % 60)}`
  const count = (hits.get(key) ?? 0) + 1
  hits.set(key, count)
  if (hits.size > 5000) {
    const keep = `:${now - (now % 60)}`
    for (const k of hits.keys()) if (!k.endsWith(keep)) hits.delete(k)
  }
  return count > limit
}

export async function POST(request: Request) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY
  if (!url || !serviceKey) {
    return NextResponse.json({ error: "not-configured" }, { status: 503 })
  }

  const ip =
    (request.headers.get("x-forwarded-for") ?? "").split(",")[0].trim() ||
    "unknown"
  if (rateLimited(ip)) {
    return NextResponse.json({ error: "rate-limited" }, { status: 429 })
  }

  let email = ""
  try {
    email = String(((await request.json()) as { email?: unknown }).email ?? "")
      .trim()
      .toLowerCase()
  } catch {
    return NextResponse.json({ error: "bad-request" }, { status: 400 })
  }
  if (email.length < 3) {
    return NextResponse.json({ error: "invalid-email" }, { status: 422 })
  }

  const supabase = createClient(url, serviceKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  })
  const { data, error } = await supabase.rpc("auth_methods_for_email", {
    p_email: email,
  })
  if (error) {
    return NextResponse.json({ error: "lookup-failed" }, { status: 503 })
  }
  // data = { exists, has_password, providers }
  return NextResponse.json(data)
}
