"use client"

import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import useSWR from "swr"
import { ArrowClockwiseIcon, ArrowRightIcon, MagnifyingGlassIcon } from "@phosphor-icons/react/dist/ssr"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { QueryDetailSkeleton, QueryRowsSkeleton } from "@/components/query-explorer-loading"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { fetcher, isSessionExpired } from "@/lib/api"
import { DEFAULT_QUERY_FILTERS, queryCacheLabel, queryExplorerKey, queryLatency, querySimilarity, type QueryFilters, type QueryPage, type QueryRecord } from "@/lib/query-explorer"
import type { Project } from "@/lib/types"

function Filter({ label, value, onChange, children }: { label: string; value: string; onChange: (value: string) => void; children: React.ReactNode }) {
  return <label className="flex min-w-0 flex-col gap-1.5 text-xs text-muted-foreground">
    {label}
    <select value={value} onChange={event => onChange(event.target.value)} className="h-9 w-full min-w-0 rounded-md border border-input bg-background px-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {children}
    </select>
  </label>
}

function dateLabel(value: string) { return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) }

function QueryDetail({ id }: { id: string }) {
  const { data, error, isLoading, mutate } = useSWR<QueryRecord>(`/api/account/queries/${id}`, fetcher)
  if (error && !isSessionExpired(error)) return <div className="p-6 text-sm" role="alert">Could not load this query. It may have been deleted.<Button variant="outline" className="mt-3 block" onClick={() => void mutate()}>Retry</Button></div>
  if (isLoading || !data) return <QueryDetailSkeleton />
  const metrics = [
    ["Latency", queryLatency(data.latency_ms)], ["Cache", queryCacheLabel(data.cache_layer)],
    ["Retrieval similarity", querySimilarity(data.retrieval_similarity)], ["Cache similarity", querySimilarity(data.cache_similarity)],
    ["Requested top K", data.top_k ?? "Not recorded"], ["Query ID", data.id],
  ]
  return <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-6 pt-2">
    <div><p className="text-xs text-muted-foreground">{dateLabel(data.created_at)}</p><p className="mt-1 break-words text-sm font-medium">{data.project_name}</p></div>
    <section><h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">Question</h3><p className="whitespace-pre-wrap break-words rounded-xl border bg-background p-4 text-sm leading-7">{data.question}</p></section>
    <dl className="grid grid-cols-2 gap-3">{metrics.map(([label, value]) => <div key={label} className="min-w-0 rounded-xl border bg-background p-3"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-2 break-words text-sm font-medium tabular-nums">{value}</dd></div>)}</dl>
    <p className="text-xs leading-5 text-muted-foreground">Retrieval similarity is the mean similarity of the retrieved chunks. Cache similarity measures the semantic cache match. Unavailable measurements remain unreported.</p>
    <div className="rounded-xl border p-4 text-sm leading-6 text-muted-foreground">Historical answers and source text are not retained in these query logs.</div>
    <Button asChild variant="outline"><Link href={`/projects/${encodeURIComponent(data.project_id)}`}>Open project<ArrowRightIcon className="size-4" /></Link></Button>
  </div>
}

export function QueryExplorer() {
  const [filters, setFilters] = useState<QueryFilters>(DEFAULT_QUERY_FILTERS)
  const [search, setSearch] = useState("")
  const [cursors, setCursors] = useState<string[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const { data: projects, error: projectsError } = useSWR<Project[]>("/api/projects", fetcher)
  const { data, error, isLoading, isValidating, mutate } = useSWR<QueryPage>(queryExplorerKey(filters, cursors.at(-1)), fetcher)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setFilters(current => current.search === search ? current : { ...current, search })
      setCursors(current => current.length ? [] : current)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [search])

  function changeFilter(key: keyof QueryFilters, value: string) {
    setFilters(current => ({ ...current, [key]: value }))
    setCursors([])
  }
  function reset() { setSearch(""); setFilters(DEFAULT_QUERY_FILTERS); setCursors([]) }
  const filtered = Object.keys(DEFAULT_QUERY_FILTERS).some(key => filters[key as keyof QueryFilters] !== DEFAULT_QUERY_FILTERS[key as keyof QueryFilters]) || search !== ""

  return <div className="flex h-[calc(100dvh-6.25rem)] min-h-0 min-w-0 flex-col gap-4 md:h-full">
    <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b pb-4">
      <div><h1 className="text-[1.75rem] font-semibold tracking-[-0.035em]">Query explorer</h1><p className="mt-1 text-sm text-muted-foreground">Find questions. Inspect latency, caching, and retrieval quality.</p></div>
      <Button variant="outline" size="sm" disabled={isValidating} onClick={() => { if (cursors.length) setCursors([]); else void mutate() }}><ArrowClockwiseIcon className={isValidating ? "size-4 animate-spin" : "size-4"} />Refresh</Button>
    </header>
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-0.5 pb-3">
      <section aria-label="Query filters" className="max-h-[40%] shrink-0 space-y-4 overflow-y-auto rounded-xl border bg-card p-4 [@media(max-height:700px)]:max-h-[30%]">
        <div className="relative"><MagnifyingGlassIcon aria-hidden="true" className="absolute top-2.5 left-3 size-4 text-muted-foreground" /><Input aria-label="Search questions" placeholder="Search questions…" maxLength={200} value={search} onChange={event => setSearch(event.target.value)} className="pl-9" /></div>
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
          <Filter label="Project" value={filters.project} onChange={value => changeFilter("project", value)}><option value="">All projects</option>{projects?.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</Filter>
          <Filter label="Time range" value={filters.days} onChange={value => changeFilter("days", value)}>{[7, 30, 90].map(days => <option key={days} value={days}>Last {days} days</option>)}</Filter>
          <Filter label="Cache result" value={filters.cache} onChange={value => changeFilter("cache", value)}><option value="all">All results</option><option value="fresh">Fresh</option><option value="l1">Exact cache</option><option value="l2">Semantic cache</option></Filter>
          <Filter label="Response time" value={filters.latency} onChange={value => changeFilter("latency", value)}><option value="">Any latency</option><option value="1000">At least 1 second</option><option value="3000">At least 3 seconds</option><option value="10000">At least 10 seconds</option></Filter>
        </div>
        {projectsError && !isSessionExpired(projectsError) && <p className="text-xs text-destructive">Project filters could not load. You can still search across all projects.</p>}
        {filtered && <Button size="sm" variant="ghost" onClick={reset}>Reset filters</Button>}
      </section>
      {/* Natural height for short lists; only the rows shrink and scroll when
          the card reaches the space left below the filters, like FilesTab. */}
      <section aria-label="Query results" aria-busy={isLoading} className="flex max-h-full min-h-0 flex-col overflow-hidden rounded-xl border bg-card">
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b px-4 py-3"><h2 className="text-sm font-medium">Recent queries</h2><span className="text-xs text-muted-foreground" role="status">{data ? `${data.items.length} on this page · Newest first` : "Loading records…"}</span></div>
        <div className="min-h-0 overflow-y-auto">
        {error && !isSessionExpired(error) ? <div role="alert" className="space-y-3 p-8 text-sm"><p>Could not load query history. Please try again.</p><Button variant="outline" onClick={() => void mutate()}>Retry</Button></div>
          : !data ? <QueryRowsSkeleton />
          : data.items.length === 0 ? <div className="px-6 py-16 text-center"><MagnifyingGlassIcon className="mx-auto mb-4 size-7 text-muted-foreground" /><h3 className="text-sm font-medium">{filtered ? "No queries match these filters" : "No queries in this time range"}</h3><p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-muted-foreground">{filtered ? "Try another search, a wider time range, or reset the filters." : "Questions from the playground and query API will appear here once recorded."}</p></div>
          : <ul className="divide-y">{data.items.map(query => <li key={query.id}><button type="button" onClick={event => { triggerRef.current = event.currentTarget; setSelected(query.id) }} className="group flex w-full min-w-0 flex-col gap-3 px-4 py-4 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:flex-row sm:items-center sm:gap-6">
            <div className="min-w-0 flex-1"><p className="line-clamp-2 break-words text-sm font-medium leading-6">{query.question}</p><p className="mt-1 truncate text-xs text-muted-foreground">{query.project_name} · {dateLabel(query.created_at)}</p></div>
            <div className="flex shrink-0 flex-wrap items-center gap-3"><Badge variant="outline" className="text-[11px]">{queryCacheLabel(query.cache_layer)}</Badge><span className="w-24 text-right text-xs tabular-nums text-muted-foreground">{queryLatency(query.latency_ms)}</span><ArrowRightIcon aria-hidden="true" className="size-4 text-muted-foreground" /></div>
          </button></li>)}</ul>}
        </div>
        <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t px-4 py-3"><span className="text-xs text-muted-foreground">Page {cursors.length + 1}</span><div className="flex gap-2"><Button size="sm" variant="outline" disabled={!cursors.length || isLoading} onClick={() => setCursors(current => current.slice(0, -1))}>Previous</Button><Button size="sm" variant="outline" disabled={!data?.next_cursor || isLoading || !!error || search !== filters.search} onClick={() => { if (data?.next_cursor) setCursors(current => [...current, data.next_cursor!]) }}>Next</Button></div></footer>
      </section>
      <p className="shrink-0 px-1 text-xs leading-5 text-muted-foreground">Recorded queries only. Failed requests and other API operations are not included. Times are shown in your local timezone.</p>
    </div>
    <Sheet open={selected !== null} onOpenChange={open => { if (!open) setSelected(null) }}><SheetContent side="right" className="w-full max-w-full bg-background sm:w-[540px]" onCloseAutoFocus={event => { event.preventDefault(); triggerRef.current?.focus() }}><SheetHeader className="p-6 pr-12"><SheetTitle className="text-lg">Query details</SheetTitle><SheetDescription>Recorded question and performance measurements.</SheetDescription></SheetHeader>{selected && <QueryDetail key={selected} id={selected} />}</SheetContent></Sheet>
  </div>
}
