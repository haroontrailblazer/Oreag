"use client"

import { cn } from "@/lib/utils"

/**
 * The 3D "building boxes" loader (CSS lives in globals.css under `.box-build`).
 * Authored at 200×320 and scaled by `scale`; boxes use the theme --primary and
 * the masks use --background, so it must sit on a `bg-background` surface.
 *
 * `onCycle` fires once at the end of every full animation cycle — use it to
 * defer closing until the animation has finished, even if the work ended early.
 */
export function BoxLoader({
  scale = 0.5,
  className,
  onCycle,
}: {
  scale?: number
  className?: string
  onCycle?: () => void
}) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className={cn("relative", className)}
      style={{ width: 200 * scale, height: 320 * scale }}
    >
      <div
        className="box-build"
        style={{ transform: `scale(${scale})`, transformOrigin: "top left" }}
      >
        {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
          <div
            key={i}
            className={`box box${i}`}
            // box0's move animation is one per cycle — use it as the heartbeat.
            onAnimationIteration={
              i === 0 && onCycle
                ? (e) => {
                    if (e.animationName === "bb-move0") onCycle()
                  }
                : undefined
            }
          >
            <div />
          </div>
        ))}
        <div className="ground">
          <div />
        </div>
      </div>
    </div>
  )
}
