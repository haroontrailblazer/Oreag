"use client"
import { useState } from "react"
import useSWR from "swr"
import { api, fetcher } from "@/lib/api"
import type { SavedEvaluation } from "@/lib/evaluation"
import type { QueryRecord } from "@/lib/query-explorer"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Input } from "@/components/ui/input"
import { FilterSelect } from "@/components/filter-select"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"

export function QueryTimeline({ query }: { query: QueryRecord }) {
  const timeline = query.timeline
  return <section className="space-y-3 rounded-xl border p-4"><h3 className="text-sm font-medium">Query timeline</h3>
    {!timeline ? <p className="text-xs text-muted-foreground">Timing was not recorded for this query.</p> : <>
      <ol className="space-y-3">{timeline.spans.map((span, index) => <li key={index} className="space-y-1.5 text-xs"><div className="flex justify-between gap-2"><span className="capitalize">{span.stage}{!span.success && " · interrupted"}</span><span className="tabular-nums">{span.duration_ms.toFixed(1)} ms</span></div><div className="h-1.5 overflow-hidden rounded bg-muted"><div className="h-full rounded bg-foreground/60" style={{ marginLeft: `${Math.min(100, span.start_ms / Math.max(1, timeline.total_ms) * 100)}%`, width: `${Math.max(.5, Math.min(100, span.duration_ms / Math.max(1, timeline.total_ms) * 100))}%` }} /></div></li>)}</ol>
      {!timeline.spans.length && <p className="text-xs text-muted-foreground">No provider or retrieval stages ran; this query may have used the cache.</p>}
      <p className="text-xs leading-5 text-muted-foreground">Stages can overlap: retrieval includes embedding and translation. Unlisted stages were skipped or unmeasured.</p>
    </>}
  </section>
}

export function AddQueryToSet({ query }: { query: QueryRecord }) {
  const [open, setOpen] = useState(false), [expected, setExpected] = useState(""), [source, setSource] = useState(""), [match, setMatch] = useState("contains")
  const [busy, setBusy] = useState(false), [message, setMessage] = useState("")
  const base = `/api/projects/${query.project_id}/evaluations`
  const { data, error, mutate } = useSWR<SavedEvaluation>(open ? `${base}/suite` : null, fetcher)
  async function add() {
    if (!data) return
    setBusy(true); setMessage("")
    try {
      const saved = await api<SavedEvaluation>(`${base}/cases/from-query`, { method: "POST", body: JSON.stringify({ query_id: query.id, revision: data.revision, expected, source, match }) })
      await mutate(saved, { revalidate: false }); setOpen(false); setMessage("Added to the project’s evaluator test set.")
    } catch (e) { setMessage(e instanceof Error ? e.message : "Could not add question."); void mutate() }
    finally { setBusy(false) }
  }
  return <><Button variant="outline" size="sm" onClick={() => { setMessage(""); setOpen(true) }}>Add to test set</Button>
    {!open && message && <p role="status" className="text-xs">{message}</p>}
    <Dialog open={open} onOpenChange={setOpen}><DialogContent className="max-h-[85dvh] overflow-y-auto"><DialogHeader><DialogTitle>Add to test set</DialogTitle><DialogDescription>Save this question with the answer you expect. Check future changes in Evaluator.</DialogDescription></DialogHeader>
      <p className="max-h-32 overflow-y-auto whitespace-pre-wrap break-words rounded-lg border p-3 text-sm">{query.question}</p>
      <label className="space-y-2 text-xs">Expected answer<Textarea maxLength={4000} value={expected} onChange={e => setExpected(e.target.value)} /></label>
      <FilterSelect label="Answer check" value={match} onChange={setMatch} options={[{ value: "contains", label: "Contains expected text" }, { value: "exact", label: "Exact text match" }]} />
      <label className="space-y-2 text-xs">Expected source filename (optional)<Input maxLength={500} value={source} onChange={e => setSource(e.target.value)} /></label>
      {(message || error) && <p role="alert" className="text-xs">{message || "Could not load the saved set."}</p>}
      <Button disabled={busy || !data || !!error || (!expected.trim() && !source.trim())} onClick={() => void add()}>Add question</Button>
    </DialogContent></Dialog></>
}
