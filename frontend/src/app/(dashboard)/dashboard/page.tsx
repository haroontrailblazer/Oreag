"use client"

import { FileText, Plus } from "@phosphor-icons/react/dist/ssr"
import Link, { useLinkStatus } from "next/link"
import { useEffect, type CSSProperties } from "react"
import useSWR, { preload } from "swr"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { fetcher } from "@/lib/api"
import { useProjectNavPending } from "@/lib/nav-pending"
import type { Project } from "@/lib/types"

// Spinning glow colour per status - only the outline changes, text stays white.
const STATUS_GLOW: Record<Project["status"], string> = {
  empty: "#9ca3af",
  indexing: "#eab308",
  ready: "#22c55e",
  error: "#ef4444",
}

function StatusButton({
  status,
  suspended,
}: {
  status: Project["status"]
  suspended?: boolean
}) {
  // A suspended project reads "suspended" (amber) regardless of index state.
  const label = suspended ? "suspended" : status
  const glow = suspended ? "#f59e0b" : STATUS_GLOW[status]
  return (
    <span
      className="status-btn shrink-0 capitalize"
      style={{ "--glow": glow } as CSSProperties}
    >
      <span>{label}</span>
    </span>
  )
}

/**
 * Shows the spinner in the card corner while the clicked card's navigation is
 * in flight. Must be rendered inside its <Link> for useLinkStatus to read it.
 */
function CardNavSpinner({ projectId }: { projectId: string }) {
  const { pending } = useLinkStatus()
  const navigating = useProjectNavPending(projectId, pending)
  if (!navigating) return null
  return (
    <Spinner
      size={22}
      className="absolute bottom-6 right-6 text-muted-foreground"
    />
  )
}

function StatNum({ children }: { children: number }) {
  return <span className="text-sm font-medium text-foreground">{children}</span>
}

function StatUnit({ children }: { children: string }) {
  return (
    <span className="ml-1 text-[11px] uppercase tracking-wider text-muted-foreground">
      {children}
    </span>
  )
}

function StatDot() {
  return <span className="mx-2 text-muted-foreground/40">·</span>
}

/** One run of the ticker. Monospace + tabular-nums keeps digit columns from
 *  jittering as it scrolls; leading-5 fixes the line box so the card's vertical
 *  rhythm is unchanged. */
function CardStats({ project }: { project: Project }) {
  return (
    <span className="whitespace-nowrap font-mono leading-5 tabular-nums">
      <StatNum>{project.file_count}</StatNum>
      <StatUnit>{`file${project.file_count === 1 ? "" : "s"}`}</StatUnit>
      <StatDot />
      <StatNum>{project.chunk_count}</StatNum>
      <StatUnit>{`chunk${project.chunk_count === 1 ? "" : "s"}`}</StatUnit>
      <StatDot />
      <StatNum>{project.query_count}</StatNum>
      <StatUnit>{`quer${project.query_count === 1 ? "y" : "ies"}`}</StatUnit>
      <StatDot />
      <span className="text-sm text-foreground/70">
        {new Date(project.created_at).toLocaleDateString()}
      </span>
    </span>
  )
}

export default function DashboardPage() {
  const { data: projects, error, isLoading } = useSWR<Project[]>(
    "/api/projects",
    fetcher
  )

  // Warm the Settings → API keys page in the background so opening it is
  // instant instead of fetching on click. Its other dataset (/api/projects) is
  // already loaded above; only the provider keys still need fetching.
  useEffect(() => {
    preload("/api/provider-keys", fetcher)
  }, [])

  // Fixed frame like the project and API keys pages: the heading row never
  // moves, only the cards area scrolls (mobile chrome ~6.25rem, desktop
  // p-8 = 4rem).
  return (
    <div className="flex h-[calc(100dvh-6.25rem)] min-h-0 flex-col gap-6 overflow-hidden md:h-full">
      <div className="flex shrink-0 items-center justify-between">
        <h1 className="text-2xl font-semibold">Projects</h1>
        <Button asChild>
          <Link href="/projects/new">
            <Plus className="size-4" /> New project
          </Link>
        </Button>
      </div>

      {error && (
        <p className="shrink-0 text-sm text-destructive">
          Could not load projects: {error.message}
        </p>
      )}

      {isLoading && (
        <div className="grid min-h-0 flex-1 grid-cols-1 content-start gap-4 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      )}

      {projects && projects.length === 0 && (
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          {/* my-auto (not justify-center) so the card centers in the free
              space but can still scroll from the top on short viewports. */}
          <Card className="my-auto py-16 text-center">
            <CardContent className="space-y-3">
              <FileText className="mx-auto size-10 text-muted-foreground" />
              <p className="text-muted-foreground">
                No projects yet. Create one to turn your documents into an API.
              </p>
              <Button asChild>
                <Link href="/projects/new">Create your first project</Link>
              </Button>
            </CardContent>
          </Card>
        </div>
      )}

      {projects && projects.length > 0 && (
        <div className="grid min-h-0 flex-1 grid-cols-1 content-start gap-4 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
            <Link
              key={project.id}
              href={`/projects/${project.id}`}
              prefetch={false}
              className="group"
            >
              <Card className="relative h-full transition-shadow hover:shadow-md">
                <CardHeader>
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle className="truncate">{project.name}</CardTitle>
                    <StatusButton
                      status={project.status}
                      suspended={project.suspended}
                    />
                  </div>
                  {project.description && (
                    <CardDescription className="line-clamp-2">
                      {project.description}
                    </CardDescription>
                  )}
                </CardHeader>
                <CardContent className="mt-auto text-sm text-muted-foreground">
                  {/* Ticker-tape stats, pinned to the card bottom (mt-auto) so
                      the line aligns across cards regardless of description
                      length. mono tabular numbers pop against the uppercase
                      units; edges fade (ticker-mask); mr-8 keeps the scroll
                      clear of the nav spinner. Pauses on hover. */}
                  <div className="ticker-mask mr-8 overflow-hidden">
                    <div className="flex w-max animate-[marquee_16s_linear_infinite] group-hover:[animation-play-state:paused] motion-reduce:animate-none">
                      <span className="shrink-0 pr-6">
                        <CardStats project={project} />
                      </span>
                      <span aria-hidden="true" className="shrink-0 pr-6">
                        <CardStats project={project} />
                      </span>
                    </div>
                  </div>
                </CardContent>
                <CardNavSpinner projectId={project.id} />
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
