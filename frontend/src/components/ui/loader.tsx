import { CircleNotch } from "@phosphor-icons/react/dist/ssr"
import type { CSSProperties } from "react"

import { cn } from "@/lib/utils"

/**
 * Minimal spinning indicator (Phosphor CircleNotch) - the app-wide loading
 * mark for buttons and actions (OAuth, login, signup, sign out, save...).
 * Follows currentColor and defaults to size-4. The playground chat keeps its
 * own three-dot LoaderOne below.
 */
export function Spin({ className }: { className?: string }) {
  return (
    <CircleNotch
      weight="bold"
      aria-label="Loading"
      className={cn("size-4 shrink-0 animate-spin", className)}
    />
  )
}

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
