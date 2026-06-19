"use client"

import { FileText, Plus } from "@phosphor-icons/react/dist/ssr"
import Link from "next/link"
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
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      )}

      {projects && projects.length === 0 && (
        <Card className="py-16 text-center">
          <CardContent className="space-y-3">
            <FileText className="mx-auto size-10 text-muted-foreground" />
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
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
            <Link key={project.id} href={`/projects/${project.id}`}>
              <Card className="h-full transition-shadow hover:shadow-md">
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
                  {project.file_count} file{project.file_count === 1 ? "" : "s"}{" "}
                  · {project.chunk_count} chunks · {project.query_count} quer
                  {project.query_count === 1 ? "y" : "ies"} ·{" "}
                  {new Date(project.created_at).toLocaleDateString()}
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
