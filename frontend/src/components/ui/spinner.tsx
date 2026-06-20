import { cn } from "@/lib/utils"

// Per-bar animation offsets — a brightness highlight travels around the ring.
const BAR_DELAYS = [
  "0s",
  "-1.1s",
  "-1s",
  "-0.9s",
  "-0.8s",
  "-0.7s",
  "-0.6s",
  "-0.5s",
  "-0.4s",
  "-0.3s",
  "-0.2s",
  "-0.1s",
]

/**
 * A 12-bar fading spinner (CSS `spinner-fade` keyframe lives in globals.css).
 * Colour follows `currentColor`, so set the tone with a text-* class.
 */
export function Spinner({
  className,
  size = 20,
}: {
  className?: string
  size?: number
}) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cn("relative inline-block shrink-0", className)}
      style={{ width: size, height: size }}
    >
      {BAR_DELAYS.map((delay, i) => (
        <span
          key={i}
          className="absolute left-1/2 top-[30%] h-[24%] w-[8%] rounded-full bg-current animate-[spinner-fade_1s_linear_infinite]"
          style={{
            transform: `rotate(${i * 30}deg) translate(0, -130%)`,
            animationDelay: delay,
          }}
        />
      ))}
    </span>
  )
}
