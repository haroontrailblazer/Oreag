"use client"

import { CircleNotch as Loader2 } from "@phosphor-icons/react/dist/ssr"
import { useSearchParams } from "next/navigation"
import { use, useEffect, useState } from "react"
import useSWR from "swr"

import { ApiTab } from "@/components/project/api-tab"
import { FilesTab } from "@/components/project/files-tab"
import { MemoryTab } from "@/components/project/memory-tab"
import { PlaygroundTab } from "@/components/project/playground-tab"
import { SettingsTab } from "@/components/project/settings-tab"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { fetcher } from "@/lib/api"
import type { Project } from "@/lib/types"

const TAB_VALUES = ["files", "playground", "api", "memory", "settings"]

export default function ProjectPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const searchParams = useSearchParams()
  const selectedFileId = searchParams.get("file")
  const tabParam = searchParams.get("tab")

  // ?file=<id> opens Files on that file; ?tab=<name> deep-links to a tab (e.g.
  // the "Manage" button in Settings → API keys opens this project's Settings).
  const [tab, setTab] = useState(
    !selectedFileId && tabParam && TAB_VALUES.includes(tabParam)
      ? tabParam
      : "files"
  )

  useEffect(() => {
    if (selectedFileId) setTab("files")
    else if (tabParam && TAB_VALUES.includes(tabParam)) setTab(tabParam)
  }, [selectedFileId, tabParam])

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
    return (
      <div className="space-y-6">
        {/* header: title + meta line */}
        <div className="space-y-2">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-4 w-80 max-w-full" />
        </div>
        {/* tabs bar + active tab content */}
        <div className="space-y-4">
          <Skeleton className="h-9 w-full max-w-sm rounded-lg" />
          <Skeleton className="h-72 rounded-xl" />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">{project.name}</h1>
        {project.status === "indexing" && (
          <Loader2
            className="size-4 animate-spin text-muted-foreground"
            aria-label="Rendering"
          />
        )}
        <span className="text-sm text-muted-foreground">
          {project.file_count} files · {project.chunk_count} chunks ·{" "}
          {project.embedding_provider}/{project.embedding_model} ·{" "}
          {project.llm_provider}/{project.llm_model}
        </span>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="files">Files</TabsTrigger>
          <TabsTrigger value="playground">Playground</TabsTrigger>
          <TabsTrigger value="api">API</TabsTrigger>
          <TabsTrigger value="memory">Memory</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>
        <TabsContent value="files" className="mt-4">
          <FilesTab
            project={project}
            onChanged={() => mutate()}
            selectedFileId={selectedFileId}
          />
        </TabsContent>
        <TabsContent value="playground" className="mt-4">
          <PlaygroundTab project={project} />
        </TabsContent>
        <TabsContent value="api" className="mt-4">
          <ApiTab project={project} />
        </TabsContent>
        <TabsContent value="memory" className="mt-4">
          <MemoryTab project={project} />
        </TabsContent>
        <TabsContent value="settings" className="mt-4">
          <SettingsTab project={project} onChanged={() => mutate()} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
