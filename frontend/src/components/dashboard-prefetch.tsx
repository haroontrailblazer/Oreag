"use client"

import { useEffect, useRef } from "react"
import { usePathname, useRouter } from "next/navigation"
import { PrefetchKind } from "next/dist/client/components/router-reducer/router-reducer-types"
import useSWR, { preload, useSWRConfig } from "swr"
import type { Session } from "@supabase/supabase-js"

import { api, fetcher } from "@/lib/api"
import { createClient } from "@/lib/supabase/client"
import { createNavigationPrefetchQueue, dashboardBackgroundTargets, dashboardPrefetchTarget } from "@/lib/navigation-prefetch"
import { dashboardDataKeys } from "@/lib/navigation-data"
import type { Project } from "@/lib/types"
import { KNOWLEDGE_HEALTH_KEY, type KnowledgeHealth } from "@/lib/knowledge-health"
import { documentInsightsKey } from "@/lib/document-insights"
import { fetchPasskeys, fetchRecoveryCount, fetchTotpFactors, PASSKEYS_KEY, RECOVERY_KEY, TOTP_KEY } from "@/lib/settings-data"

function scheduleIdle(callback: () => void) {
  let idle: number | undefined
  const timer = window.setTimeout(() => {
    if ("requestIdleCallback" in window) idle = window.requestIdleCallback(callback, { timeout: 1500 })
    else callback()
  }, 250)
  return () => {
    window.clearTimeout(timer)
    if (idle != null) window.cancelIdleCallback(idle)
  }
}

