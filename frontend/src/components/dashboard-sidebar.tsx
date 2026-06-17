"use client"

import {
  Circle,
  Database,
  FileText,
  FolderKanban,
  Home,
  KeyRound,
  Plus,
  Search,
} from "lucide-react"
import Image from "next/image"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useMemo, useState } from "react"
import useSWR from "swr"

import { UserMenu } from "@/components/user-menu"
import { ThemeToggle } from "@/components/theme-toggle"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { fetcher } from "@/lib/api"
import type { FileRecord, Project } from "@/lib/types"
import { cn } from "@/lib/utils"

const mainNav = [
  { href: "/dashboard", label: "Overview", icon: Home },
  { href: "/projects/new", label: "New project", icon: Plus },
  { href: "/settings/api-keys", label: "API keys", icon: KeyRound },
]

const statusTone: Record<Project["status"], string> = {
  empty: "fill-muted-foreground text-muted-foreground",
  indexing: "fill-amber-500 text-amber-500",
  ready: "fill-emerald-500 text-emerald-500",
  error: "fill-red-500 text-red-500",
}

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

function ProjectLink({
  project,
  active,
}: {
  project: Project
  active: boolean
}) {
  return (
    <Link
      href={`/projects/${project.id}`}
      className={cn(
        "flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium text-sidebar-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
        active && "bg-sidebar-accent text-sidebar-accent-foreground"
      )}
    >
      <FolderKanban className="size-4 shrink-0" />
      <span className="min-w-0 flex-1 truncate">{project.name}</span>
      <Circle
        className={cn("size-2.5 shrink-0", statusTone[project.status])}
        aria-label={project.status}
      />
    </Link>
  )
}

function FileItem({
  file,
  projectId,
}: {
  file: FileRecord
  projectId: string
}) {
  return (
    <Link
      href={`/projects/${projectId}?file=${file.id}`}
      title={file.filename}
      className="flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium text-sidebar-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
    >
      <FileText className="size-4 shrink-0 text-sidebar-foreground/55" />
      <span className="min-w-0 flex-1 truncate">{file.filename}</span>
    </Link>
  )
}

export function DashboardSidebar() {
  const pathname = usePathname()
  const [query, setQuery] = useState("")

  // Inside a single project, the panel switches to that project's files.
  const projectMatch = pathname.match(/^\/projects\/([^/]+)$/)
  const projectId =
    projectMatch && projectMatch[1] !== "new" ? projectMatch[1] : null
  const inProject = projectId !== null

  const {
    data: projects,
    isLoading: projectsLoading,
  } = useSWR<Project[]>("/api/projects", fetcher)
  const {
    data: files,
    isLoading: filesLoading,
  } = useSWR<FileRecord[]>(
    projectId ? `/api/projects/${projectId}/files` : null,
    fetcher
  )

  // Clear the search box when switching between the projects/files contexts.
  useEffect(() => {
    setQuery("")
  }, [projectId])

  const filteredProjects = useMemo(() => {
    const term = query.trim().toLowerCase()
    if (!term) return projects ?? []
    return (projects ?? []).filter((project) =>
      [project.name, project.description ?? "", project.status]
        .join(" ")
        .toLowerCase()
        .includes(term)
    )
  }, [projects, query])

  const filteredFiles = useMemo(() => {
    // most recent first
    const list = [...(files ?? [])].sort((a, b) =>
      a.created_at < b.created_at ? 1 : -1
    )
    const term = query.trim().toLowerCase()
    if (!term) return list
    return list.filter((file) => file.filename.toLowerCase().includes(term))
  }, [files, query])

  return (
    <aside className="border-sidebar-border bg-sidebar text-sidebar-foreground md:min-h-dvh md:border-r">
      <div className="flex h-full flex-col gap-5 p-4 md:sticky md:top-0 md:h-dvh">
        <div className="flex items-center justify-between gap-3">
          <Link
            href="/dashboard"
            className="group flex min-w-0 items-center gap-3"
          >
            <span className="flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-black/10 transition-transform group-hover:scale-[1.03] dark:bg-black dark:ring-white/15">
              <Image
                src="/logo.png"
                alt="Oreag"
                width={200}
                height={200}
                priority
                className="size-full object-contain dark:invert"
              />
            </span>
            <span className="min-w-0 leading-tight">
              <span className="block truncate text-lg font-semibold tracking-tight">
                Oreag
              </span>
              <span className="block truncate text-xs text-sidebar-foreground/55">
                RAG & Memory
              </span>
            </span>
          </Link>
          <div className="md:hidden">
            <UserMenu compact />
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
              {inProject ? "Files" : "Projects"}
            </span>
            {(inProject ? files?.length : projects?.length) ? (
              <Badge variant="secondary" className="h-5 rounded-md px-1.5 text-[10px]">
                {inProject ? files?.length : projects?.length}
              </Badge>
            ) : null}
          </div>

          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-sidebar-foreground/45" />
            <Input
              type="search"
              placeholder={inProject ? "Search files" : "Search projects"}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-8 bg-background pl-8 text-sm"
            />
          </div>

          <div className="grid max-h-72 gap-1 overflow-y-auto pr-1 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden md:max-h-[calc(100dvh-22rem)]">
            {(inProject ? filesLoading : projectsLoading) && (
              <>
                <Skeleton className="h-9" />
                <Skeleton className="h-9" />
              </>
            )}

            {inProject ? (
              <>
                {files?.length === 0 && (
                  <div className="rounded-md px-3 py-2 text-xs text-sidebar-foreground/55">
                    No files yet
                  </div>
                )}
                {files && files.length > 0 && filteredFiles.length === 0 && (
                  <div className="rounded-md px-3 py-2 text-xs text-sidebar-foreground/55">
                    No matching files
                  </div>
                )}
                {filteredFiles.map((file) => (
                  <FileItem
                    key={file.id}
                    file={file}
                    projectId={projectId as string}
                  />
                ))}
              </>
            ) : (
              <>
                {projects?.length === 0 && (
                  <div className="rounded-md px-3 py-2 text-xs text-sidebar-foreground/55">
                    No projects yet
                  </div>
                )}
                {projects &&
                  projects.length > 0 &&
                  filteredProjects.length === 0 && (
                    <div className="rounded-md px-3 py-2 text-xs text-sidebar-foreground/55">
                      No matching projects
                    </div>
                  )}
                {filteredProjects.map((project) => (
                  <ProjectLink
                    key={project.id}
                    project={project}
                    active={pathname === `/projects/${project.id}`}
                  />
                ))}
              </>
            )}
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
            <UserMenu />
          </div>
        </div>
      </div>
    </aside>
  )
}
