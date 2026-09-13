"use client"

import { useState } from "react"
import useSWR from "swr"
import { ArrowsClockwiseIcon, CheckCircleIcon, FilesIcon, ScalesIcon, XCircleIcon } from "@phosphor-icons/react/dist/ssr"
import { api, fetcher, isSessionExpired } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Spinner } from "@/components/ui/spinner"
import { FilterSelect } from "@/components/filter-select"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"

type Passage = { file_id: string; filename: string; page_number: number | null; passage: string; in_force_from: string | null; in_force_to: string | null; version_label: string | null }
type Conflict = { key: string; reason: string; left: Passage; right: Passage; status: "open" | "confirmed" | "dismissed"; note: string | null; revision: number }
type Report = { items: Conflict[]; scanned_passages: number; scan_limit: number; limited: boolean; content_version: number }
const statusLabel = { open: "Needs review", confirmed: "Confirmed conflict", dismissed: "Not a conflict" }
const dateLabel = (value: string) => new Date(`${value}T00:00:00Z`).toLocaleDateString(undefined, { dateStyle: "medium", timeZone: "UTC" })

function ConflictReview({ item, endpoint, version, onSaved }: { item: Conflict; endpoint: string; version: number; onSaved: (value: Conflict) => Promise<void> }) {
  const [note, setNote] = useState(item.note ?? "")
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState("")
  async function save(status: Conflict["status"]) {
    setBusy(true); setFailure("")
    try {
      const result = await api<Conflict>(`${endpoint}/${item.key}`, { method: "PUT", body: JSON.stringify({ status, note, revision: item.revision, content_version: version }) })
      await onSaved(result)
    } catch (error) { if (!isSessionExpired(error)) setFailure(error instanceof Error ? error.message : "Could not save review") }
    finally { setBusy(false) }
  }
  return <article className="space-y-4 rounded-xl border bg-card p-4">
    <div className="flex flex-wrap items-start justify-between gap-2"><h3 className="min-w-0 flex-1 text-sm font-medium leading-6">{item.reason}</h3><Badge variant="outline">{statusLabel[item.status]}</Badge></div>
    <div className="grid min-w-0 gap-3 sm:grid-cols-2">{[item.left, item.right].map((source, index) => <section key={index} className="min-w-0 space-y-2 rounded-lg bg-muted/30 p-3">
      <h4 className="flex items-start gap-2 text-xs font-medium"><FilesIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" /><span className="[overflow-wrap:anywhere]">{source.filename}{source.page_number != null ? ` · Page ${source.page_number}` : ""}</span></h4>
      <p className="text-[11px] leading-5 text-muted-foreground">{source.version_label ? `${source.version_label} · ` : ""}{source.in_force_from ? `Effective from ${dateLabel(source.in_force_from)}` : "Effective date not specified"}</p>
      <blockquote className="whitespace-pre-wrap text-sm leading-6 [overflow-wrap:anywhere]">{source.passage}</blockquote>
    </section>)}</div>
    <label className="block space-y-2 text-xs font-medium">Review note<Textarea value={note} onChange={event => setNote(event.target.value)} maxLength={2000} disabled={busy} placeholder="Explain which source applies, or why these statements can coexist." className="min-h-20" /></label>
    <div className="flex flex-wrap gap-2"><Button size="sm" disabled={busy} onClick={() => void save("confirmed")}>{busy ? <Spinner size={14} /> : <CheckCircleIcon aria-hidden="true" />}Confirm conflict</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => void save("dismissed")}><XCircleIcon aria-hidden="true" />Not a conflict</Button>{item.status !== "open" && <Button size="sm" variant="ghost" disabled={busy} onClick={() => void save("open")}><ArrowsClockwiseIcon aria-hidden="true" />Reopen review</Button>}</div>
    {failure && <p role="alert" className="text-xs text-destructive">{failure}</p>}
  </article>
}

