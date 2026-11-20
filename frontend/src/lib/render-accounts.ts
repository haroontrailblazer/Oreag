/**
 * The Render accounts Oreag runs on, highest priority first.
 *
 * Render gives each account 750 free instance hours a month. When they run
 * out, Render suspends every free service in that account until the 1st of the
 * next month, when they come back on their own. Oreag runs identical copies of
 * the backend and the MCP server (same database, same keys) on two accounts:
 * Hexra serves whenever it is up, and the standby serves only while Hexra is
 * down. Nothing has to be switched by hand in either direction.
 *
 * Everything that needs a backend asks activeAccount():
 *   - the browser, through /api/active-backend (lib/api.ts)
 *   - the Python and JavaScript SDKs, through the same endpoint
 *   - the MCP connector proxy (app/mcp/projects/[projectId]/mcp), directly
 *
 * Server-only: it probes Render from the always-on Vercel app.
 */

export interface RenderAccount {
  name: string
  api: string
  mcp: string
}

export const ACCOUNTS: readonly RenderAccount[] = [
  {
    name: "hexra",
    api: "https://oreag.onrender.com",
    mcp: "https://oreag-1.onrender.com",
  },
  {
    name: "standby",
    api: "https://oreag-tpsy.onrender.com",
    mcp: "https://oreag-mcp.onrender.com",
  },
]

/** Render's answer for any service in a suspended account. */
export function isSuspended(response: Response): boolean {
  return (
    response.status === 503 &&
    /suspend/i.test(response.headers.get("x-render-routing") ?? "")
  )
}

type State = "up" | "suspended" | "unreachable"

// A suspended account answers at once. A sleeping free instance instead holds
// the request while it boots, which takes up to about a minute, so a probe that
// times out is reported as waking up, not as gone.
const PROBE_TIMEOUT_MS = 4_000

async function probe(account: RenderAccount): Promise<State> {
  try {
    const response = await fetch(`${account.api}/healthz`, {
      cache: "no-store",
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    })
    if (isSuspended(response)) return "suspended"
    await response.body?.cancel()
    return response.ok ? "up" : "unreachable"
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      return "up"
    }
    return "unreachable"
  }
}

async function pick(): Promise<RenderAccount> {
  let fallback: RenderAccount | undefined
  for (const account of ACCOUNTS) {
    const state = await probe(account)
    if (state === "up") return account
    if (state === "unreachable") fallback ??= account
  }
  // Nothing answered. An unreachable account may recover; a suspended one
  // will not before the month ends.
  return fallback ?? ACCOUNTS[0]
}

// Short enough that a switch reaches callers within seconds, long enough that
// busy traffic costs one probe per instance every few seconds, not one per
// request. Accounts are probed in order and the search stops at the first that
// answers, so the standby is never woken while Hexra serves.
const CACHE_MS = 15_000
let cached: { account: RenderAccount; at: number } | null = null
let pending: Promise<RenderAccount> | null = null

export function activeAccount(): Promise<RenderAccount> {
  if (cached && Date.now() - cached.at < CACHE_MS) {
    return Promise.resolve(cached.account)
  }
  pending ??= pick()
    .then((account) => {
      cached = { account, at: Date.now() }
      return account
    })
    .finally(() => {
      pending = null
    })
  return pending
}

/** Forget the cached answer, after an account turned out to be suspended. */
export function forgetActiveAccount(): void {
  cached = null
}
