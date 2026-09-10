"use client"

import { useRef, useState } from "react"
import Link from "next/link"
import useSWR from "swr"
import { ArrowClockwiseIcon, ArrowRightIcon, HeartbeatIcon, MagnifyingGlassIcon } from "@phosphor-icons/react/dist/ssr"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { MobileFilters } from "@/components/mobile-filters"
import { FilterSelect } from "@/components/filter-select"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { fetcher, isSessionExpired } from "@/lib/api"
import { cn } from "@/lib/utils"
import {
  HEALTH_LABELS, KNOWLEDGE_HEALTH_KEY, healthIssues, healthProjectLink,
  healthSimilarity, healthState, sortedHealthProjects,
  type KnowledgeHealth, type ProjectHealth,
} from "@/lib/knowledge-health"

function StateBadge({ project }: { project: ProjectHealth }) {
  const state = healthState(project)
  return <Badge variant="outline" className={cn("shrink-0", state === "attention" && "border-amber-500/30 text-amber-700 dark:text-amber-400")}>
    {HEALTH_LABELS[state]}
  </Badge>
}

export function KnowledgeHealthLoading() {
  return <div role="status" aria-label="Loading health" className="flex min-h-0 flex-1 flex-col gap-3 md:block md:space-y-4">
    <div className="grid shrink-0 grid-cols-2 gap-2 md:gap-3 lg:grid-cols-4">
      {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-20 animate-none rounded-xl md:h-36" />)}
    </div>
    <Skeleton className="h-9 shrink-0 animate-none rounded-md md:hidden" />
    <Skeleton className="min-h-0 flex-1 animate-none rounded-xl md:h-64" />
  </div>
}

function HealthDetail({ project }: { project: ProjectHealth }) {
  const issues = healthIssues(project)
  return <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-6 pt-2">
    <StateBadge project={project} />
    <dl className="grid grid-cols-2 gap-3">
      {[
        ["Current files", project.current_files], ["Searchable files", project.searchable_files],
        ["Indexed chunks", project.indexed_chunks], ["Identical extra uploads", project.duplicate_copies],
      ].map(([label, value]) => <div key={label} className="min-w-0 rounded-xl border p-3">
        <dt className="text-xs text-muted-foreground">{label}</dt>
        <dd className="mt-2 text-lg font-semibold tabular-nums">{value}</dd>
      </div>)}
    </dl>
    <section className="space-y-2 rounded-xl border p-4">
      <h3 className="text-sm font-medium">Retrieval · Last 30 days</h3>
      <p className="text-2xl font-semibold tabular-nums">{healthSimilarity(project.avg_retrieval_similarity)}</p>
      <p className="text-xs leading-5 text-muted-foreground">Mean similarity across {project.measured_queries} measured, uncached queries. {project.fresh_queries - project.measured_queries} uncached queries have no measurement.</p>
      <p className="text-xs leading-5 text-muted-foreground">Similarity depends on the embedding model and questions asked. It does not measure answer accuracy or prove that the knowledge base is complete.</p>
    </section>
    <div>
      <h3 className="mb-3 text-sm font-medium">Checks and next steps</h3>
      {issues.length ? <ul className="divide-y rounded-xl border">
        {issues.map(issue => <li key={issue.title} className="space-y-2 p-4">
          <h4 className="text-sm font-medium">{issue.title}</h4>
          <p className="text-xs leading-5 text-muted-foreground">{issue.description}</p>
          <Link href={healthProjectLink(project.id, issue.tab)} className="inline-flex items-center gap-1 text-xs font-medium underline underline-offset-4">
            Open {issue.tab}<ArrowRightIcon aria-hidden="true" className="size-3" />
          </Link>
        </li>)}
      </ul> : <p className="rounded-xl border p-4 text-sm text-muted-foreground">No indexing issues detected in the current files. Test representative questions to assess coverage.</p>}
    </div>
    <p className="text-xs leading-5 text-muted-foreground">
      Most recent successful indexing: {project.last_indexed_at ? new Date(project.last_indexed_at).toLocaleString() : "Not recorded"}. This is an indexing timestamp, not a document freshness assessment.
    </p>
    <Button asChild variant="outline"><Link href={healthProjectLink(project.id, "files")}>Open project files<ArrowRightIcon className="size-4" /></Link></Button>
  </div>
}

export function KnowledgeHealthDashboard() {
  const { data, error, isValidating, mutate } = useSWR<KnowledgeHealth>(KNOWLEDGE_HEALTH_KEY, fetcher)
  const [search, setSearch] = useState("")
  const [state, setState] = useState("all")
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const projects = data?.projects ?? []
  const visible = sortedHealthProjects(projects, search, state)
  const selected = projects.find(project => project.id === selectedId)
  const summary = [
    { label: "Need attention", value: projects.filter(project => healthState(project) === "attention").length, detail: "Projects with file issues" },
    { label: "Searchable files", value: projects.reduce((total, project) => total + project.searchable_files, 0), detail: "Current files with indexed chunks" },
    { label: "Queued / indexing", value: projects.reduce((total, project) => total + project.indexing_files, 0), detail: "Files still being processed" },
    { label: "Identical extra uploads", value: projects.reduce((total, project) => total + project.duplicate_copies, 0), detail: "Copies to review within projects" },
  ]
  const statusOptions = [{ value: "all", label: "All statuses" }, ...Object.entries(HEALTH_LABELS).map(([value, label]) => ({ value, label }))]

  return <div className="relative flex h-[calc(100dvh-6.3125rem)] min-h-0 min-w-0 flex-col gap-3 overflow-hidden md:h-full md:gap-4">
    <header className="flex shrink-0 items-start justify-between gap-3 border-b pb-3 md:flex-wrap md:items-center md:pb-4">
      <div className="min-w-0 flex-1">
        <h1 className="text-2xl font-semibold tracking-[-0.035em] md:text-[1.75rem]">Health</h1>
        <p className="mt-1 text-xs text-muted-foreground md:text-sm">Check indexing readiness and find documents that need attention.</p>
      </div>
      <Button size="sm" variant="outline" className="shrink-0" aria-label={isValidating ? "Checking health" : "Refresh health"} disabled={isValidating} onClick={() => void mutate()}>
        <ArrowClockwiseIcon className="size-4" /><span className="hidden md:inline">{isValidating ? "Checking…" : "Refresh"}</span>
      </Button>
    </header>
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden pr-0.5 md:block md:overflow-y-auto md:pb-3">
      {error && !isSessionExpired(error) && <div role="alert" className="mb-4 shrink-0 space-y-2 rounded-xl border p-4 text-sm">
        <p>Could not refresh health data.{data ? " Showing the last available snapshot." : " Please try again."}</p>
        <Button variant="outline" size="sm" onClick={() => void mutate()}>Retry</Button>
      </div>}
      {!data && (!error || isSessionExpired(error)) && <KnowledgeHealthLoading />}
      {data && <div className="flex min-h-0 flex-1 flex-col gap-3 md:block md:space-y-4">
        <div className="grid shrink-0 grid-cols-2 gap-2 md:gap-3 lg:grid-cols-4" aria-label="Health summary">
          {summary.map(metric => <div key={metric.label} className="relative flex min-w-0 flex-col gap-1 rounded-xl border bg-card p-3 md:min-h-36 md:gap-0 md:p-4">
            <p className="text-[11px] font-medium leading-4 text-muted-foreground md:text-xs">{metric.label}</p>
            <p className="break-words text-xl font-semibold tabular-nums md:my-2 md:text-3xl">{metric.value.toLocaleString()}</p>
            <p className="sr-only md:not-sr-only md:mt-auto md:text-xs md:leading-5 md:text-muted-foreground">{metric.detail}</p>
          </div>)}
        </div>
        <div className="flex shrink-0 items-center gap-3 md:flex-wrap">
          <div className="relative min-w-0 flex-1 md:basis-48">
            <MagnifyingGlassIcon aria-hidden="true" className="absolute left-3 top-2.5 size-4 text-muted-foreground" />
            <Input aria-label="Search projects" placeholder="Search projects…" value={search} onChange={event => setSearch(event.target.value)} className="pl-9" />
          </div>
          <MobileFilters title="Health filters" activeCount={state === "all" ? 0 : 1} onReset={() => setState("all")}>
            <FilterSelect label="Health status" value={state} onChange={setState} options={statusOptions} />
          </MobileFilters>
          <div className="hidden md:block md:w-48"><FilterSelect label="Health status" value={state} onChange={setState} options={statusOptions} hideLabel /></div>
        </div>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pb-3 md:space-y-4 md:overflow-visible md:pb-0" role="region" aria-label="Health results" tabIndex={0}>
        <section aria-label="Project health" className="overflow-hidden rounded-xl border bg-card">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
            <h2 className="text-sm font-medium">Projects</h2>
            <span role="status" className="text-xs text-muted-foreground">{visible.length} of {projects.length} · Attention first</span>
          </div>
          {!visible.length ? <div className="space-y-3 px-6 py-12 text-center">
            <HeartbeatIcon className="mx-auto size-7 text-muted-foreground" />
            <p className="text-sm font-medium">{projects.length ? "No projects match these filters" : "No knowledge bases yet"}</p>
            <p className="text-xs text-muted-foreground">{projects.length ? "Try another name or status." : "Create a project and add documents to start checking its readiness."}</p>
            {projects.length ? <Button variant="outline" size="sm" onClick={() => { setSearch(""); setState("all") }}>Reset filters</Button> : <Button asChild variant="outline"><Link href="/projects/new">Create project</Link></Button>}
          </div> : <ul className="divide-y">
            {visible.map(project => <li key={project.id}>
              <button type="button" onClick={event => { triggerRef.current = event.currentTarget; setSelectedId(project.id) }} className="flex w-full min-w-0 flex-col gap-3 px-4 py-4 text-left hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:flex-row sm:items-center sm:gap-6">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{project.name}</p>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">{project.searchable_files} / {project.current_files} current files searchable · {project.indexed_chunks.toLocaleString()} chunks</p>
                  {project.duplicate_copies > 0 && <p className="mt-1 text-xs text-muted-foreground">{project.duplicate_copies} identical extra upload{project.duplicate_copies === 1 ? "" : "s"} to review</p>}
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <StateBadge project={project} />
                  <ArrowRightIcon aria-hidden="true" className="size-4 text-muted-foreground" />
                </div>
              </button>
            </li>)}
          </ul>}
        </section>
        <p className="text-xs leading-5 text-muted-foreground">Current files only; superseded versions are excluded. Readiness reflects indexing status, not answer accuracy. Retrieval measurements cover the last {data.query_window_days} days.</p>
        <p className="text-xs text-muted-foreground">Checked {new Date(data.generated_at).toLocaleString()}</p>
        </div>
      </div>}
    </div>
    <Sheet open={selectedId !== null} onOpenChange={open => { if (!open) setSelectedId(null) }}>
      <SheetContent side="right" className="w-full max-w-full bg-background sm:w-[540px]" onCloseAutoFocus={event => { event.preventDefault(); triggerRef.current?.focus() }}>
        <SheetHeader className="p-6 pr-12">
          <SheetTitle className="break-words text-lg">{selected?.name ?? "Project health"}</SheetTitle>
          <SheetDescription>Readiness checks and next steps for this knowledge base.</SheetDescription>
        </SheetHeader>
        {selected ? <HealthDetail project={selected} /> : <p className="p-6 text-sm text-muted-foreground">This project is no longer in the current report.</p>}
      </SheetContent>
    </Sheet>
  </div>
}
