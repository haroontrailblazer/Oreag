import { createClient } from "@/lib/supabase/client"

const BACKEND_PORT = process.env.NEXT_PUBLIC_API_PORT ?? "8000"
const LOCAL_HOSTS = ["localhost", "127.0.0.1"]

/**
 * Resolve the FastAPI base URL.
 *
 * - Honors NEXT_PUBLIC_API_BASE_URL when it points at a real (non-localhost)
 *   host - e.g. a deployed API domain.
 * - Otherwise follows the browser's current hostname, so the app works whether
 *   it's opened at http://localhost:3000 or http://<lan-ip>:3000. A hardcoded
 *   "localhost" would otherwise resolve to the *client's* machine over the LAN
 *   and every fetch would fail.
 */
export function getApiBase(): string {
  const explicit = process.env.NEXT_PUBLIC_API_BASE_URL?.trim()

  if (typeof window === "undefined") {
    return explicit || `http://localhost:${BACKEND_PORT}`
  }

  if (explicit) {
    try {
      const url = new URL(explicit)
      const servedFromLocalhost = LOCAL_HOSTS.includes(window.location.hostname)
      const explicitIsLocalhost = LOCAL_HOSTS.includes(url.hostname)
      // Ignore a localhost override when the page itself is served over the LAN.
      if (!(explicitIsLocalhost && !servedFromLocalhost)) return explicit
    } catch {
      return explicit
    }
  }

  return `${window.location.protocol}//${window.location.hostname}:${BACKEND_PORT}`
}

/** Backwards-compatible constant. Prefer getApiBase() in client components. */
export const API_BASE =
  typeof window !== "undefined"
    ? getApiBase()
    : process.env.NEXT_PUBLIC_API_BASE_URL?.trim() ||
      `http://localhost:${BACKEND_PORT}`

export class ApiError extends Error {
  status: number
  /** The API refused this session until a second factor is cleared. */
  mfaRequired: boolean
  constructor(status: number, message: string, mfaRequired = false) {
    super(message)
    this.status = status
    this.mfaRequired = mfaRequired
  }
  /**
   * The session is gone, not the request. Signing out on another device, an
   * expired refresh token, or a revoked session all land here.
   *
   * Callers MUST NOT render this. "Missing bearer token" is a message written
   * for whoever is holding a debugger, and it appeared at the top of the page
   * as a red error for a user whose only problem was that they were signed
   * out. A redirect to /login is already in flight by the time this is thrown,
   * so the correct UI is the loading state, not an error.
   */
  get sessionExpired() {
    return this.status === 401
  }
}

/** True when this failure means "you are signed out", not "the request failed". */
export function isSessionExpired(error: unknown): boolean {
  return error instanceof ApiError && error.sessionExpired
}

/* Anything that wants to show a "signing you out" affordance subscribes here.
   A module-level set rather than React context: `api()` is called from loaders,
   event handlers and SWR internals, none of which sit inside a provider. */
type SessionExpiredListener = () => void
const sessionExpiredListeners = new Set<SessionExpiredListener>()

export function onSessionExpired(listener: SessionExpiredListener): () => void {
  sessionExpiredListeners.add(listener)
  // Braces, not a concise body: Set.delete returns a boolean, and a useEffect
  // cleanup must return void or a destructor.
  return () => {
    sessionExpiredListeners.delete(listener)
  }
}

/**
 * Leave for /login, once.
 *
 * Same single-shot guard as the MFA bounce and for the same reason: every
 * in-flight SWR request fails together, so an unguarded redirect fires a burst
 * of them. The dead token is cleared FIRST - otherwise /login can read a stale
 * session from storage and bounce straight back to the dashboard, which reads
 * as the app ignoring the click.
 *
 * `scope: "local"` matters even here: this device's session is already void
 * server-side, and a global sign-out would take the user's OTHER devices down
 * with it - turning one expired tab into an account-wide sign-out.
 */
let redirectingToLogin = false
async function redirectToLogin() {
  if (redirectingToLogin || typeof window === "undefined") return
  redirectingToLogin = true
  for (const listener of sessionExpiredListeners) listener()
  try {
    await createClient().auth.signOut({ scope: "local" })
  } catch {
    // Already unusable - the redirect is what matters.
  }
  window.location.replace("/login")
}

/**
 * Sent by the backend with a 403 when the session is below aal2 and the
 * account has a verified factor. Read from a header rather than by matching
 * the message, so rewording the message can never break the redirect.
 */
const MFA_REQUIRED_HEADER = "x-mfa-required"

/**
 * Bounce to the two-factor step, once.
 *
 * A session in this state is valid but unusable, and every in-flight SWR
 * request will hit the same 403 - so without the guard the user gets a burst
 * of redirects. `location.assign` rather than the router: this can fire from
 * anywhere, including outside a React tree.
 */
