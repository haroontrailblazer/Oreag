import { activeAccount } from "@/lib/render-accounts"

/**
 * Which Render account is serving right now (see lib/render-accounts.ts).
 *
 * The browser (lib/api.ts) and both SDKs ask here before calling the backend,
 * so a switch between accounts needs no redeploy and no client change. The
 * answer is public, the same URLs every client bundle already contains, so any
 * origin may read it, and the CDN may hold it for a few seconds.
 */
export async function GET() {
  const account = await activeAccount()
  return Response.json(
    { account: account.name, apiBase: account.api, mcpBase: account.mcp },
    {
      headers: {
        "Cache-Control": "public, max-age=0, s-maxage=15, stale-while-revalidate=15",
        "Access-Control-Allow-Origin": "*",
      },
    }
  )
}
