import {
  ACCOUNTS,
  activeAccount,
  forgetActiveAccount,
  isSuspended,
} from "@/lib/render-accounts"

/**
 * Stable MCP connector URL: /mcp/projects/<project-id>/mcp
 *
 * The MCP server runs on two Render accounts, because one account's free hours
 * run out mid-month (see lib/render-accounts.ts). An MCP client stores a single
 * URL, so rather than pointing clients at either account, this route forwards
 * each request to the account that is serving, and to the other one if Render
 * answers that the first is suspended or it cannot be reached. No redeploy and
 * no client change is needed when the accounts switch, in either direction.
 *
 * Only this path shape is forwarded, and only to these fixed hosts, so the
 * route cannot be pointed anywhere else. The caller's
 * `Authorization: Bearer <key>` passes through untouched; the MCP server and
 * the backend check it, not this route.
 */

export const runtime = "nodejs"

// A sleeping free Render instance takes up to a minute to boot before it
// answers, and a tool call such as ask_docs can take a while after that.
export const maxDuration = 300

const REQUEST_HEADERS = [
  "authorization",
  "content-type",
  "accept",
  "mcp-protocol-version",
  "mcp-session-id",
  "last-event-id",
]

// Not content-length or content-encoding: fetch has already decoded the body,
// so the upstream's values would describe bytes this response does not carry.
const RESPONSE_HEADERS = [
  "content-type",
  "cache-control",
  "mcp-session-id",
  "mcp-protocol-version",
  "www-authenticate",
]

function pick(from: Headers, names: string[]): Headers {
  const picked = new Headers()
  for (const name of names) {
    const value = from.get(name)
    if (value !== null) picked.set(name, value)
  }
  return picked
}

async function forward(
  request: Request,
  { params }: { params: Promise<{ projectId: string }> }
): Promise<Response> {
  const { projectId } = await params
  const body =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.arrayBuffer()
  const headers = pick(request.headers, REQUEST_HEADERS)

  const serving = await activeAccount()
  const upstreams = [serving, ...ACCOUNTS.filter((a) => a !== serving)].map(
    (account) => account.mcp
  )

  for (const base of upstreams) {
    let upstream: Response
    try {
      upstream = await fetch(
        `${base}/projects/${encodeURIComponent(projectId)}/mcp`,
        {
          method: request.method,
          headers,
          body,
          redirect: "manual",
          cache: "no-store",
          signal: request.signal,
        }
      )
    } catch (error) {
      if (request.signal.aborted) throw error
      forgetActiveAccount()
      continue // unreachable: try the next account
    }

    // Any other answer, errors included, is the real one. Retrying a failed
    // tool call on the other account could run it twice.
    if (isSuspended(upstream)) {
      await upstream.body?.cancel()
      forgetActiveAccount()
      continue
    }

    const responseHeaders = pick(upstream.headers, RESPONSE_HEADERS)
    responseHeaders.set("x-oreag-upstream", new URL(base).host)
    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    })
  }

  return Response.json(
    { error: "No Oreag MCP server is available right now. Try again shortly." },
    { status: 503 }
  )
}

export const GET = forward
export const POST = forward
export const DELETE = forward
