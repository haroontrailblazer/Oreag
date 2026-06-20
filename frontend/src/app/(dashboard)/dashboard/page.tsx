"use client"

import { FileText, Plus } from "@phosphor-icons/react/dist/ssr"
import Link, { useLinkStatus } from "next/link"
import useSWR from "swr"

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
import type { Project } from "@/lib/types"
import { cn } from "@/lib/utils"

const STATUS_TONE: Record<Project["status"], string> = {
  empty: "bg-muted text-muted-foreground",
  indexing:
    "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
  ready:
    "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400",
  error: "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-400",
}

function StatusPill({ status }: { status: Project["status"] }) {
  return (
    <span
      className={cn(
        "shrink-0 rounded-full px-2 py-0.5 text-xs font-medium capitalize",
        STATUS_TONE[status]
      )}
    >
      {status}
    </span>
  )
}

/**
 * Shows the spinner in the card corner while the clicked card's navigation is
 * in flight. Must be rendered inside its <Link> for useLinkStatus to read it.
 */
function CardNavSpinner() {
  const { pending } = useLinkStatus()
  if (!pending) return null
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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Projects</h1>
        <Button asChild>
          <Link href="/projects/new">
            <Plus className="size-4" /> New project
          </Link>
        </Button>
      </div>

      {error && (
        <p className="text-sm text-destructive">
          Could not load projects: {error.message}
        </p>
      )}

      {isLoading && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      )}

      {projects && projects.length === 0 && (
        <Card className="py-16 text-center">
          <CardContent className="space-y-3">
            <FileText weight="duotone" className="mx-auto size-10 text-muted-foreground" />
            <p className="text-muted-foreground">
              No projects yet. Create one to turn your PDFs into an API.
            </p>
            <Button asChild>
              <Link href="/projects/new">Create your first project</Link>
            </Button>
          </CardContent>
        </Card>
      )}

      {projects && projects.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
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
                    <StatusPill status={project.status} />
                  </div>
                  {project.description && (
                    <CardDescription className="line-clamp-2">
                      {project.description}
                    </CardDescription>
                  )}
                </CardHeader>
                <CardContent className="text-sm text-muted-foreground">
                  {/* Ticker-tape stats: mono tabular numbers pop against the
                      uppercase units; edges fade (ticker-mask); mr-8 keeps the
                      scroll clear of the nav spinner; single line keeps the
                      original vertical spacing. Pauses on hover. */}
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
                <CardNavSpinner />
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
