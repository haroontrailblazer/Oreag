export const DASHBOARD_ROUTES = [
  "/settings/usage", "/settings/api-keys", "/projects/new",
  "/settings/profile", "/settings/report-key-issue", "/dashboard",
  "/query-explorer",
] as const

/** Only application pages, never auth actions, API endpoints or external URLs. */
export function dashboardPrefetchTarget(href: string, origin: string, projectIds: readonly string[]) {
  let url: URL
  try { url = new URL(href, origin) } catch { return null }
  if (url.origin !== origin) return null
  const projectPath = projectIds.some((id) => url.pathname === `/projects/${encodeURIComponent(id)}`)
  if (!(DASHBOARD_ROUTES as readonly string[]).includes(url.pathname) && !projectPath) return null
  return url.pathname + url.search
}

type QueueOptions = {
  run: (href: string) => Promise<boolean>
  schedule: (callback: () => void) => () => void
  paused: () => boolean
  now?: () => number
}

/** One background job at a time, with user intent jumping ahead of the queue.
 * Keep failed jobs retryable and refresh expired prefetches on the next intent
 * or navigation, without a perpetual background polling loop. */
export function createNavigationPrefetchQueue({ run, schedule, paused, now = Date.now }: QueueOptions) {
  const pending = new Map<string, boolean>()
  const completed = new Map<string, number>()
  let active: string | null = null
  let cancel: (() => void) | undefined
  let disposed = false

  function pump() {
    if (disposed || active || cancel || pending.size === 0 || paused()) return
    cancel = schedule(() => {
      cancel = undefined
      if (disposed || paused()) return
      const next = [...pending].find(([, intent]) => intent) ?? pending.entries().next().value
      if (!next) return
      const [href] = next
      pending.delete(href)
      active = href
      void run(href).then((success) => {
        if (success && !disposed) completed.set(href, now())
      }).catch(() => {
        // Speculation must never surface as a page failure.
      }).finally(() => {
        active = null
        pump()
      })
    })
  }

  return {
    enqueue(href: string, intent = false) {
      if (disposed || href === active) return
      const last = completed.get(href)
      if (last != null && now() - last < 30_000) return
      pending.set(href, intent || pending.get(href) || false)
      pump()
    },
    resume: pump,
    dispose() {
      disposed = true
      cancel?.()
      pending.clear()
    },
  }
}
