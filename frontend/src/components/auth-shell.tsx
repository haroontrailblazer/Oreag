import { BrandMark } from "@/components/ui/brand-mark"
import { Card, CardContent } from "@/components/ui/card"

/**
 * Shared chrome for the auth screens: centered card with the brand mark, a
 * small pill badge, a bold heading and a muted subtitle. The Login/Sign Up
 * switch lives in each page's footer (not a top toggle) to match the design.
 */
export function AuthShell({
  title,
  subtitle,
  badge = "RAG & Memory API",
  children,
}: {
  title: string
  subtitle: string
  badge?: string
  children: React.ReactNode
}) {
  return (
    // min-h-dvh (not min-h-screen/100vh): on mobile 100vh includes the
    // address-bar area, so the page ends up taller than the visible viewport
    // and scrolls even when the content fits. dvh tracks the real visible
    // height. overflow-x-hidden guards against any stray horizontal scroll.
    <div className="flex min-h-dvh items-center justify-center overflow-x-hidden bg-muted/40 p-4">
      <Card className="w-full max-w-md rounded-3xl py-5 sm:py-8">
        <CardContent className="space-y-4 sm:space-y-6">
          <div className="flex flex-col items-center gap-2 text-center">
            <BrandMark className="size-11 rounded-2xl sm:size-12" imgClassName="scale-150" />
            <span className="rounded-full border bg-muted/60 px-3 py-1 text-[11px] font-medium text-muted-foreground">
              {badge}
            </span>
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
