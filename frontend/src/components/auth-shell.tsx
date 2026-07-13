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
    <div className="flex min-h-screen items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-md rounded-3xl py-8">
        <CardContent className="space-y-6">
          <div className="flex flex-col items-center gap-3 text-center">
            <BrandMark className="size-12 rounded-2xl" imgClassName="scale-150" />
            <span className="rounded-full border bg-muted/60 px-3 py-1 text-[11px] font-medium text-muted-foreground">
              {badge}
            </span>
            <div className="space-y-1">
              <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
              <p className="text-sm text-muted-foreground">{subtitle}</p>
            </div>
          </div>
          {children}
        </CardContent>
      </Card>
    </div>
  )
}
