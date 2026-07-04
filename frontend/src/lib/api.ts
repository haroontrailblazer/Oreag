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
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
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
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export const fetcher = <T>(path: string) => api<T>(path)

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
