import { cn } from "@/lib/utils"

// (delay ms, alternate?) per square — the original 3×3 staggered fade wave.
const SQUARES = [
  { delay: 0, alternate: true },
  { delay: 75, alternate: true },
  { delay: 150, alternate: false },
  { delay: 225, alternate: false },
  { delay: 300, alternate: false },
  { delay: 375, alternate: false },
  { delay: 450, alternate: false },
  { delay: 525, alternate: false },
  { delay: 600, alternate: false },
]

/**
 * A 3×3 grid of squares that fade in and out in sequence. Colour follows
 * currentColor; animation uses the `fade-in` keyframe in globals.css.
 */
export function SquaresLoader({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cn("grid grid-cols-3 gap-px", className)}
    >
      {SQUARES.map((square, i) => (
        <span
          key={i}
          className="size-1 bg-current animate-[fade-in_675ms_ease-in-out_infinite]"
          style={{
            animationDelay: `${square.delay}ms`,
            animationDirection: square.alternate ? "alternate" : "normal",
          }}
        />
      ))}
    </span>
  )
}
