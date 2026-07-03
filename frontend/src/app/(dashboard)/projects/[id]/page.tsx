"use client"

import { useSearchParams } from "next/navigation"
import { use, useEffect, useState } from "react"
import useSWR, { mutate as globalMutate } from "swr"

import { ApiTab } from "@/components/project/api-tab"
import { FilesTab } from "@/components/project/files-tab"
import { MemoryTab } from "@/components/project/memory-tab"
import { PlaygroundTab } from "@/components/project/playground-tab"
import { SettingsTab } from "@/components/project/settings-tab"
import { VisualizeTab } from "@/components/project/visualize-tab"
import { SquaresLoader } from "@/components/ui/squares-loader"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { fetcher } from "@/lib/api"
import type { Project } from "@/lib/types"

const TAB_VALUES = [
  "files",
  "memory",
  "playground",
  "api",
  "visualize",
  "settings",
]

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

  // Let the active (Files) tab paint and fetch first, then quietly mount the
  // remaining tabs in the background so switching to them is instant — without
  // this, each tab only fetches its data the first time it's clicked.
  const [prefetchTabs, setPrefetchTabs] = useState(false)
  useEffect(() => {
    const timer = setTimeout(() => setPrefetchTabs(true), 150)
    return () => clearTimeout(timer)
  }, [])
  const mountAll = prefetchTabs ? true : undefined

  const {
    data: project,
    error,
    mutate,
  } = useSWR<Project>(`/api/projects/${id}`, fetcher, {
    refreshInterval: (latest) =>
      latest?.status === "indexing" ? 3000 : 0,
  })

  // Push this project's live data into the dashboard's cached "/api/projects"
  // list so any change made here — deleting files, indexing progress, indexing
  // finishing, name/stat updates — is already reflected when the user navigates
  // back, instead of showing a stale card until a manual refresh. Patches the
  // list in place (no refetch); if it isn't cached yet, the dashboard fetches
  // it normally.
  useEffect(() => {
    if (!project) return
    globalMutate<Project[]>(
      "/api/projects",
      (list) =>
        list ? list.map((p) => (p.id === project.id ? project : p)) : list,
      { revalidate: false }
    )
  }, [project])

  // Refresh this project and the dashboard's project list together after any
  // in-project change. The list backs the Settings → API keys "Project key
  // overrides" table, so adding/removing a project-level key here shows up
  // there immediately — no manual refresh, even if the list wasn't cached yet.
  function handleChanged() {
    mutate()
    globalMutate("/api/projects")
  }

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
          <SquaresLoader size={4} className="text-muted-foreground" />
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
          <TabsTrigger value="memory">Memory</TabsTrigger>
          <TabsTrigger value="playground">Playground</TabsTrigger>
          <TabsTrigger value="api">API</TabsTrigger>
          <TabsTrigger value="visualize">Visualize</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>
        <TabsContent value="files" className="mt-4" forceMount={mountAll}>
          <FilesTab
            project={project}
            onChanged={handleChanged}
            selectedFileId={selectedFileId}
          />
        </TabsContent>
        <TabsContent value="memory" className="mt-4" forceMount={mountAll}>
          <MemoryTab project={project} />
        </TabsContent>
        <TabsContent value="playground" className="mt-4" forceMount={mountAll}>
          <PlaygroundTab project={project} />
        </TabsContent>
        <TabsContent value="api" className="mt-4" forceMount={mountAll}>
          <ApiTab project={project} />
        </TabsContent>
        {/* No forceMount: the 3D canvas (WebGL) only spins up when opened. */}
        <TabsContent value="visualize" className="mt-4">
          <VisualizeTab project={project} />
        </TabsContent>
        <TabsContent value="settings" className="mt-4" forceMount={mountAll}>
          <SettingsTab project={project} onChanged={handleChanged} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
