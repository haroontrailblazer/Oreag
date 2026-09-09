"use client"

import { useEffect, useRef, useState, type ReactNode } from "react"

/** Mount chart/table work shortly before it scrolls into view. Once mounted,
 * keep it alive so scrolling and SWR refreshes preserve local UI state. */
export function DeferredUsagePanel({ children, label, minHeight }: {
  children: ReactNode
  label: string
  minHeight: number
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
      tabIndex={ready ? undefined : 0}
      onFocus={() => setReady(true)}
    >
      {ready ? children : (
        <div className="rounded-xl border border-border bg-card p-6" style={{ minHeight }} aria-busy="true" aria-label={`Loading ${label.toLowerCase()}`}>
          <p className="text-sm font-medium text-muted-foreground">{label}</p>
        </div>
      )}
    </div>
  )
}
