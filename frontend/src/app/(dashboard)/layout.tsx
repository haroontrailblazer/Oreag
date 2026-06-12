import { DashboardSidebar } from "@/components/dashboard-sidebar"

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="min-h-screen bg-background md:grid md:grid-cols-[16rem_minmax(0,1fr)]">
      <DashboardSidebar />
      <main className="min-w-0 bg-muted/20">
        <div className="mx-auto max-w-6xl p-4 py-6 md:p-8">{children}</div>
      </main>
    </div>
  )
}
