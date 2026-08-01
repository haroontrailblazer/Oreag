import { BrandMark } from "@/components/ui/brand-mark"
import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

/**
 * Shared chrome for the auth screens: centered card with the brand mark, a
 * small pill badge, a bold heading and a muted subtitle. The Login/Sign Up
 * switch lives in each page's footer (not a top toggle) to match the design.
 */
export function AuthShell({
  title,
  subtitle,
  badge = "RAG & Memory API",
  keyboardCompact = false,
  children,
}: {
  title: string
  subtitle: string
  badge?: string
  /** Compact nonessential chrome while a mobile text input has focus. */
  keyboardCompact?: boolean
  children: React.ReactNode
}) {
  return (
    // min-h-dvh (not min-h-screen/100vh): on mobile 100vh includes the
    // address-bar area, so the page ends up taller than the visible viewport
    // and scrolls even when the content fits. dvh tracks the real visible
    // height. overflow-x-hidden guards against any stray horizontal scroll.
    <div className="flex min-h-dvh items-center justify-center overflow-x-hidden bg-muted/40 p-4">
      <Card
        className={cn(
          "group w-full max-w-md rounded-3xl py-5 sm:py-8",
          keyboardCompact && "max-sm:focus-within:py-3"
        )}
      >
        <CardContent
          className={cn(
            "space-y-4 sm:space-y-6",
            keyboardCompact && "max-sm:group-focus-within:space-y-3"
          )}
        >
          <div
            className={cn(
              "flex flex-col items-center gap-2 text-center",
              keyboardCompact && "max-sm:group-focus-within:gap-1"
            )}
          >
            <div
              className={cn(
                "contents",
                keyboardCompact &&
                  "max-sm:group-focus-within:hidden sm:group-focus-within:contents"
              )}
            >
              <BrandMark
                className="size-11 rounded-2xl sm:size-12"
                imgClassName="scale-150"
              />
              <span className="rounded-full border bg-muted/60 px-3 py-1 text-[11px] font-medium text-muted-foreground">
                {badge}
              </span>
            </div>
            <div className="space-y-1">
              <h1 className="text-xl font-bold tracking-tight sm:text-2xl">
                {title}
              </h1>
              <p className="text-sm text-muted-foreground">{subtitle}</p>
            </div>
          </div>
          {children}
        </CardContent>
      </Card>
    </div>
  )
}
