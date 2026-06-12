"use client"

import { FileText, Plus } from "lucide-react"
import Link from "next/link"
import useSWR from "swr"

import { StatusBadge } from "@/components/status-badge"
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

export default function DashboardPage() {
  const { data: projects, error, isLoading } = useSWR<Project[]>(
    "/api/projects",
    fetcher
  )

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Your RAG projects</h1>
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
                    <StatusBadge status={project.status} />
                  </div>
                  {project.description && (
                    <CardDescription className="line-clamp-2">
                      {project.description}
                    </CardDescription>
                  )}
                </CardHeader>
                <CardContent className="text-sm text-muted-foreground">
                  {project.file_count} file{project.file_count === 1 ? "" : "s"}{" "}
                  · {project.chunk_count} chunks ·{" "}
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
