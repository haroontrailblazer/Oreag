/**
 * Which backend this build sends requests to.
 *
 * NEXT_PUBLIC_API_BASE_URL is inlined at build time and stored on Vercel as a
 * sensitive variable, whose value the Vercel API will not return. The Render
 * failover job (scripts/render_failover.py) reads it here to tell whether the
 * live build already points at the account that is serving. The value is not
 * a secret: every client bundle contains it.
 */
export function GET() {
  return Response.json(
    { apiBase: process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || null },
    { headers: { "Cache-Control": "no-store" } }
  )
}
