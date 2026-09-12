"use client"

import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import useSWR, { useSWRConfig } from "swr"
import { ArchiveIcon, ArrowRightIcon, ArrowsClockwiseIcon, CheckCircleIcon, FloppyDiskIcon, MagnifyingGlassIcon, TrayIcon } from "@phosphor-icons/react/dist/ssr"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { KnowledgeGapsContentSkeleton, KnowledgeGapDetailSkeleton } from "@/components/knowledge-gaps-loading"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { FilterSelect } from "@/components/filter-select"
import { MobileFilters } from "@/components/mobile-filters"
import { AddQueryToSet } from "@/components/query-tools"
import { GapVerification } from "@/components/gap-verification"
import { api, ApiError, fetcher, isSessionExpired } from "@/lib/api"
import { cn } from "@/lib/utils"
import type { Project } from "@/lib/types"
import {
  DEFAULT_GAP_FILTERS, gapDetailKey, gapStatus, knowledgeGapsKey,
  type GapDetail, type GapFilters, type GapItem, type GapReport,
} from "@/lib/knowledge-gaps"

const count = (value: number) => value.toLocaleString("en-US")
const when = (value: string) => new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })

function StatusBadge({ item }: { item: GapItem }) {
  const Icon = item.reopened ? ArrowsClockwiseIcon : item.status === "resolved" ? item.verification_run_id ? CheckCircleIcon : ArchiveIcon : TrayIcon
  return <Badge variant="outline" className={cn("shrink-0", item.status === "resolved" && item.verification_run_id
    ? "border-emerald-500/30 text-emerald-700 dark:text-emerald-400"
    : item.status === "resolved" ? "text-muted-foreground" : "border-amber-500/30 text-amber-700 dark:text-amber-400")}><Icon aria-hidden="true" />{gapStatus(item)}</Badge>
}

