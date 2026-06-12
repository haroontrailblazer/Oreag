"use client"

import { Database, FolderKanban, Home, Plus } from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import useSWR from "swr"

import { SignOutButton } from "@/components/sign-out-button"
import { ThemeToggle } from "@/components/theme-toggle"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { fetcher } from "@/lib/api"
import type { Project } from "@/lib/types"
import { cn } from "@/lib/utils"

const mainNav = [
  { href: "/dashboard", label: "Overview", icon: Home },
  { href: "/projects/new", label: "New project", icon: Plus },
]

function SidebarLink({
  href,
  label,
  icon: Icon,
  active,
}: {
  href: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  active: boolean
}) {
  return (
    <Link
      href={href}
      className={cn(
        "flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium text-sidebar-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
        active && "bg-sidebar-accent text-sidebar-accent-foreground"
      )}
    >
      <Icon className="size-4" />
      <span className="truncate">{label}</span>
    </Link>
  )
}

export function DashboardSidebar() {
  const pathname = usePathname()
  const { data: projects, isLoading } = useSWR<Project[]>("/api/projects", fetcher)

  return (
    <aside className="border-sidebar-border bg-sidebar text-sidebar-foreground md:min-h-dvh md:border-r">
      <div className="flex h-full flex-col gap-5 p-4 md:sticky md:top-0 md:h-dvh">
        <div className="flex items-center justify-between gap-3">
          <Link href="/dashboard" className="flex min-w-0 items-center gap-2">
            <span className="grid size-8 place-items-center rounded-lg bg-sidebar-primary text-sm font-semibold text-sidebar-primary-foreground">
              O
            </span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold">Oreag</span>
              <span className="block truncate text-xs text-sidebar-foreground/55">
                RAG API
              </span>
            </span>
          </Link>
          <div className="md:hidden">
            <SignOutButton />
          </div>
        </div>

        <nav className="grid gap-1">
          {mainNav.map((item) => (
            <SidebarLink
              key={item.href}
              {...item}
              active={
                item.href === "/dashboard"
                  ? pathname === "/dashboard"
                  : pathname.startsWith(item.href)
              }
            />
          ))}
        </nav>

        <Separator />

        <div className="min-h-0 flex-1 space-y-2">
          <div className="flex items-center justify-between px-3">
            <span className="text-xs font-medium uppercase tracking-wide text-sidebar-foreground/55">
              Projects
            </span>
            {projects && projects.length > 0 && (
              <Badge variant="secondary" className="h-5 rounded-md px-1.5 text-[10px]">
                {projects.length}
              </Badge>
            )}
          </div>

          <div className="grid max-h-72 gap-1 overflow-y-auto pr-1 md:max-h-[calc(100dvh-22rem)]">
            {isLoading && (
              <>
                <Skeleton className="h-9" />
                <Skeleton className="h-9" />
              </>
            )}

            {projects?.length === 0 && (
              <div className="rounded-md px-3 py-2 text-xs text-sidebar-foreground/55">
                No projects yet
              </div>
            )}

            {projects?.map((project) => (
              <SidebarLink
                key={project.id}
                href={`/projects/${project.id}`}
                label={project.name}
                icon={FolderKanban}
                active={pathname === `/projects/${project.id}`}
              />
            ))}
          </div>
        </div>

        <Separator />

        <div className="space-y-3">
          <Button asChild variant="outline" className="w-full justify-start bg-background">
            <Link href="/projects/new">
              <Database className="size-4" />
              Create knowledge base
            </Link>
          </Button>
          <ThemeToggle />
          <div className="hidden md:block">
            <SignOutButton />
          </div>
        </div>
      </div>
    </aside>
  )
}
