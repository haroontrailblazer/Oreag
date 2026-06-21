import Image from "next/image"

import { cn } from "@/lib/utils"

/**
 * The Oreag logo rendered as a 3D app-icon badge. Centralised so the brand mark
 * gets the same depth/gloss treatment everywhere it appears (landing, auth,
 * sidebar, mobile bar). Pass size + rounding (and any hover) through
 * `className`; `imgClassName` tweaks the logo itself (e.g. `scale-150`). The
 * 3D surface comes from the `.brand-mark` class in globals.css.
 */
export function BrandMark({
  className,
  imgClassName,
}: {
  className?: string
  imgClassName?: string
}) {
  return (
    <span className={cn("brand-mark", className)}>
      <Image
        src="/logo.png"
        alt=""
        width={200}
        height={200}
        priority
        className={cn("size-full object-contain dark:invert", imgClassName)}
      />
    </span>
  )
}
