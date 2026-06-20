"use client"

import {
  CaretRight as ChevronRight,
  Circle,
  FileText,
  Kanban as FolderKanban,
  House as Home,
  Key as KeyRound,
  List,
  Plus,
  MagnifyingGlass as Search,
} from "@phosphor-icons/react/dist/ssr"
import Image from "next/image"
import Link, { useLinkStatus } from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useMemo, useState } from "react"
import useSWR from "swr"

import { UserMenu } from "@/components/user-menu"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { fetcher } from "@/lib/api"
import { useProjectNavPending } from "@/lib/nav-pending"
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

/** Right-side indicator: a spinner while this link's navigation is pending,
 *  otherwise the project's status dot. Fixed-size slot so the swap doesn't
 *  shift the truncated name. Must live inside the <Link> for useLinkStatus. */
function ProjectNavIndicator({
  projectId,
  status,
}: {
  projectId: string
  status: Project["status"]
}) {
  const { pending } = useLinkStatus()
  const navigating = useProjectNavPending(projectId, pending)
  return (
    <span className="flex size-3.5 shrink-0 items-center justify-center">
      {navigating ? (
        <Spinner size={14} className="text-sidebar-foreground/55" />
      ) : (
        <Circle
          weight="fill"
          className={cn("size-2.5", statusTone[status])}
          aria-label={status}
        />
      )}
    </span>
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
      prefetch={false}
      className={cn(
        "flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium text-sidebar-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
        active && "bg-sidebar-accent text-sidebar-accent-foreground"
      )}
    >
      <FolderKanban className="size-4 shrink-0" />
      <span className="min-w-0 flex-1 truncate">{project.name}</span>
      <ProjectNavIndicator projectId={project.id} status={project.status} />
    </Link>
  )
}

/** Group label from a file's extension (the panel groups files by this). */
function fileType(file: FileRecord): string {
  const ext = (file.source_extension || file.filename.split(".").pop() || "")
    .toLowerCase()
    .replace(/^\./, "")
  return ext ? ext.toUpperCase() : "OTHER"
}

function FileItem({
  file,
  projectId,
  loading,
  onSelect,
}: {
  file: FileRecord
  projectId: string
  loading: boolean
  onSelect: () => void
}) {
  // Split off the extension so a long name elides in the middle
  // ("long-report-name….pdf") and the file type always stays visible.
  const dot = file.filename.lastIndexOf(".")
  const base = dot > 0 ? file.filename.slice(0, dot) : file.filename
  const ext = dot > 0 ? file.filename.slice(dot) : ""
  return (
    <Link
      href={`/projects/${projectId}?file=${file.id}`}
      title={file.filename}
      onClick={onSelect}
      className="flex h-8 items-center gap-2 rounded-md px-3 text-xs font-medium text-sidebar-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
    >
      <FileText className="size-3.5 shrink-0 text-sidebar-foreground/55" />
      <span className="flex min-w-0 flex-1 items-center">
        <span className="truncate">{base}</span>
        {ext && <span className="shrink-0">{ext}</span>}
      </span>
      <span className="flex size-3.5 shrink-0 items-center justify-center">
        {loading && <Spinner size={12} className="text-sidebar-foreground/55" />}
      </span>
    </Link>
  )
}

/** The full sidebar panel — rendered in the desktop column and the mobile drawer. */
function SidebarBody() {
  const pathname = usePathname()
  const [query, setQuery] = useState("")
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set())
  const [loadingFileId, setLoadingFileId] = useState<string | null>(null)

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

  // Briefly spin a file row while the Files tab scrolls to / highlights it.
  useEffect(() => {
    if (!loadingFileId) return
    const timer = setTimeout(() => setLoadingFileId(null), 700)
    return () => clearTimeout(timer)
  }, [loadingFileId])

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

  // Group the project's files by type (PDF, DOCX, …) for collapsible sections.
  const fileGroups = useMemo(() => {
    const map = new Map<string, FileRecord[]>()
    for (const file of filteredFiles) {
      const type = fileType(file)
      const group = map.get(type)
      if (group) group.push(file)
      else map.set(type, [file])
    }
    return [...map.entries()]
      .map(([type, items]) => ({ type, items }))
      .sort((a, b) => a.type.localeCompare(b.type))
  }, [filteredFiles])

  const searching = query.trim().length > 0

  function toggleGroup(type: string) {
    setOpenGroups((prev) => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  return (
    <div className="flex h-full flex-col gap-5 p-4 md:sticky md:top-0 md:h-dvh">
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

        <div className="grid gap-1 overflow-y-auto pr-1 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden max-h-[calc(100dvh-22rem)]">
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
              {fileGroups.map((group) => {
                const open = searching || openGroups.has(group.type)
                return (
                  <div key={group.type}>
                    <button
                      type="button"
                      onClick={() => toggleGroup(group.type)}
                      className="flex h-8 w-full items-center gap-2 rounded-md px-3 text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                    >
                      <ChevronRight
                        className={cn(
                          "size-3 shrink-0 transition-transform",
                          open && "rotate-90"
                        )}
                      />
                      <span className="min-w-0 flex-1 truncate text-left text-[11px] font-medium uppercase tracking-wide">
                        {group.type}
                      </span>
                      <Badge
                        variant="secondary"
                        className="h-5 rounded-md px-1.5 text-[10px]"
                      >
                        {group.items.length}
                      </Badge>
                    </button>
                    {open && (
                      <div className="mt-1 ml-4 grid gap-1 border-l border-sidebar-border pl-2">
                        {group.items.map((file) => (
                          <FileItem
                            key={file.id}
                            file={file}
                            projectId={projectId as string}
                            loading={loadingFileId === file.id}
                            onSelect={() => setLoadingFileId(file.id)}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
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

      <UserMenu />
    </div>
  )
}

export function DashboardSidebar() {
  const pathname = usePathname()
  const [menuOpen, setMenuOpen] = useState(false)

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setMenuOpen(false)
  }, [pathname])

  return (
    <>
      {/* Mobile top bar — hamburger opens the drawer; sidebar is hidden below md */}
      <header className="sticky top-0 z-30 flex items-center gap-2 border-b border-sidebar-border bg-sidebar/95 px-3 py-2 backdrop-blur supports-[backdrop-filter]:bg-sidebar/80 md:hidden">
        <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Open navigation">
              <List className="size-5" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72 p-0">
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            <SheetDescription className="sr-only">
              Browse projects, files, and account settings.
            </SheetDescription>
            <SidebarBody />
          </SheetContent>
        </Sheet>
        <Link href="/dashboard" className="group flex min-w-0 items-center gap-2">
          <span className="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-white shadow-sm ring-1 ring-black/10 dark:bg-black dark:ring-white/15">
            <Image
              src="/logo.png"
              alt="Oreag"
              width={64}
              height={64}
              priority
              className="size-full object-contain dark:invert"
            />
          </span>
          <span className="truncate text-base font-semibold tracking-tight">
            Oreag
          </span>
        </Link>
        <div className="ml-auto">
          <UserMenu compact />
        </div>
      </header>

      {/* Desktop sidebar — fixed left column */}
      <aside className="hidden border-sidebar-border bg-sidebar text-sidebar-foreground md:block md:min-h-dvh md:border-r">
        <SidebarBody />
      </aside>
    </>
  )
}
