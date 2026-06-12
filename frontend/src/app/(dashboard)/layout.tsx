import Link from "next/link"

import { SignOutButton } from "@/components/sign-out-button"

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="min-h-screen bg-muted/20">
      <header className="border-b bg-background">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
          <Link href="/dashboard" className="text-lg font-semibold">
            Oreag
          </Link>
          <SignOutButton />
        </div>
      </header>
      <main className="mx-auto max-w-5xl p-4 py-8">{children}</main>
    </div>
  )
}
