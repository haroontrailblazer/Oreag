"use client"

import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import useSWR, { useSWRConfig } from "swr"
import { ArrowRightIcon, ArrowsClockwiseIcon, CheckCircleIcon, ClockIcon, FileTextIcon, MagnifyingGlassIcon } from "@phosphor-icons/react/dist/ssr"
import { toast } from "sonner"
import { api, fetcher, isSessionExpired } from "@/lib/api"
import { DOCUMENT_INSIGHTS_KEY, FRESHNESS, documentInsightsKey, type DocumentInsight, type DocumentInsightsReport } from "@/lib/document-insights"
import { cn } from "@/lib/utils"
import { FilterSelect } from "@/components/filter-select"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"

const count = (value: number | null) => value == null ? "Not recorded" : value.toLocaleString()
const date = (value: string | null) => value ? new Date(value).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "Not recorded"

function FreshnessBadge({ document }: { document: DocumentInsight }) {
  const state = FRESHNESS[document.freshness]
  return <Badge variant="outline" className={cn("max-w-full whitespace-normal text-left", state.className)}>{document.freshness === "reviewed" ? <CheckCircleIcon aria-hidden="true" /> : <ClockIcon aria-hidden="true" />}{state.label}</Badge>
}

export function DocumentInsights({ projects }: { projects: { id: string; name: string }[] }) {
  const [project, setProject] = useState("")
  const [days, setDays] = useState("30")
  const [search, setSearch] = useState("")
  const [query, setQuery] = useState("")
  const [offset, setOffset] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState("")
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const selectedProject = projects.some(item => item.id === project) ? project : projects[0]?.id ?? ""
  const { mutate: refreshAll } = useSWRConfig()
  const { data, error, mutate, isValidating } = useSWR<DocumentInsightsReport>(selectedProject ? documentInsightsKey(selectedProject, days, query, offset) : null, fetcher, { refreshInterval: selectedId ? 0 : 60_000, revalidateOnFocus: !selectedId })
  const selected = data?.items.find(item => item.id === selectedId)

  useEffect(() => {
    const timer = window.setTimeout(() => { setQuery(search); setOffset(0) }, 300)
    return () => window.clearTimeout(timer)
  }, [search])

  async function markReviewed(document: DocumentInsight) {
    setSaving(true); setSaveError("")
    try {
      const result = await api<{ reviewed_at: string; review_after_days: number }>(`${DOCUMENT_INSIGHTS_KEY}/${document.id}/review`, { method: "PUT", body: JSON.stringify({ content_signature: document.content_signature }) })
      await mutate(current => current ? { ...current, items: current.items.map(item => item.id === document.id ? { ...item, freshness: "reviewed", reviewed_at: result.reviewed_at, review_due_at: new Date(new Date(result.reviewed_at).getTime() + result.review_after_days * 86_400_000).toISOString() } : item) } : current, { revalidate: false })
      toast.success("Document review recorded")
      void refreshAll(key => typeof key === "string" && key.startsWith(`${DOCUMENT_INSIGHTS_KEY}?`))
    } catch (failure) {
      if (!isSessionExpired(failure)) setSaveError(failure instanceof Error ? failure.message : "Could not record this review. Try again.")
      void mutate()
    } finally { setSaving(false) }
  }

  return <section aria-label="Document impact and freshness" className="min-w-0 space-y-4 rounded-xl border bg-card p-4 sm:p-5">
    <div className="space-y-1"><h2 className="flex items-center gap-2 text-sm font-semibold"><FileTextIcon className="size-4 text-muted-foreground" aria-hidden="true" />Document impact &amp; freshness</h2><p className="text-xs leading-5 text-muted-foreground">See which documents appear in answers and keep their content reviewed.</p></div>
    {!projects.length ? <p className="py-6 text-center text-xs text-muted-foreground">Add a project and upload documents to get started.</p> : <>
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_8rem] gap-3 sm:grid-cols-[minmax(0,1fr)_8rem_minmax(0,1fr)] sm:items-end">
        <FilterSelect label="Document project" value={selectedProject} onChange={value => { setProject(value); setOffset(0); setSelectedId(null) }} options={projects.map(item => ({ value: item.id, label: item.name }))} />
        <FilterSelect label="Impact period" value={days} onChange={value => { setDays(value); setOffset(0); setSelectedId(null) }} options={[7, 30, 90].map(value => ({ value: String(value), label: `${value} days` }))} />
        <div className="col-span-2 flex min-w-0 items-center gap-2 sm:col-span-1"><div className="relative min-w-0 flex-1"><MagnifyingGlassIcon className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" /><Input aria-label="Search documents" placeholder="Search documents…" value={search} maxLength={200} onChange={event => setSearch(event.target.value)} className="h-8 pl-8 text-base placeholder:text-[13px] md:text-[13px]" /></div>
        <Button variant="outline" size="icon-sm" aria-label="Refresh document insights" disabled={isValidating} onClick={() => void mutate()}><ArrowsClockwiseIcon className="size-4" /></Button>
        </div>
      </div>
      {error && !isSessionExpired(error) && <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-xs"><p>Could not refresh document insights.{data ? " Showing the last available snapshot." : " Please try again."}</p><Button variant="outline" size="sm" onClick={() => void mutate()}>Retry</Button></div>}
      {!data && (!error || isSessionExpired(error)) && <div role="status" aria-label="Loading document insights" className="space-y-3"><Skeleton className="h-20 rounded-lg" /><Skeleton className="h-48 rounded-lg" /></div>}
      {data && <>
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-1 rounded-lg border p-3"><p className="text-xs text-muted-foreground">Current documents</p><p className="text-xl font-semibold tabular-nums">{count(data.total_documents)}</p></div>
          <div className="space-y-1 rounded-lg border p-3"><p className="text-xs text-muted-foreground">Answers with document citations</p><p className="text-xl font-semibold tabular-nums">{data.tracked_queries ? count(data.answers_with_citations) : "Not recorded yet"}</p></div>
          <div className="space-y-1 rounded-lg border p-3"><p className="text-xs text-muted-foreground">Queries with source tracking</p><p className="text-xl font-semibold tabular-nums">{count(data.tracked_queries)} <span className="text-xs font-normal text-muted-foreground">/ {count(data.query_count)}</span></p></div>
        </div>
        {data.limited ? <p className="rounded-lg bg-muted/20 p-3 text-xs leading-5 text-muted-foreground">Impact shows a sample of the latest {count(data.scan_limit)} queries. Choose a shorter period for more complete coverage.</p> : !data.tracked_queries ? <p className="text-xs leading-5 text-muted-foreground">Document impact starts with new answers. Earlier queries without document IDs cannot show which documents were used.</p> : data.tracked_queries < data.query_count ? <p className="text-xs leading-5 text-muted-foreground">Impact covers the {count(data.tracked_queries)} queries with recorded document IDs. Earlier or untracked queries are excluded.</p> : null}
        <div className="overflow-hidden rounded-lg border">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/20 px-4 py-3 text-xs"><span className="font-medium">Documents</span><span className="text-muted-foreground">Content reviews every {data.review_after_days} days</span></div>
          {!data.items.length ? <div className="space-y-2 p-8 text-center"><FileTextIcon className="mx-auto size-7 text-muted-foreground" aria-hidden="true" /><p className="text-sm font-medium">{query ? "No documents match this search" : "No current documents yet"}</p><p className="text-xs text-muted-foreground">{query ? "Try another filename." : "Upload documents in your project’s Files tab."}</p><Button variant="outline" size="sm" asChild><Link href={`/projects/${encodeURIComponent(selectedProject)}?tab=files`}>Open files<ArrowRightIcon /></Link></Button></div> : <ul className="divide-y">{data.items.map(document => <li key={document.id}><button type="button" className="flex w-full min-w-0 items-start gap-3 p-4 text-left hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring" onClick={event => { triggerRef.current = event.currentTarget; setSelectedId(document.id); setSaveError("") }}>
            <FileTextIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <div className="grid min-w-0 flex-1 gap-3 sm:grid-cols-[minmax(0,1fr)_6rem_10rem] sm:items-center">
              <div className="min-w-0 space-y-1"><p className="truncate text-sm font-medium">{document.filename}</p><p className="text-xs text-muted-foreground">{document.indexed_at ? `Indexed ${date(document.indexed_at)}` : `Uploaded ${date(document.created_at)}`}</p></div>
              <div><p className="text-xs text-muted-foreground">Cited answers</p><p className="mt-1 text-sm font-medium tabular-nums">{count(document.cited_answers)}</p></div>
              <div className="space-y-1"><FreshnessBadge document={document} />{document.reviewed_at && <p className="text-[11px] text-muted-foreground">Reviewed {date(document.reviewed_at)}</p>}</div>
            </div>
            <ArrowRightIcon className="mt-1 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          </button></li>)}</ul>}
        </div>
        {data.matching_documents > data.page_size && <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground"><p>{data.offset + 1}–{Math.min(data.offset + data.items.length, data.matching_documents)} of {count(data.matching_documents)} documents</p><div className="flex gap-2"><Button variant="outline" size="sm" disabled={!offset || isValidating} onClick={() => setOffset(value => Math.max(0, value - data.page_size))}>Previous</Button><Button variant="outline" size="sm" disabled={offset + data.page_size >= data.matching_documents || isValidating} onClick={() => setOffset(value => value + data.page_size)}>Next</Button></div></div>}
        <details className="text-xs leading-5 text-muted-foreground"><summary className="w-fit cursor-pointer rounded-sm font-medium text-foreground focus-visible:outline-2">How impact and freshness work</summary><div className="mt-2 space-y-2"><p>Impact counts retained queries in the selected period, including cached answers. A document is counted once per query. Cited answers contain an explicit citation to a source from that document. A source being included does not prove it was used correctly.</p><p>Feedback belongs to the whole answer. One answer can cite several documents. These counts describe recorded usage, not how much a document improved quality.</p><p>Freshness is based on a person reviewing the current content. Reviews become due after {data.review_after_days} days, and changed content needs another review. Uploading or re-indexing alone does not confirm that the information is current. Superseded files are excluded from this list.</p></div></details>
      </>}
    </>}
    <Sheet open={selectedId !== null} onOpenChange={open => { if (!open && !saving) setSelectedId(null) }}>
      <SheetContent side="right" className="w-full max-w-full bg-background sm:w-[520px]" onCloseAutoFocus={event => { event.preventDefault(); triggerRef.current?.focus() }}>
        <SheetHeader className="p-6 pr-12"><SheetTitle className="break-words text-lg">{selected?.filename ?? "Document insights"}</SheetTitle><SheetDescription>Answer usage and content-review history for this version.</SheetDescription></SheetHeader>
        {selected && <div className="min-h-0 space-y-5 overflow-y-auto px-6 pb-6">
          <div className="grid grid-cols-2 gap-3">{[["Cited answers", selected.cited_answers], ["Included in sources", selected.included_queries]].map(([label, value]) => <div key={label} className="min-w-0 space-y-2 rounded-xl border p-4"><p className="text-xs text-muted-foreground">{label}</p><p className={cn("font-semibold tabular-nums", value == null ? "text-sm" : "text-2xl")}>{count(value as number | null)}</p></div>)}</div>
          <p className="text-xs leading-5 text-muted-foreground">Last {days} days · {selected.helpful + selected.not_helpful ? `${selected.helpful} helpful and ${selected.not_helpful} not-helpful ratings on answers citing this document.` : "No ratings recorded on answers citing this document."}</p>
          <div className="space-y-4 rounded-xl border p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="flex items-center gap-2 text-sm font-medium"><ClockIcon className="size-4 text-muted-foreground" />Content freshness</h3><FreshnessBadge document={selected} /></div><p className="text-xs leading-5 text-muted-foreground">{FRESHNESS[selected.freshness].description}</p>
            <dl className="space-y-3 text-xs"><div className="flex flex-wrap justify-between gap-2"><dt className="text-muted-foreground">Next review</dt><dd className="font-medium">{selected.freshness === "changed" || selected.freshness === "review_due" ? "Due now" : date(selected.review_due_at)}</dd></div>{[["Last reviewed", selected.reviewed_at], ["Last cited", selected.last_cited_at], ["Uploaded", selected.created_at], ["Indexed", selected.indexed_at]].map(([label, value]) => <div key={label} className="flex flex-wrap justify-between gap-2"><dt className="text-muted-foreground">{label}</dt><dd className="font-medium">{date(value)}</dd></div>)}</dl>
          </div>
          {saveError && <p role="alert" className="text-xs leading-5 text-destructive">{saveError}</p>}
          <p className="text-xs leading-5 text-muted-foreground">After checking this document’s content, mark this version as reviewed. This records your review without changing the document.</p>
          <div className="flex flex-wrap gap-2"><Button size="sm" disabled={saving || selected.freshness === "not_searchable"} onClick={() => void markReviewed(selected)}><CheckCircleIcon />{saving ? "Saving review…" : "Mark reviewed"}</Button><Button variant="outline" size="sm" asChild><Link href={`/projects/${encodeURIComponent(selectedProject)}?tab=files`}>Open files<ArrowRightIcon /></Link></Button></div>
        </div>}
        {!selected && <p role="status" className="px-6 pb-6 text-sm text-muted-foreground">This document is no longer in the current list. Close this panel and refresh the documents.</p>}
      </SheetContent>
    </Sheet>
  </section>
}
