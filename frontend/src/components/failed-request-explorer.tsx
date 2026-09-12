"use client"

import { useEffect, useRef, useState, type ReactNode } from "react"
import Link from "next/link"
import useSWR from "swr"
import { ArrowRightIcon, ArrowsClockwiseIcon, CopyIcon, MagnifyingGlassIcon, WarningCircleIcon } from "@phosphor-icons/react/dist/ssr"
import { toast } from "sonner"
import { fetcher, isSessionExpired } from "@/lib/api"
import { DEFAULT_FAILURE_FILTERS, FAILURE_KEY, FAILURE_OUTCOMES, FAILURE_PERIODS, failureGuidance, failureKey, type FailedRequest, type FailureFilters, type FailurePage } from "@/lib/request-failures"
import { queryLatency } from "@/lib/query-explorer"
import type { Project } from "@/lib/types"
import { cn } from "@/lib/utils"
import { FilterSelect } from "@/components/filter-select"
import { MobileFilters } from "@/components/mobile-filters"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"

const dateLabel = (value: string) => new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
const duration = (value: number | null) => queryLatency(value == null ? null : Math.round(value))

function OutcomeBadge({ record }: { record: FailedRequest }) {
  const state = FAILURE_OUTCOMES[record.outcome]
  return <Badge variant="outline" className={cn("text-[11px]", state.className)}>{state.label}</Badge>
}

function FailureRowsSkeleton() {
  return <div role="status" aria-label="Loading failed requests" className="divide-y">{Array.from({ length: 5 }, (_, index) => <div key={index} className="space-y-3 p-4"><Skeleton className="h-4 w-4/5" /><Skeleton className="h-3 w-48 max-w-full" /><Skeleton className="h-5 w-24" /></div>)}</div>
}

