"use client"

import { cn } from "@/lib/utils"

/**
 * The 3D "building boxes" loader (CSS lives in globals.css under `.box-build`).
 * Authored at 200×320 and scaled by `scale`; boxes use the theme --primary and
 * the masks use --background, so it must sit on a `bg-background` surface.
 *
 * `onCycle` fires once at the end of every full animation cycle - use it to
 * defer closing until the animation has finished, even if the work ended early.
 */
/* The scatter/drop travel paints beyond the assembled cube, and the
   background-colored mask rects swing out the sides. Clip to a snug window
   around the action (fly-ins enter and the final drop exits through the clip
   edges) so the loader hugs its visuals and never overlaps dialog text.
   Coordinates are authored-units; scatter offsets in globals.css are kept
   within this window. */
const PAD_X = 20
const CROP_TOP = 25
const VISIBLE_BOTTOM = 235

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
      className={cn("relative overflow-hidden", className)}
      style={{
        width: (200 + PAD_X * 2) * scale,
        height: (VISIBLE_BOTTOM - CROP_TOP) * scale,
      }}
    >
      <div
        className="box-build"
        style={{
          transform: `translate(${PAD_X * scale}px, ${-CROP_TOP * scale}px) scale(${scale})`,
          transformOrigin: "top left",
        }}
      >
        {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
          <div
            key={i}
            className={`box box${i}`}
            // box0's move animation is one per cycle - use it as the heartbeat.
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
