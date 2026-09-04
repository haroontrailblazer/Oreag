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
  keyboardStable = false,
  children,
}: {
  title: string
  subtitle: string
  badge?: string
  /** Anchor keypad-based steps on mobile so focusing a code does not pan the card. */
  keyboardStable?: boolean
  children: React.ReactNode
}) {
  return (
    // svh stays stable when the mobile keypad opens. Keeping the card inside a
    // stable viewport and scrolling only its contents prevents the whole page
    // from re-centering while a code field is focused.
    <div
      className={cn(
        "flex h-svh justify-center overflow-hidden bg-muted/40 p-4",
        keyboardStable ? "items-start sm:items-center" : "items-center"
      )}
    >
      <Card className="w-full max-w-md max-h-[calc(100svh-2rem)] overflow-y-auto rounded-3xl py-5 no-scrollbar sm:py-8">
        <CardContent className="flex flex-col gap-4 sm:gap-6">
          <div className="flex flex-col items-center gap-2 text-center">
            <BrandMark
              className="size-11 shrink-0 rounded-2xl sm:size-12"
              imgClassName="scale-150"
            />
            <span className="rounded-full border bg-muted/60 px-3 py-1 text-[11px] font-medium text-muted-foreground">
              {badge}
            </span>
            <div className="flex flex-col gap-1">
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
