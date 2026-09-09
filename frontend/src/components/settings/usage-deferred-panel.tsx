"use client"

import { useEffect, useRef, useState, type ReactNode } from "react"
import { UsageChartSkeleton } from "@/components/settings/usage-loading"

/** Mount chart/table work shortly before it scrolls into view. Once mounted,
 * keep it alive so scrolling and SWR refreshes preserve local UI state. */
export function DeferredUsagePanel({ children, label, layout }: {
  children: ReactNode
  label: string
  layout?: "daily"
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (!("IntersectionObserver" in window)) {
      const frame = requestAnimationFrame(() => setReady(true))
      return () => cancelAnimationFrame(frame)
    }
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry?.isIntersecting) return
      setReady(true)
      observer.disconnect()
    }, { rootMargin: "240px 0px", threshold: 0 })
    if (ref.current) observer.observe(ref.current)
    return () => observer.disconnect()
  }, [])

  return (
    <div
      ref={ref}
      className="min-w-0 rounded-xl focus-visible:outline-2 focus-visible:outline-ring"
      data-usage-panel={label}
      data-ready={ready}
      data-usage-layout={layout}
      tabIndex={ready ? undefined : 0}
      onFocus={() => setReady(true)}
    >
      {ready ? children : (
        <div className="usage-panel-placeholder" aria-busy="true" aria-label={`Loading ${label.toLowerCase()}`}>
          {layout === "daily" ? <div className="grid gap-3 sm:gap-4 lg:grid-cols-2"><UsageChartSkeleton label="Daily requests" /><UsageChartSkeleton label="Daily tokens" /></div> : <UsageChartSkeleton label={label} kind={label.endsWith("usage") ? "table" : "chart"} />}
        </div>
      )}
    </div>
  )
}
