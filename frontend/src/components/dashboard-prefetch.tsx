"use client"

import { useEffect, useRef } from "react"
import { usePathname, useRouter } from "next/navigation"
import useSWR, { preload, useSWRConfig } from "swr"

import { fetcher } from "@/lib/api"
import { createClient } from "@/lib/supabase/client"
import { createNavigationPrefetchQueue, dashboardPrefetchTarget, DASHBOARD_ROUTES } from "@/lib/navigation-prefetch"
import type { Project } from "@/lib/types"

function scheduleIdle(callback: () => void) {
  // Space out work and allow the page the user opened to paint first.
  let idle: number | undefined
  const timer = window.setTimeout(() => {
    if ("requestIdleCallback" in window) {
      idle = window.requestIdleCallback(callback, { timeout: 1500 })
    } else callback()
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
  // Shares the sidebar's existing subscription, cache and fetcher.
  const { data: projects } = useSWR<Project[]>("/api/projects", fetcher)
  const queueRef = useRef<ReturnType<typeof createNavigationPrefetchQueue> | null>(null)
  const pathsRef = useRef<string[]>([])
  const currentPathRef = useRef(pathname)

  useEffect(() => {
    const supabase = createClient()
    let stopped = false
    let accountId: string | undefined

    async function warmData(key: string) {
      if (stopped || cache.get(key)?.data !== undefined) return
      // Populate the same SWR cache for immediate rendering. The page keeps
      // its normal revalidation/polling rules when it is actually opened.
      const data = await preload(key, fetcher)
      if (!stopped && cache.get(key)?.data === undefined) {
        await mutate(key, data, { revalidate: false })
      }
    }

    const queue = createNavigationPrefetchQueue({
      schedule: scheduleIdle,
      paused: () => document.hidden || !navigator.onLine,
      run: async (href) => {
        const path = href.split("?")[0]
        if (path === currentPathRef.current) return false
        if (path.startsWith("/projects/") && path !== "/projects/new" && !pathsRef.current.includes(path)) return false
        // The dashboard has already passed server auth. Check the current
        // session again before speculation so an expired session cannot warm
        // a login redirect into the router cache.
        const { data: { session } } = await supabase.auth.getSession()
        if (stopped || !session || !session.expires_at || session.expires_at * 1000 <= Date.now() + 60_000) return false
        if (accountId && accountId !== session.user.id) return false
        accountId = session.user.id
        router.prefetch(href)
        if (path === "/settings/usage") {
          await import("@/components/settings/usage-dashboard-content")
        } else if (path === "/projects/new") {
          await warmData("/api/models")
        } else if (path.startsWith("/projects/")) {
          await warmData(`/api${path}`)
          if (!stopped) await warmData(`/api${path}/files`)
        }
        return !stopped
      },
    })
    queueRef.current = queue

    function enqueuePages() {
      for (const href of [...DASHBOARD_ROUTES, ...pathsRef.current]) {
        if (href !== currentPathRef.current) queue.enqueue(href)
      }
      queue.resume()
    }

    function onIntent(event: Event) {
      const link = event.target instanceof Element ? event.target.closest("a[href]") : null
      if (!link || link.hasAttribute("download") || link.getAttribute("target") === "_blank") return
      const projectIds = pathsRef.current.map(path => decodeURIComponent(path.slice("/projects/".length)))
      const href = dashboardPrefetchTarget(link.getAttribute("href")!, window.location.origin, projectIds)
      if (href && href.split("?")[0] !== currentPathRef.current) queue.enqueue(href, true)
    }

    const { data: authListener } = supabase.auth.onAuthStateChange((event, session) => {
      // Do not call async auth methods inside this callback (auth-js lock).
      if (event === "SIGNED_OUT" || (accountId && session?.user.id !== accountId)) {
        stopped = true
        queue.dispose()
      }
    })
    enqueuePages()
    document.addEventListener("pointerover", onIntent, { passive: true })
    document.addEventListener("focusin", onIntent)
    document.addEventListener("visibilitychange", enqueuePages)
    window.addEventListener("online", enqueuePages)
    return () => {
      stopped = true
      queue.dispose()
      queueRef.current = null
      authListener.subscription.unsubscribe()
      document.removeEventListener("pointerover", onIntent)
      document.removeEventListener("focusin", onIntent)
      document.removeEventListener("visibilitychange", enqueuePages)
      window.removeEventListener("online", enqueuePages)
    }
  }, [router, cache, mutate])

  useEffect(() => {
    currentPathRef.current = pathname
    pathsRef.current = (projects ?? []).map(project => `/projects/${encodeURIComponent(project.id)}`)
    for (const href of [...DASHBOARD_ROUTES, ...pathsRef.current]) {
      if (href !== pathname) queueRef.current?.enqueue(href)
    }
  }, [pathname, projects])

  return null
}
