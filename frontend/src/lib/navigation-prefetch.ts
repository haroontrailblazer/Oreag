export const DASHBOARD_ROUTES = [
  "/dashboard", "/query-explorer", "/knowledge-health", "/knowledge-gaps",
  "/settings/usage", "/settings/api-keys", "/projects/new",
  "/query-explorer?view=failures", "/settings/profile", "/settings/report-key-issue",
] as const

/** Prepare a small working set; larger accounts warm other projects on intent. */
export function dashboardBackgroundTargets(projectPaths: readonly string[], currentPath: string) {
  return [...DASHBOARD_ROUTES, ...projectPaths.filter(path => path !== currentPath).slice(0, 3)]
}

/** Only application pages, never auth actions, API endpoints or external URLs. */
export function dashboardPrefetchTarget(href: string, origin: string, projectIds: readonly string[]) {
  let url: URL
  try { url = new URL(href, origin) } catch { return null }
  if (url.origin !== origin) return null
  const projectPath = projectIds.some((id) => url.pathname === `/projects/${encodeURIComponent(id)}`)
  if (!DASHBOARD_ROUTES.some(href => href.split("?")[0] === url.pathname) && !projectPath) return null
  return url.pathname + url.search
}

type QueueOptions = {
  run: (href: string, intent: boolean) => Promise<boolean>
  schedule: (callback: () => void) => () => void
  paused: () => boolean
  now?: () => number
  freshForMs?: number
}

/** One idle background job and one reserved, immediate intent slot. A slow
 * background request must never make the link under the pointer wait for it. */
export function createNavigationPrefetchQueue({ run, schedule, paused, now = Date.now, freshForMs = 30_000 }: QueueOptions) {
  const pending = new Map<string, boolean>()
  const completed = new Map<string, number>()
  const active = new Map<string, boolean>()
  let cancel: (() => void) | undefined
  let disposed = false

  function start(href: string, intent: boolean) {
    pending.delete(href)
    active.set(href, intent)
    void Promise.resolve().then(() => disposed || paused() ? false : run(href, intent)).then((success) => {
      if (success && !disposed) completed.set(href, now())
    }).catch(() => {
      // Speculation must never surface as a page failure.
    }).finally(() => {
      active.delete(href)
      pump()
    })
  }

  function pump() {
    if (disposed || paused()) return
    const nextIntent = [...pending].find(([, intent]) => intent)
    if (nextIntent && ![...active.values()].includes(true)) start(nextIntent[0], true)
    if (cancel || [...active.values()].includes(false) || ![...pending.values()].includes(false)) return
    cancel = schedule(() => {
      cancel = undefined
      if (disposed || paused()) return
      const next = [...pending].find(([, intent]) => !intent)
      if (!next) return
      start(next[0], false)
    })
  }

  return {
    enqueue(href: string, intent = false) {
      if (disposed || active.has(href)) return
      const last = completed.get(href)
      if (last != null && now() - last < freshForMs) return
      pending.set(href, intent || pending.get(href) || false)
      pump()
    },
    resume: pump,
    invalidate(href: string) { completed.delete(href) },
    dispose() {
      disposed = true
      cancel?.()
      pending.clear()
    },
  }
}
