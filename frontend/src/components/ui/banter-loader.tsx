import { cn } from "@/lib/utils"

/**
 * The "banter" 9-box shuffle loader (CSS lives in globals.css under
 * `.banter-loader`). It's authored at 72px and scaled to `size`; the boxes use
 * currentColor, so tint it with a text-* class.
 */
export function BanterLoader({
  size = 22,
  className,
}: {
  size?: number
  className?: string
}) {
  return (
    <span
      role="status"
      aria-label="Indexing"
      className={cn("relative inline-block shrink-0", className)}
      style={{ width: size, height: size }}
    >
      <span
        className="banter-loader"
        style={{ transform: `scale(${size / 72})`, transformOrigin: "top left" }}
      >
        {Array.from({ length: 9 }).map((_, i) => (
          <span key={i} className="banter-loader__box" />
        ))}
      </span>
    </span>
  )
}