let redirectingForMfa = false
function redirectToMfa() {
  if (redirectingForMfa || typeof window === "undefined") return
  // Already there - redirecting would reload the page under the user mid-typing.
  if (window.location.pathname === "/auth/two-factor") return
  redirectingForMfa = true
  window.location.assign("/auth/two-factor")
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const supabase = createClient()
  const {
    data: { session },
  } = await supabase.auth.getSession()

  const headers = new Headers(init?.headers)
  if (session) headers.set("Authorization", `Bearer ${session.access_token}`)
  if (init?.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json")
  }

  const res = await fetch(`${getApiBase()}${path}`, { ...init, headers })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      if (body?.detail) {
        detail =
          typeof body.detail === "string"
            ? body.detail
            : JSON.stringify(body.detail)
      }
    } catch {
      // non-JSON error body
    }
    const mfaRequired = res.headers.get(MFA_REQUIRED_HEADER) === "1"
    if (mfaRequired) redirectToMfa()
    // 401 on a dashboard route can only mean the session is gone - every
    // /api/* route requires one. Bounce rather than surface the backend's
    // wording ("Missing bearer token") to someone who is simply signed out.
    else if (res.status === 401) void redirectToLogin()
    throw new ApiError(res.status, detail, mfaRequired)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export const fetcher = <T>(path: string) => api<T>(path)

/**
 * Download a binary response to the user's disk.
 *
 * `api()` cannot be reused: it unconditionally `res.json()`s the body. This is
 * the only way to read a superseded document version, whose blobs are kept
 * precisely so history stays reachable after it leaves the index.
 */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const supabase = createClient()
  const {
    data: { session },
  } = await supabase.auth.getSession()

  const headers = new Headers()
  if (session) headers.set("Authorization", `Bearer ${session.access_token}`)

  const res = await fetch(`${getApiBase()}${path}`, { headers })
  if (!res.ok) throw new ApiError(res.status, res.statusText)

  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/**
 * POST a JSON body and consume a Server-Sent Events stream, calling `onEvent`
 * with each parsed `data:` frame. Auth mirrors {@link api}. Resolves when the
 * stream ends; rejects (ApiError) on a non-2xx response, or an AbortError when
 * `signal` fires. The caller interprets event shapes.
 */
export async function apiStream(
  path: string,
  body: unknown,
  {
    onEvent,
    signal,
  }: { onEvent: (event: unknown) => void; signal?: AbortSignal }
): Promise<void> {
  const supabase = createClient()
  const {
    data: { session },
  } = await supabase.auth.getSession()

  const headers = new Headers()
  if (session) headers.set("Authorization", `Bearer ${session.access_token}`)
  headers.set("Content-Type", "application/json")

  const res = await fetch(`${getApiBase()}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    let detail = res.statusText
    try {
      const errBody = await res.json()
      if (errBody?.detail) {
        detail =
          typeof errBody.detail === "string"
            ? errBody.detail
            : JSON.stringify(errBody.detail)
      }
    } catch {
      // non-JSON error body
    }
    // Same rule as api(): a 401 here is a dead session, not a failed stream.
    if (res.status === 401) void redirectToLogin()
    throw new ApiError(res.status, detail)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // SSE frames are separated by a blank line; each carries one `data:` line.
    let sep: number
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const dataLine = frame
        .split("\n")
        .find((line) => line.startsWith("data:"))
      if (!dataLine) continue
      const payload = dataLine.slice(5).trim()
      if (!payload) continue
      try {
        onEvent(JSON.parse(payload))
      } catch {
        // ignore a malformed frame rather than break the stream
      }
    }
  }
}

/**
 * POST a FormData body with upload-progress reporting and cancellation.
 *
 * `fetch` can't surface upload progress, so this uses XMLHttpRequest. Auth and
 * the (browser-set) multipart Content-Type mirror {@link api}.
 *
 * @param onProgress called with an integer 0–100 as bytes are sent
 * @param signal     aborts the in-flight upload (rejects with an AbortError)
 */
export async function uploadWithProgress<T>(
  path: string,
  body: FormData,
  {
    onProgress,
    signal,
  }: { onProgress?: (percent: number) => void; signal?: AbortSignal } = {}
): Promise<T> {
  const supabase = createClient()
  const {
    data: { session },
  } = await supabase.auth.getSession()

  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open("POST", `${getApiBase()}${path}`)
    if (session) {
      xhr.setRequestHeader("Authorization", `Bearer ${session.access_token}`)
    }
    // Intentionally no Content-Type - the browser sets the multipart boundary.

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress?.(Math.round((event.loaded / event.total) * 100))
      }
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        if (xhr.status === 204 || !xhr.responseText) {
          resolve(undefined as T)
          return
        }
        try {
          resolve(JSON.parse(xhr.responseText) as T)
        } catch {
          resolve(undefined as T)
        }
        return
      }
      let detail = xhr.statusText
      try {
        const parsed = JSON.parse(xhr.responseText)
        if (parsed?.detail) {
          detail =
            typeof parsed.detail === "string"
              ? parsed.detail
              : JSON.stringify(parsed.detail)
        }
      } catch {
        // non-JSON error body
      }
      reject(new ApiError(xhr.status, detail))
    }

    xhr.onerror = () => reject(new ApiError(0, "Network error during upload"))
    xhr.onabort = () =>
      reject(new DOMException("Upload aborted", "AbortError"))

    if (signal) {
      if (signal.aborted) {
        xhr.abort()
        return
      }
      signal.addEventListener("abort", () => xhr.abort(), { once: true })
    }

    xhr.send(body)
  })
}
