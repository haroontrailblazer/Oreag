import type { CSSProperties } from "react"

import { cn } from "@/lib/utils"

/**
 * Three dots that bounce in sequence - a drop-in loading indicator used in
 * place of "…" button labels and ad-hoc dot rows. Colour follows currentColor,
 * so it reads correctly on a dark button (white) or muted text (grey).
 * Animation keyframe `loader-one-bounce` lives in globals.css.
 */
export function LoaderOne({
  className,
  size = 4,
}: {
  className?: string
  size?: number
}) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cn("inline-flex items-center", className)}
      style={{ gap: size * 0.5 }}
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="inline-block shrink-0 rounded-full bg-current animate-[loader-one-bounce_0.9s_ease-in-out_infinite]"
          style={
            {
              width: size,
              height: size,
              animationDelay: `${i * 0.15}s`,
              "--loader-bounce": `${-(size * 0.9)}px`,
            } as CSSProperties
          }
        />
      ))}
    </span>
  )
}