export function DashboardPrefetch() {
  const router = useRouter()
  const pathname = usePathname()
  const { cache, mutate } = useSWRConfig()
  const { data: projects } = useSWR<Project[]>("/api/projects", fetcher)
  const enqueueRef = useRef<(() => void) | null>(null)
  const projectIdsRef = useRef<string[]>([])
  const currentPathRef = useRef(pathname)

  useEffect(() => {
    const supabase = createClient()
    let stopped = false
    let session: Session | null = null
    let accountId: string | undefined
    const controllers = new Set<AbortController>()
    const usable = () => !stopped && !!session?.expires_at && session.expires_at * 1000 > Date.now() + 60_000
    const paused = () => document.hidden || !navigator.onLine || !usable()
    const saveData = () => (navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData === true

    const dataQueue = createNavigationPrefetchQueue({
      schedule: scheduleIdle,
      paused,
      run: async (key, intent) => {
        if (!usable()) return false
        // A mounted page already fetching this key owns its request.
        if (cache.get(key)?.data === undefined && !cache.get(key)?.isValidating) {
          const controller = new AbortController()
          controllers.add(controller)
          const timeout = window.setTimeout(() => controller.abort(), 10_000)
          try {
            const read = key === PASSKEYS_KEY ? fetchPasskeys : key === TOTP_KEY ? fetchTotpFactors : key === RECOVERY_KEY ? fetchRecoveryCount
              : (path: string) => api(path, { signal: controller.signal })
            const data = await preload(key, (path: string) => Promise.race([
              read(path),
              new Promise<never>((_, reject) => controller.signal.addEventListener("abort", () => reject(new DOMException("Preload cancelled", "AbortError")), { once: true })),
            ]))
            if (!usable()) return false
            // Keep a newer page/edit result. Revalidation also releases SWR's
            // preload promise, so it cannot resurrect old data on a later visit.
            await mutate(key, (current: unknown) => current === undefined ? data : current)
          } catch {
            // Release a rejected preload through SWR's public API. An open
            // page can retry with its normal fetcher; future visits aren't poisoned.
            if (usable()) void mutate(key).catch(() => {})
            return false
          } finally {
            window.clearTimeout(timeout)
            controllers.delete(controller)
          }
        }
        if (key === KNOWLEDGE_HEALTH_KEY) {
          const health = cache.get(key)?.data as KnowledgeHealth | undefined
          const firstProject = health?.projects[0]?.id
          if (firstProject && projectIdsRef.current.includes(firstProject)) {
            dataQueue.enqueue(documentInsightsKey(firstProject, "30", "", 0), intent)
          }
        }
        return true
      },
    })

    function warmPageData(href: string, intent = false) {
      for (const key of dashboardDataKeys(href, projectIdsRef.current)) dataQueue.enqueue(key, intent)
    }

    // Route code never waits for a data request. Next schedules its own network
    // work; this queue only schedules lightweight router.prefetch calls.
    const routeQueue = createNavigationPrefetchQueue({
      schedule: scheduleIdle,
      paused,
      freshForMs: 5 * 60_000,
      run: async href => {
        if (!usable() || !dashboardPrefetchTarget(href, window.location.origin, projectIdsRef.current)) return false
        // Next 16 defaults to AUTO, which stops at loading boundaries on
        // dynamic routes. Its typed FULL option also prepares Gaps/projects.
        router.prefetch(href, { kind: PrefetchKind.FULL, onInvalidate: () => routeQueue.invalidate(href) })
        if (href.split("?")[0] === "/settings/usage") {
          void import("@/components/settings/usage-dashboard-content").catch(() => routeQueue.invalidate(href))
        }
        return true
      },
    })

    function enqueuePages() {
      if (!usable()) return
      if (!saveData()) {
        const paths = projectIdsRef.current.map(id => `/projects/${encodeURIComponent(id)}`)
        for (const href of dashboardBackgroundTargets(paths, currentPathRef.current)) {
          if (href === window.location.pathname + window.location.search) continue
          routeQueue.enqueue(href)
          warmPageData(href)
        }
      }
      routeQueue.resume()
      dataQueue.resume()
    }
    enqueueRef.current = enqueuePages

    function onIntent(event: Event) {
      if (!usable()) return
      const link = event.target instanceof Element ? event.target.closest("a[href]") : null
      if (!link || link.hasAttribute("download") || link.getAttribute("target") === "_blank") return
      const href = dashboardPrefetchTarget(link.getAttribute("href")!, window.location.origin, projectIdsRef.current)
      if (!href || href === window.location.pathname + window.location.search) return
      routeQueue.enqueue(href, true)
      warmPageData(href, true)
    }

    function stop() {
      stopped = true
      routeQueue.dispose()
      dataQueue.dispose()
      for (const controller of controllers) controller.abort()
    }
    function updateSession(next: Session | null) {
      if (stopped) return
      if (accountId && next?.user.id !== accountId) { stop(); return }
      session = next
      accountId = next?.user.id
      enqueuePages()
    }
    const { data: authListener } = supabase.auth.onAuthStateChange((event, next) => {
      // No async auth methods inside this callback (auth-js lock).
      if (event === "SIGNED_OUT") stop()
      else updateSession(next)
    })
    void supabase.auth.getSession().then(({ data }) => updateSession(data.session)).catch(() => {})
    document.addEventListener("pointerover", onIntent, { passive: true })
    document.addEventListener("pointerdown", onIntent, { passive: true })
    document.addEventListener("focusin", onIntent)
    document.addEventListener("visibilitychange", enqueuePages)
    window.addEventListener("online", enqueuePages)
    return () => {
      stop()
      enqueueRef.current = null
      authListener.subscription.unsubscribe()
      document.removeEventListener("pointerover", onIntent)
      document.removeEventListener("pointerdown", onIntent)
      document.removeEventListener("focusin", onIntent)
      document.removeEventListener("visibilitychange", enqueuePages)
      window.removeEventListener("online", enqueuePages)
    }
  }, [router, cache, mutate])

  useEffect(() => {
    currentPathRef.current = pathname
    projectIdsRef.current = (projects ?? []).map(project => project.id)
    enqueueRef.current?.()
  }, [pathname, projects])

  return null
}
