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
    <div className="min-h-dvh bg-background md:grid md:h-dvh md:grid-cols-[16rem_minmax(0,1fr)] md:overflow-hidden">
      <DashboardSidebar />
      <main className="min-w-0 bg-muted/20 md:overflow-y-auto">
        <div className="mx-auto max-w-6xl p-4 py-6 md:p-8">{children}</div>
      </main>
    </div>
  )
}
