import { cn } from "@/lib/utils"

/**
 * The approved context-loop mark. Its transparent mask inherits currentColor,
 * keeping the same silhouette in light and dark themes without a badge surface.
 */
export function BrandMark({
  className,
}: {
  className?: string
}) {
  return (
    <span aria-hidden="true" className={cn("brand-mark size-9 shrink-0 text-foreground", className)} />
  )
}

/** Shared centered lockup for every authentication and password card. */
export function AuthBrand() {
  return (
    <div className="flex flex-col items-center gap-2 pb-2 text-foreground" data-slot="auth-brand">
      <BrandMark className="size-12 sm:size-14" />
      <span className="text-2xl font-bold leading-none tracking-[-0.045em]">Oreag</span>
    </div>
  )
}
