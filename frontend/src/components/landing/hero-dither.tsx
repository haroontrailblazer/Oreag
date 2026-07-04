"use client"

import dynamic from "next/dynamic"
import { useSyncExternalStore } from "react"

// three.js must never run on the server, and the hero panel only exists at
// lg+. Gating the mount on the breakpoint also means phones never download
// the (heavy) 3D chunk for a display:none panel.
const Dither = dynamic(() => import("./dither"), { ssr: false })

function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mq = window.matchMedia(query)
      mq.addEventListener("change", onChange)
      return () => mq.removeEventListener("change", onChange)
    },
    () => window.matchMedia(query).matches,
    () => false
  )
}

export function HeroDither() {
  const desktop = useMediaQuery("(min-width: 1024px)")
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)")

  if (!desktop) return null

  return (
    <Dither
      src="/hero.jpg"
      colorNum={4}
      pixelSize={2}
      disableAnimation={reducedMotion}
    />
  )
}
