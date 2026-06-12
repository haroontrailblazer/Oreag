"use client"

import { use } from "react"
import useSWR from "swr"

import { ApiTab } from "@/components/project/api-tab"
import { FilesTab } from "@/components/project/files-tab"
import { PlaygroundTab } from "@/components/project/playground-tab"
import { SettingsTab } from "@/components/project/settings-tab"
import { StatusBadge } from "@/components/status-badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { fetcher } from "@/lib/api"
import type { Project } from "@/lib/types"

export default function ProjectPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const {
    data: project,
    error,
    mutate,
  } = useSWR<Project>(`/api/projects/${id}`, fetcher, {
    refreshInterval: (latest) =>
      latest?.status === "indexing" ? 3000 : 0,
  })

  if (error) {
    return (
      <p className="text-sm text-destructive">
        Could not load project: {error.message}
      </p>
    )
  }
  if (!project) {
    return <Skeleton className="h-64" />
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">{project.name}</h1>
        <StatusBadge status={project.status} />
        <span className="text-sm text-muted-foreground">
          {project.file_count} files · {project.chunk_count} chunks ·{" "}
          {project.embedding_provider}/{project.embedding_model} ·{" "}
          {project.llm_provider}/{project.llm_model}
        </span>
      </div>

      <Tabs defaultValue="files">
        <TabsList>
          <TabsTrigger value="files">Files</TabsTrigger>
          <TabsTrigger value="playground">Playground</TabsTrigger>
          <TabsTrigger value="api">API</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>
        <TabsContent value="files" className="mt-4">
          <FilesTab project={project} onChanged={() => mutate()} />
        </TabsContent>
        <TabsContent value="playground" className="mt-4">
          <PlaygroundTab project={project} />
        </TabsContent>
        <TabsContent value="api" className="mt-4">
          <ApiTab project={project} />
        </TabsContent>
        <TabsContent value="settings" className="mt-4">
          <SettingsTab project={project} onChanged={() => mutate()} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