function GapReview({ item, days, verificationId, onUpdate }: { item: GapItem; days: string; verificationId: string | null; onUpdate: (result: GapDetail) => Promise<void> }) {
  // Retain the reviewed evidence version and draft through background refreshes
  // or evidence pagination. A conflict requires an explicit refresh to save.
  const [baseline, setBaseline] = useState(item)
  const [note, setNote] = useState(item.note ?? "")
  const [busy, setBusy] = useState<"save" | "refresh" | null>(null)
  const [failure, setFailure] = useState("")
  const [conflict, setConflict] = useState(false)
  const [message, setMessage] = useState("")
  const endpoint = gapDetailKey(item.project_id, item.question_key, days)
  const canAttach = !!verificationId && (baseline.status !== "resolved" || verificationId !== baseline.verification_run_id)

  async function save(status: "open" | "resolved", verification = baseline.verification_run_id) {
    if (busy) return
    setBusy("save"); setFailure(""); setMessage("")
    try {
      const result = await api<GapDetail>(endpoint, { method: "PUT", body: JSON.stringify({
        status, note, revision: baseline.revision, evidence_version: baseline.evidence_version,
        verification_run_id: status === "resolved" ? verification : null,
      }) })
      setBaseline(result.item); setNote(result.item.note ?? ""); setConflict(false)
      await onUpdate(result)
      setMessage(result.item.reopened ? "New evidence arrived. This gap still needs review."
        : status === "resolved" ? verification ? "Resolved with a passing check attached. You can review the saved answer above." : "Review closed without a test. No fix has been verified." : "Review saved. This gap is open.")
    } catch (error) {
      if (!isSessionExpired(error)) {
        setFailure(error instanceof Error ? error.message : "Could not save this review.")
        setConflict(error instanceof ApiError && error.status === 409)
      }
    } finally { setBusy(null) }
  }

  async function refresh() {
    setBusy("refresh"); setFailure(""); setMessage("")
    try {
      const result = await api<GapDetail>(endpoint)
      setBaseline(result.item); setConflict(false)
      await onUpdate(result)
      setMessage("Evidence refreshed. Your draft note is preserved. Review the queries before saving again.")
    } catch (error) {
      if (!isSessionExpired(error)) setFailure(error instanceof Error ? error.message : "Could not refresh evidence.")
    } finally { setBusy(null) }
  }

  return <section className="space-y-3 rounded-xl border bg-background p-4" aria-label="Review this gap" aria-busy={!!busy}>
    <h3 className="text-sm font-medium">Review and resolution</h3>
    <label className="block space-y-2 text-xs font-medium">Review note
      <Textarea value={note} onChange={event => setNote(event.target.value)} maxLength={2000} disabled={!!busy}
        placeholder="What did you check or change? If the answer was correct, note that here." className="min-h-24 text-base md:text-sm" />
    </label>
    <p className="text-xs leading-5 text-muted-foreground">Use Verify fix above to test the answer and attach a passing result. Close review dismisses the issue without testing it. New flagged evidence can reopen either outcome.</p>
    {baseline.status === "resolved" && <p className="flex items-start gap-2 text-xs leading-5 text-muted-foreground">{baseline.verification_run_id ? <CheckCircleIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" /> : <ArchiveIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />}<span>{baseline.verification_run_id ? "A passing check is saved with this resolution. Its questions, answers, and checks are shown above." : "Closed without verification. You can still run Verify fix and attach a passing result."}</span></p>}
    {failure && <p role="alert" className="text-xs text-destructive">{failure}</p>}
    {message && <p role="status" className="text-xs leading-5 text-muted-foreground">{message}</p>}
    <div className="flex flex-wrap gap-2">
      {canAttach && <Button size="sm" disabled={!!busy || conflict} onClick={() => void save("resolved", verificationId)}><CheckCircleIcon aria-hidden="true" />Resolve with verification</Button>}
      <Button size="sm" variant="outline" disabled={!!busy || conflict} onClick={() => void save(baseline.status === "resolved" ? "open" : "resolved", null)}>
        {busy === "save" ? <Spinner size={16} /> : baseline.status === "resolved" ? <ArrowsClockwiseIcon aria-hidden="true" className="size-4" /> : <ArchiveIcon aria-hidden="true" className="size-4" />}
        {busy === "save" ? "Saving…" : baseline.status === "resolved" ? "Reopen gap" : "Close review"}
      </Button>
      <Button size="sm" variant="outline" disabled={!!busy || conflict || note.trim() === (baseline.note ?? "")} onClick={() => void save(baseline.status)}><FloppyDiskIcon aria-hidden="true" className="size-4" />Save note</Button>
      <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => void refresh()}>{busy === "refresh" ? <Spinner size={16} /> : <ArrowsClockwiseIcon aria-hidden="true" className="size-4" />}{busy === "refresh" ? "Refreshing…" : "Refresh evidence"}</Button>
    </div>
  </section>
}

function GapDetailView({ selected, days, onSaved }: { selected: GapItem; days: string; onSaved: () => void }) {
  const [offset, setOffset] = useState(0)
  const [verificationId, setVerificationId] = useState<string | null>(null)
  const { mutate: updateCache } = useSWRConfig()
  const { data, error, isLoading, mutate } = useSWR<GapDetail>(gapDetailKey(selected.project_id, selected.question_key, days, offset), fetcher, { revalidateOnFocus: false, keepPreviousData: true })
  async function update(result: GapDetail) {
    await updateCache(gapDetailKey(selected.project_id, selected.question_key, days), result, { revalidate: false })
    setOffset(0); setVerificationId(null); onSaved()
  }
  return <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-6 pt-2 [overflow-wrap:anywhere]">
    {error && !isSessionExpired(error) && <div role="alert" className="space-y-2 rounded-xl border p-4 text-sm">
      <p>Could not load this gap. Its evidence may have left the selected window.</p>
      <Button variant="outline" size="sm" onClick={() => void mutate()}>Retry</Button>
    </div>}
    {!data && !error && <KnowledgeGapDetailSkeleton />}
    {data && <>
      <div className="flex flex-wrap items-center gap-2"><StatusBadge item={data.item} /><span className="text-xs text-muted-foreground">{data.item.project_name}</span></div>
      <section><h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">Question</h3><p className="whitespace-pre-wrap rounded-xl border bg-background p-4 text-sm leading-7">{data.item.question}</p></section>
      <p className="text-xs leading-5 text-muted-foreground">{data.item.flagged_count === 0
        ? "This saved review has no current gap signals."
        : data.item.weak_evidence_count > 0
          ? `Flagged for document similarity below ${data.weak_similarity_threshold.toFixed(2)}${data.item.not_helpful_count > 0 ? " and not-helpful feedback" : ""}. A low document match does not mean the answer was wrong.`
          : "Flagged because an answer received not-helpful feedback. Review the feedback before deciding whether documents need changes."}</p>
      {data.item.reopened && <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs leading-5">New evidence appeared after the last resolution{data.item.resolved_at ? ` on ${when(data.item.resolved_at)}` : ""}. Review it before resolving again.</p>}
      <dl className="grid grid-cols-2 gap-3">
        {[["Matching queries", data.item.query_count], ["Flagged queries", data.item.flagged_count], ["Not helpful", data.item.not_helpful_count], ["Low document matches", data.item.weak_evidence_count]].map(([label, value]) =>
          <div key={label} className="min-w-0 rounded-xl border bg-background p-3"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-2 break-words text-xl font-semibold tabular-nums">{count(Number(value))}</dd></div>)}
      </dl>
      <p className="text-xs leading-5 text-muted-foreground">{count(data.item.helpful_count)} helpful ratings · {count(data.item.unmeasured_count)} fresh queries without a similarity measurement. Signals can overlap on one query. Historical answers and source passages are not retained.</p>
      {data.limited && <p className="rounded-lg border border-amber-500/30 p-3 text-xs leading-5">Partial history: this project has more than {count(data.scan_limit)} queries in the last {data.window_days} days. Counts and evidence cover its latest {count(data.scanned_queries)} queries.</p>}
      <div className="flex flex-wrap gap-2">
        <Button asChild variant="outline" size="sm"><Link href={`/projects/${encodeURIComponent(data.item.project_id)}?tab=files`}>Review documents<ArrowRightIcon aria-hidden="true" className="size-4" /></Link></Button>
        <Button asChild variant="outline" size="sm"><Link href={`/projects/${encodeURIComponent(data.item.project_id)}?tab=playground`}>Test in Playground<ArrowRightIcon aria-hidden="true" className="size-4" /></Link></Button>
      </div>
      <GapVerification gap={data} days={days} resolutionRunId={verificationId} onSelect={setVerificationId} />
      <GapReview item={data.item} days={days} verificationId={verificationId} onUpdate={update} />
      <section className="space-y-3" aria-label="Queries behind this gap" aria-busy={isLoading}>
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-medium">Queries behind this gap</h3><span className="text-xs text-muted-foreground">Flagged first · Last {days} days</span></div>
        <ul className="space-y-3">{data.evidence.map(query => <li key={query.id} className="space-y-3 rounded-xl border bg-background p-4">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {query.not_helpful && <Badge variant="outline">Not helpful</Badge>}
            {query.weak_evidence && <Badge variant="outline">Low document match</Badge>}
            {!query.not_helpful && !query.weak_evidence && <Badge variant="secondary">{query.feedback_rating === "helpful" ? "Helpful" : "No flagged signal"}</Badge>}
            <span className="text-muted-foreground">{when(query.created_at)}</span>
          </div>
          <p className="whitespace-pre-wrap text-sm leading-6">{query.question}</p>
          <p className="text-xs leading-5 text-muted-foreground">Query {query.id} · {query.cache_layer ? `${query.cache_layer.toUpperCase()} cache` : `Fresh retrieval: ${query.retrieval_similarity == null ? "not measured" : query.retrieval_similarity.toFixed(3)}`}</p>
          {query.feedback_note && <blockquote className="whitespace-pre-wrap border-l-2 pl-3 text-xs leading-6 text-muted-foreground">{query.feedback_note}</blockquote>}
          <AddQueryToSet query={{ id: query.id, project_id: data.item.project_id, question: query.question }} />
        </li>)}</ul>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>{isLoading ? "Loading queries…" : `${offset + 1}–${Math.min(offset + 25, data.evidence_total)} of ${count(data.evidence_total)}`}</span>
          <div className="flex gap-2"><Button variant="outline" size="sm" disabled={isLoading || offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous queries</Button><Button variant="outline" size="sm" disabled={isLoading || data.next_offset === null} onClick={() => setOffset(data.next_offset!)}>Next queries</Button></div>
        </div>
      </section>
    </>}
  </div>
}

export function KnowledgeGapsDashboard({ initialProject = "" }: { initialProject?: string }) {
  const [filters, setFilters] = useState<GapFilters>({ ...DEFAULT_GAP_FILTERS, project: initialProject })
  const [search, setSearch] = useState("")
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<GapItem | null>(null)
  const trigger = useRef<HTMLButtonElement | null>(null)
  const { data: projects, error: projectsError } = useSWR<Project[]>("/api/projects", fetcher)
  const { data, error, isLoading, isValidating, mutate } = useSWR<GapReport>(knowledgeGapsKey(filters, offset), fetcher, {
    refreshInterval: selected || offset ? 0 : 60_000, revalidateOnFocus: !selected,
  })
  useEffect(() => {
    const timer = window.setTimeout(() => { setFilters(current => current.search === search ? current : { ...current, search }); setOffset(0) }, 300)
    return () => window.clearTimeout(timer)
  }, [search])
  function change(patch: Partial<GapFilters>) { setFilters(current => ({ ...current, ...patch })); setOffset(0) }
  function reset() { setFilters(DEFAULT_GAP_FILTERS); setSearch(""); setOffset(0) }
  const activeFilters = Number(filters.days !== "30") + Number(!!filters.project) + Number(filters.status !== "open") + Number(filters.recurring)

  return <div className="flex h-[calc(100dvh-6.3125rem)] min-h-0 min-w-0 flex-col gap-4 md:h-full">
    <header className="grid shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 border-b pb-4">
      <h1 id="knowledge-gaps-heading" tabIndex={-1} className="col-span-2 text-[1.75rem] font-semibold tracking-[-0.035em] lg:col-span-1">Knowledge gaps</h1>
      <p className="col-span-2 row-start-2 text-xs leading-5 text-muted-foreground md:text-sm">Review potential knowledge gaps from feedback and document matches. A flagged query can still have a correct answer.</p>
      <div role="search" aria-label="Search and filter knowledge gaps" className="col-span-2 row-start-3 flex min-w-0 items-center gap-2 lg:col-span-1 lg:col-start-2 lg:row-start-1 lg:w-72">
        <div className="relative min-w-0 flex-1"><MagnifyingGlassIcon aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" /><Input aria-label="Search gap questions" placeholder="Search questions…" value={search} maxLength={200} onChange={event => setSearch(event.target.value)} className="h-8 pl-8 pr-2 text-base placeholder:text-[13px] md:text-[13px]" /></div>
        <MobileFilters title="Knowledge gap filters" activeCount={activeFilters} onReset={reset} desktop compact>
          <div className="space-y-4">
            <FilterSelect label="Project" value={filters.project} onChange={project => change({ project })} options={[{ value: "", label: "All projects" }, ...(projects ?? []).map(project => ({ value: project.id, label: project.name }))]} />
            <FilterSelect label="Time range" value={filters.days} onChange={days => change({ days })} options={[7, 30, 90].map(days => ({ value: String(days), label: `Last ${days} days` }))} />
            <FilterSelect label="Status" value={filters.status} onChange={status => change({ status })} options={[{ value: "open", label: "Needs review" }, { value: "resolved", label: "Closed reviews" }, { value: "all", label: "All statuses" }]} />
            <div className="flex items-center justify-between gap-3 rounded-lg border p-3">
              <label htmlFor="repeated-gap-questions" className="cursor-pointer text-sm font-medium">Only repeated questions<span className="mt-1 block text-xs font-normal text-muted-foreground">At least 2 matching queries</span></label>
              <Switch id="repeated-gap-questions" checked={filters.recurring} onCheckedChange={recurring => change({ recurring })} />
            </div>
            {projectsError && !isSessionExpired(projectsError) && <p className="text-xs text-destructive">Project options could not load. You can still review all projects.</p>}
          </div>
        </MobileFilters>
        <Button variant="outline" size="icon-sm" aria-label="Refresh knowledge gaps" title="Refresh knowledge gaps" disabled={isValidating} onClick={() => void mutate()}><ArrowsClockwiseIcon aria-hidden="true" className={cn("size-4", isValidating && "motion-safe:animate-spin")} /></Button>
      </div>
    </header>
    <div role="region" aria-label="Knowledge gaps overview" tabIndex={0} className="min-h-0 flex-1 space-y-4 overflow-y-auto pb-3 pr-0.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
      <p className="break-words text-xs leading-5 text-muted-foreground [overflow-wrap:anywhere]">Last {filters.days} days · {filters.project ? projects?.find(project => project.id === filters.project)?.name ?? "Selected project" : "All projects"} · {filters.status === "all" ? "All statuses" : filters.status === "resolved" ? "Closed reviews" : "Needs review"}{filters.recurring ? " · Repeated only" : ""}</p>
      {error && !isSessionExpired(error) && <div role="alert" className="space-y-2 rounded-xl border p-4 text-sm"><p>Could not load knowledge gaps.{data ? " Showing the last available snapshot." : " Please try again."}</p><Button size="sm" variant="outline" onClick={() => void mutate()}>Retry</Button></div>}
      {!data && !error && <KnowledgeGapsContentSkeleton />}
      {data && <>
        <section aria-label="Gap summary" className="grid grid-cols-3 gap-2 sm:gap-3">
          {[["Needs review", data.open_groups], ["Closed reviews", data.resolved_groups], ["Flagged queries", data.flagged_queries]].map(([label, value]) => <div key={label} className="min-w-0 rounded-xl border bg-card p-3 sm:p-4"><p className="min-h-8 text-[11px] leading-4 text-muted-foreground sm:min-h-0 sm:text-xs">{label}</p><p className="mt-2 text-2xl font-semibold tabular-nums">{count(Number(value))}</p></div>)}
        </section>
        <p className="text-xs leading-5 text-muted-foreground">Summary covers the selected projects and date range. Counts reflect current ratings.</p>
        {data.limited && <p role="status" className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3 text-xs leading-5">Partial history: showing groups from the latest {count(data.scanned_queries)} queries in this scope. Filter to a project or a shorter date range to inspect more of its activity. Group details use that project’s own sample.</p>}
        <section aria-label="Knowledge gap results" aria-busy={isLoading} className="overflow-hidden rounded-xl border bg-card">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3"><h2 className="text-sm font-medium">Question groups</h2><span role="status" className="text-xs text-muted-foreground">{count(data.matched_groups)} matching · Most flagged first</span></div>
          {!data.items.length ? <div className="space-y-3 px-6 py-12 text-center">
            {filters.status === "resolved" ? <ArchiveIcon aria-hidden="true" className="mx-auto size-7 text-muted-foreground" /> : <TrayIcon aria-hidden="true" className="mx-auto size-7 text-muted-foreground" />}
            <p className="text-sm font-medium">{data.scanned_queries === 0 ? "No query activity in this window" : "No gaps match these filters"}</p>
            <p className="mx-auto max-w-md text-xs leading-5 text-muted-foreground">Questions with negative feedback or low document similarity appear here. Casual conversation and obvious keyboard noise are excluded from similarity flags.</p>
            {(activeFilters > 0 || search) && <Button size="sm" variant="outline" onClick={reset}>Reset filters</Button>}
          </div> : <ul className="divide-y">{data.items.map(item => <li key={`${item.project_id}:${item.question_key}`}>
            <button type="button" onClick={event => { trigger.current = event.currentTarget; setSelected(item) }} className="relative block w-full min-w-0 space-y-3 px-4 py-4 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
              <div className="flex flex-col items-start justify-between gap-2 sm:flex-row sm:gap-4"><p className="min-w-0 line-clamp-2 break-words text-sm font-medium leading-6 [overflow-wrap:anywhere]">{item.question}</p><StatusBadge item={item} /></div>
              <p className="break-words text-xs leading-5 text-muted-foreground [overflow-wrap:anywhere]">{item.project_name} · Last seen {when(item.last_seen)}</p>
              <div className="flex items-end justify-between gap-3"><div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground"><span>{count(item.query_count)} {item.query_count === 1 ? "query" : "matching queries"}</span><span>{count(item.not_helpful_count)} not helpful</span><span>{count(item.weak_evidence_count)} low document {item.weak_evidence_count === 1 ? "match" : "matches"}</span></div><ArrowRightIcon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" /><span className="sr-only">Review gap</span></div>
            </button>
          </li>)}</ul>}
        </section>
        {(offset > 0 || data.next_offset !== null) && <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground"><span>Page {Math.floor(offset / 25) + 1}</span><div className="flex gap-2"><Button size="sm" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</Button><Button size="sm" variant="outline" disabled={data.next_offset === null} onClick={() => setOffset(data.next_offset!)}>Next</Button></div></div>}
        <details className="rounded-xl border p-4 text-xs leading-6 text-muted-foreground"><summary className="cursor-pointer rounded-sm font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">How gaps are identified</summary><div className="mt-2 space-y-2">
          <p>Questions are grouped within one project when wording matches after normalizing case, whitespace, and question-ending marks. Paraphrases remain separate; numbers, negation, and word order are preserved.</p>
          <p>Signals are a “not helpful” rating or an uncached retrieval similarity below {data.weak_similarity_threshold.toFixed(2)}. This is a review threshold, independent of project answer settings. Recognized casual conversation (including repeated or stretched greetings) and obvious keyboard noise do not trigger similarity flags. Real questions that include a greeting still qualify. Explicit negative feedback always counts. Cached and missing similarity values do not trigger similarity flags.</p>
          <p>Similarity measures retrieval closeness, not answer accuracy. Groups can include helpful answers as context. Lists scan up to {count(data.scan_limit)} recent queries. Evidence follows query-log retention; groups without retained queries in the selected window are hidden. Review notes and status persist until their project is deleted.</p>
        </div></details>
      </>}
    </div>
    <Sheet open={!!selected} onOpenChange={open => { if (!open) setSelected(null) }}>
      <SheetContent side="right" className="w-full max-w-full bg-background sm:w-[540px]" onCloseAutoFocus={event => { event.preventDefault(); if (trigger.current?.isConnected) trigger.current.focus(); else document.getElementById("knowledge-gaps-heading")?.focus() }}>
        <SheetHeader className="shrink-0 p-6 pr-12"><SheetTitle className="text-lg">Review knowledge gap</SheetTitle><SheetDescription>Review the evidence, test a fix, or close the review if the answer was already correct.</SheetDescription></SheetHeader>
        {selected && <GapDetailView key={`${selected.project_id}:${selected.question_key}:${filters.days}`} selected={selected} days={filters.days} onSaved={() => void mutate()} />}
      </SheetContent>
    </Sheet>
  </div>
}
