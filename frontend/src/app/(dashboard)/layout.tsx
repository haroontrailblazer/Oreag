import { DashboardSidebar } from "@/components/dashboard-sidebar"

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    // Desktop: the shell is exactly one viewport tall (md:h-dvh + overflow
    // hidden), so the page body never scrolls past the content - only <main>
    // scrolls its own area. That removes the empty band that appeared below the
    // sidebar/content on tall pages. Mobile keeps a natural min-h-dvh scroll.
    // relative is load-bearing: sr-only spans (position:absolute) inside cards
    // have no positioned ancestor, so their containing block would be the
    // document - escaping every overflow clip and stretching the page (the
    // phantom body scroll / black band). Anchoring them here keeps them inside
    // the clipped root.
    <div className="relative min-h-dvh bg-background md:grid md:h-dvh md:grid-cols-[16rem_minmax(0,1fr)] md:overflow-hidden">
      <DashboardSidebar />
      <main className="min-w-0 bg-muted/20 md:h-dvh md:overflow-y-auto">
        {/* min-h-full + md:h-full give children a *definite* height to resolve
            h-full/flex-1 against, so fixed-frame pages derive their height from
            the real layout (no hardcoded viewport-minus-chrome guesses). */}
        <div className="mx-auto flex min-h-full max-w-6xl flex-col p-4 py-6 md:h-full md:p-8">
          {children}
        </div>
      </main>
    </div>
  )
}