export function SourceConflicts({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState("open")
  const [message, setMessage] = useState("")
  const endpoint = `/api/projects/${projectId}/source-conflicts`
  const { data, error, isValidating, mutate } = useSWR<Report>(open ? endpoint : null, fetcher, { revalidateOnFocus: false })
  const items = data?.items.filter(item => status === "all" || item.status === status) ?? []
  async function saved(item: Conflict) {
    await mutate(current => current ? { ...current, items: current.items.map(row => row.key === item.key ? item : row) } : current, { revalidate: false })
    setMessage(`Review saved: ${statusLabel[item.status].toLowerCase()}.`)
  }
  return <>
    <Button variant="outline" size="icon" className="lg:w-28 lg:px-3" onClick={() => setOpen(true)} aria-label="Review source conflicts" title="Review source conflicts"><ScalesIcon aria-hidden="true" /><span className="hidden lg:inline">Conflicts</span></Button>
    <Sheet open={open} onOpenChange={setOpen}><SheetContent side="right" className="w-full max-w-full bg-background sm:w-[860px] sm:max-w-[calc(100vw-2rem)]">
      <SheetHeader className="p-6 pr-12"><SheetTitle className="flex items-center gap-2 text-lg"><ScalesIcon aria-hidden="true" className="size-5 text-muted-foreground" />Source conflicts</SheetTitle><SheetDescription>Compare possible disagreements and decide whether they matter.</SheetDescription></SheetHeader>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 pb-6">
        <p className="text-xs leading-5 text-muted-foreground">Checks matching English statements for different numbers or explicit negation in currently effective, indexed documents. These are candidates for review. Saving a decision does not edit documents or change answers.</p>
        <div className="flex flex-wrap items-end justify-between gap-3"><div className="w-full sm:w-52"><FilterSelect label="Review status" value={status} onChange={setStatus} options={[{ value: "open", label: "Needs review" }, { value: "confirmed", label: "Confirmed conflicts" }, { value: "dismissed", label: "Not a conflict" }, { value: "all", label: "All comparisons" }]} /></div><Button variant="outline" size="sm" disabled={isValidating} onClick={() => { setMessage(""); void mutate() }}><ArrowsClockwiseIcon aria-hidden="true" />Refresh comparisons</Button></div>
        {message && <p role="status" className="text-xs text-muted-foreground">{message}</p>}
        {error && !isSessionExpired(error) ? <div role="alert" className="space-y-2 rounded-xl border p-4 text-xs"><p>Could not load source comparisons.</p><Button variant="outline" size="sm" onClick={() => void mutate()}>Retry</Button></div>
          : !data ? <p role="status" className="py-12 text-center text-xs text-muted-foreground">Comparing indexed passages…</p>
          : <>
            <p className="text-xs text-muted-foreground">{items.length} {items.length === 1 ? "comparison" : "comparisons"} · {data.scanned_passages.toLocaleString()} passages scanned{data.limited ? " · Scan limit reached" : ""}</p>
            {data.limited && <p className="rounded-lg bg-muted/30 p-3 text-xs leading-5 text-muted-foreground">This bounded scan covers up to {data.scan_limit.toLocaleString()} passages and 100 comparisons. Additional disagreements may exist outside these results.</p>}
            {items.length ? items.map(item => <ConflictReview key={`${item.key}:${item.revision}`} item={item} endpoint={endpoint} version={data.content_version} onSaved={saved} />) : <div className="space-y-2 rounded-xl border p-8 text-center"><ScalesIcon aria-hidden="true" className="mx-auto size-7 text-muted-foreground" /><p className="text-sm font-medium">No comparisons in this view</p><p className="text-xs leading-5 text-muted-foreground">{status === "open" ? "No matching statements need review in the scanned passages. This does not check every possible disagreement." : "Choose another review status to see other comparisons."}</p></div>}
          </>}
      </div>
    </SheetContent></Sheet>
  </>
}