function FailureDetail({ id }: { id: string }) {
  const { data, error, mutate } = useSWR<FailedRequest>(`${FAILURE_KEY}/${id}`, fetcher, { revalidateOnFocus: false })
  if (error && !isSessionExpired(error)) return <div role="alert" className="space-y-3 px-6 pb-6 text-sm"><p>Could not load this request. The record may no longer be retained.</p><Button variant="outline" size="sm" onClick={() => void mutate()}>Retry</Button></div>
  if (!data) return <div role="status" aria-label="Loading request details" className="space-y-4 px-6"><Skeleton className="h-20 w-full" /><Skeleton className="h-48 w-full" /></div>
  const guidance = failureGuidance(data)
  async function copyDetails() {
    try {
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2))
      toast.success("Request details copied")
    } catch { toast.error("Could not copy request details") }
  }
  return <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-6 pb-6">
    <div className="space-y-2"><div className="flex flex-wrap items-center gap-2"><OutcomeBadge record={data} /><span className="text-xs tabular-nums text-muted-foreground">HTTP {data.status_code}</span></div><p className="text-xs text-muted-foreground">{dateLabel(data.created_at)}</p><p className="break-words text-sm font-medium">{data.project_name ?? "Project not recorded"}</p></div>
    <section className="space-y-2"><h3 className="text-xs font-medium text-muted-foreground">Endpoint</h3><p className="break-all rounded-xl border bg-background p-4 font-mono text-xs leading-6">{data.endpoint}</p></section>
    <dl className="grid grid-cols-2 gap-3">{[["Duration", duration(data.latency_ms)], ["First token", duration(data.first_token_ms)], ["HTTP status", String(data.status_code)], ["Record ID", data.id]].map(([label, value]) => <div key={label} className="min-w-0 rounded-xl border p-3"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-2 break-words text-sm font-medium tabular-nums">{value}</dd></div>)}</dl>
    <section className="space-y-3 rounded-xl border p-4"><h3 className="flex items-center gap-2 text-sm font-medium"><WarningCircleIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />What happened</h3><p className="text-xs leading-5 text-muted-foreground">{guidance.summary}</p><p className="text-xs leading-5 text-muted-foreground">The original error message was not saved in this record.</p></section>
    <section className="space-y-3"><h3 className="text-sm font-medium">What to check next</h3><ul className="list-disc space-y-2 pl-4 text-xs leading-5 text-muted-foreground">{guidance.steps.map(step => <li key={step}>{step}</li>)}</ul></section>
    <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={() => void copyDetails()}><CopyIcon aria-hidden="true" />Copy details</Button><Button size="sm" variant="outline" asChild><Link href="/settings/usage#operations">View operations<ArrowRightIcon aria-hidden="true" /></Link></Button>{data.project_id && <Button size="sm" variant="outline" asChild><Link href={`/projects/${encodeURIComponent(data.project_id)}`}>Open project<ArrowRightIcon aria-hidden="true" /></Link></Button>}</div>
    <p className="text-xs leading-5 text-muted-foreground">Record ID identifies this telemetry entry. It is separate from query IDs and trace IDs. Request bodies, credentials, and response text are not retained here.</p>
  </div>
}

export function FailedRequestExplorer({ navigation }: { navigation: ReactNode }) {
  const [filters, setFilters] = useState<FailureFilters>(DEFAULT_FAILURE_FILTERS)
  const [search, setSearch] = useState("")
  const [cursors, setCursors] = useState<string[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const { data: projects, error: projectsError } = useSWR<Project[]>("/api/projects", fetcher)
  const { data, error, isLoading, isValidating, mutate } = useSWR<FailurePage>(failureKey(filters, cursors.at(-1)), fetcher, {
    refreshInterval: cursors.length || selected ? 0 : 30_000, revalidateOnFocus: false,
    refreshWhenHidden: false, refreshWhenOffline: false,
  })
  useEffect(() => {
    if (search === filters.search) return
    const timer = window.setTimeout(() => { setFilters(current => current.search === search ? current : { ...current, search }); setCursors(current => current.length ? [] : current) }, 300)
    return () => window.clearTimeout(timer)
  }, [search, filters.search])
  function changeFilter(key: keyof FailureFilters, value: string) { setFilters(current => ({ ...current, [key]: value })); setCursors([]) }
  function reset() { setFilters(DEFAULT_FAILURE_FILTERS); setSearch(""); setCursors([]) }
  const filterCount = (["hours", "project", "outcome", "status", "latency"] as const).filter(key => filters[key] !== DEFAULT_FAILURE_FILTERS[key]).length
  const filtered = !!filterCount || !!search
  const filterControls = <div className="space-y-4"><div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
    <FilterSelect label="Project" value={filters.project} onChange={value => changeFilter("project", value)} options={[{ value: "", label: "All projects" }, ...(projects ?? []).map(project => ({ value: project.id, label: project.name }))]} />
    <FilterSelect label="Time range" value={filters.hours} onChange={value => changeFilter("hours", value)} options={FAILURE_PERIODS} />
    <FilterSelect label="Outcome" value={filters.outcome} onChange={value => changeFilter("outcome", value)} options={[{ value: "all", label: "All failures" }, ...Object.entries(FAILURE_OUTCOMES).map(([value, state]) => ({ value, label: state.label }))]} />
    <FilterSelect label="HTTP status" value={filters.status} onChange={value => changeFilter("status", value)} options={[{ value: "", label: "Any status" }, ...[200, 400, 401, 403, 404, 408, 409, 413, 415, 422, 429, 500, 502, 503, 504].map(code => ({ value: String(code), label: `HTTP ${code}` }))]} />
    <FilterSelect label="Duration" value={filters.latency} onChange={value => changeFilter("latency", value)} options={[{ value: "", label: "Any duration" }, { value: "1000", label: "At least 1 second" }, { value: "3000", label: "At least 3 seconds" }, { value: "10000", label: "At least 10 seconds" }]} />
  </div>{projectsError && !isSessionExpired(projectsError) && <p className="text-xs text-destructive">Project filters could not load. You can still search across all projects.</p>}</div>

  return <div className="flex h-[calc(100dvh-6.25rem)] min-h-0 min-w-0 flex-col gap-4 md:h-full">
    <header className="grid shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 border-b pb-4">
      <h1 className="text-[1.75rem] font-semibold tracking-[-0.035em]">Queries</h1>
      <div role="search" aria-label="Search and filter failed requests" className="flex w-[min(52vw,16rem)] min-w-0 items-center gap-2"><div className="relative min-w-0 flex-1"><MagnifyingGlassIcon className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" /><Input aria-label="Search endpoints" placeholder="Search endpoints…" maxLength={200} value={search} onChange={event => setSearch(event.target.value)} className="h-8 pl-8 pr-2 text-base placeholder:text-[13px] md:text-[13px]" /></div><MobileFilters title="Failed request filters" activeCount={filterCount} onReset={reset} desktop compact>{filterControls}</MobileFilters></div>
      <p className="col-span-2 text-xs text-muted-foreground md:text-sm">Inspect rejected requests, server errors, and interrupted streams.</p>
    </header>
    <div className="shrink-0">{navigation}</div>
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pb-3 pr-0.5">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground"><p className="min-w-0 flex-1 break-words leading-5">{FAILURE_PERIODS.find(period => period.value === filters.hours)?.label}{filters.project ? ` · ${projects?.find(project => project.id === filters.project)?.name ?? "Selected project"}` : ""} · {filters.outcome === "all" ? "All failures" : FAILURE_OUTCOMES[filters.outcome as keyof typeof FAILURE_OUTCOMES].label}{filters.status ? ` · HTTP ${filters.status}` : ""}{filters.latency ? ` · At least ${Number(filters.latency) / 1000} s` : ""}</p><Button size="sm" variant="outline" disabled={isValidating} onClick={() => { if (cursors.length) setCursors([]); else void mutate() }}><ArrowsClockwiseIcon className={cn("size-3.5", isValidating && "motion-safe:animate-spin")} aria-hidden="true" />Refresh</Button></div>
      {error && !isSessionExpired(error) && <div role="alert" className="flex shrink-0 flex-wrap items-center justify-between gap-3 rounded-xl border p-4 text-xs"><p>Could not refresh failed requests.{data ? " Showing the last available snapshot." : " Please try again."}</p><Button variant="outline" size="sm" onClick={() => void mutate()}>Retry</Button></div>}
      <section aria-label="Failed request results" aria-busy={isLoading} className="flex max-h-full min-h-0 flex-col overflow-hidden rounded-xl border bg-card">
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b px-4 py-3"><h2 className="flex items-center gap-2 text-sm font-medium"><WarningCircleIcon className="size-4 text-muted-foreground" aria-hidden="true" />Failed requests</h2><span role="status" className="text-xs text-muted-foreground">{data ? `${data.items.length} on this page · Newest first` : error ? "Records unavailable" : "Loading records…"}</span></div>
        <div className="min-h-0 overflow-y-auto">
          {!data ? !error || isSessionExpired(error) ? <FailureRowsSkeleton /> : <p className="p-6 text-sm text-muted-foreground">Use Retry to load the request records.</p>
            : !data.items.length ? <div className="space-y-3 px-6 py-12 text-center"><MagnifyingGlassIcon className="mx-auto size-7 text-muted-foreground" aria-hidden="true" /><h3 className="text-sm font-medium">{filtered ? "No failed requests match these filters" : "No failed requests recorded in this period"}</h3><p className="mx-auto max-w-sm text-xs leading-5 text-muted-foreground">{filtered ? "Try another endpoint, a wider time range, or reset the filters." : "Recorded rejections, errors, and interrupted responses will appear here."}</p>{filtered && <Button variant="outline" size="sm" onClick={reset}>Reset filters</Button>}</div>
            : <ul className="divide-y">{data.items.map(record => <li key={record.id}><button type="button" className="group flex w-full min-w-0 flex-col gap-3 p-4 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:flex-row sm:items-center sm:gap-6" onClick={event => { triggerRef.current = event.currentTarget; setSelected(record.id) }}><div className="min-w-0 flex-1"><p className="line-clamp-2 break-all font-mono text-xs leading-6">{record.endpoint}</p><p className="mt-1 truncate text-xs text-muted-foreground">{record.project_name ?? "Project not recorded"} · {dateLabel(record.created_at)}</p></div><div className="flex shrink-0 flex-wrap items-center gap-3"><OutcomeBadge record={record} /><span className="text-xs tabular-nums text-muted-foreground">HTTP {record.status_code}</span><span className="text-xs tabular-nums text-muted-foreground sm:w-16 sm:text-right">{duration(record.latency_ms)}</span><ArrowRightIcon className="ml-auto size-4 text-muted-foreground" aria-hidden="true" /></div></button></li>)}</ul>}
        </div>
        <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t px-4 py-3"><span className="text-xs text-muted-foreground">Page {cursors.length + 1}</span><div className="flex gap-2"><Button size="sm" variant="outline" disabled={!cursors.length || isLoading} onClick={() => setCursors(current => current.slice(0, -1))}>Previous</Button><Button size="sm" variant="outline" disabled={!data?.next_cursor || isLoading || !!error || search !== filters.search} onClick={() => { if (data?.next_cursor) setCursors(current => [...current, data.next_cursor!]) }}>Next</Button></div></footer>
      </section>
      <details className="shrink-0 px-1 text-xs leading-5 text-muted-foreground"><summary className="w-fit cursor-pointer rounded-sm font-medium text-foreground focus-visible:outline-2">About these records</summary><div className="mt-2 space-y-2"><p>Shows recorded authenticated API and project requests. Includes HTTP errors and streams that failed or were interrupted after starting. Unauthenticated requests that cannot be linked to your account are excluded.</p><p>Measurements arrive asynchronously and may be missing during overload. Records follow the configured retention period{data ? ` (${data.retention_days} days)` : ""}. An empty list means no matching records, not a guarantee that every request succeeded.</p><p>Endpoints show route templates, not raw URLs. Request bodies, credentials, and original error messages are not stored. Times are shown in your local timezone. Project filters require recorded project attribution.</p>{data && <p>Snapshot: {dateLabel(data.as_of)}. Older pages keep this time range; Refresh returns to the latest records.</p>}</div></details>
    </div>
    <Sheet open={selected !== null} onOpenChange={open => { if (!open) setSelected(null) }}><SheetContent side="right" className="w-full max-w-full bg-background sm:w-[540px]" onCloseAutoFocus={event => { event.preventDefault(); triggerRef.current?.focus() }}><SheetHeader className="p-6 pr-12"><SheetTitle className="text-lg">Failed request details</SheetTitle><SheetDescription>Recorded outcome, timing, and suggested next checks.</SheetDescription></SheetHeader>{selected && <FailureDetail key={selected} id={selected} />}</SheetContent></Sheet>
  </div>
}
