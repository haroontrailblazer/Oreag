"use client"

import { useRef, useState } from "react"
import useSWR from "swr"
import { ArrowsClockwiseIcon, CheckCircleIcon, FlaskIcon, PlayIcon, StopIcon } from "@phosphor-icons/react/dist/ssr"
import { api, fetcher, isSessionExpired } from "@/lib/api"
import type { EvaluationRun } from "@/lib/evaluation"
import type { GapDetail } from "@/lib/knowledge-gaps"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import { Spinner } from "@/components/ui/spinner"
import { EvaluationCheckResults } from "@/components/evaluation-check-results"

type Case = { query_id: string; question: string; expected: string; source: string; match: "contains" }
type Verification = EvaluationRun & { gap_evidence_version: string; matches_current: boolean; reference_run_id: string | null }
type History = { content_version: number; runs: Verification[] }

export function GapVerification({ gap, days, resolutionRunId, onSelect }: { gap: GapDetail; days: string; resolutionRunId: string | null; onSelect: (id: string) => void }) {
  const endpoint = `/api/projects/${gap.item.project_id}/gaps/${gap.item.question_key}/verification`
  const { data, error, mutate } = useSWR<History>(endpoint, fetcher, { refreshInterval: value => value?.runs.some(run => ["preparing", "running"].includes(run.status)) ? 2000 : 15000 })
  const [editing, setEditing] = useState(false)
  const [cases, setCases] = useState<Case[]>([])
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState("")
  const [selected, setSelected] = useState("")
  const attempt = useRef<{ id: string; payload: string } | null>(null)
  const lock = useRef(false)
  const savedResolution = gap.item.status === "resolved" ? data?.runs.find(run => run.id === gap.item.verification_run_id) : undefined
  const run = data?.runs.find(run => run.id === selected) ?? savedResolution ?? data?.runs[0]
  const isAttached = run && gap.item.status === "resolved" && run.id === gap.item.verification_run_id
  const active = data?.runs.some(run => ["preparing", "running"].includes(run.status))
  const verified = run?.status === "completed" && run.results.length === run.suite.cases.length && run.results.every(result => result.status === "passed")
  const current = run?.matches_current && run.gap_evidence_version === gap.item.evidence_version
  const normalized = (question: string) => question.normalize("NFKC").trim().replace(/\s+/g, " ").toLowerCase()
  const questions = gap.evidence.filter((query, index, evidence) => evidence.findIndex(other => normalized(other.question) === normalized(query.question)) === index)
  async function start() {
    if (lock.current) return
    lock.current = true; setBusy(true); setFailure("")
    const payload = JSON.stringify({ evidence_version: gap.item.evidence_version, cases: cases.map(test => ({ query_id: test.query_id, expected: test.expected, source: test.source, match: test.match })) })
    if (attempt.current?.payload !== payload) attempt.current = { id: crypto.randomUUID(), payload }
    try {
      const result = await api<Verification>(`${endpoint}?days=${days}`, { method: "POST", body: JSON.stringify({ id: attempt.current.id, ...JSON.parse(payload) }) })
      setSelected(result.id); setEditing(false); attempt.current = null; await mutate()
    } catch (error) { if (!isSessionExpired(error)) setFailure(error instanceof Error ? error.message : "Could not start verification") }
    finally { lock.current = false; setBusy(false) }
  }
  async function cancel() {
    if (!run || lock.current) return
    lock.current = true; setBusy(true); setFailure("")
    try { await api(`/api/projects/${gap.item.project_id}/evaluations/runs/${run.id}/cancel`, { method: "POST" }); await mutate() }
    catch (error) { if (!isSessionExpired(error)) setFailure(error instanceof Error ? error.message : "Could not cancel verification") }
    finally { lock.current = false; setBusy(false) }
  }
  return <section aria-label="Verify gap fix" className="space-y-3 rounded-xl border bg-background p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="flex items-center gap-2 text-sm font-medium"><FlaskIcon aria-hidden="true" className="size-4 text-muted-foreground" />Verify fix</h3><Button size="sm" variant="outline" disabled={busy || active || !!error} onClick={() => setEditing(value => !value)}><PlayIcon aria-hidden="true" />{editing ? "Close setup" : "Verify fix"}</Button></div>
    <p className="text-xs leading-5 text-muted-foreground">Test affected questions against the current documents and settings. Review the answers, then select a passing run to resolve with verification.</p>
    {error && !isSessionExpired(error) && <div role="alert" className="space-y-2 text-xs"><p>Could not load verification history.</p><Button size="sm" variant="outline" onClick={() => void mutate()}>Retry</Button></div>}
    {editing && <div className="space-y-3">
      <p className="text-xs font-medium">Select questions from this evidence page ({cases.length}/20)</p>
      {questions.length < gap.evidence.length && <p className="text-xs text-muted-foreground">Repeated identical questions are shown once.</p>}
      <ul className="max-h-80 space-y-3 overflow-y-auto pr-1">{questions.map(query => {
        const test = cases.find(test => test.query_id === query.id)
        return <li key={query.id} className="space-y-3 rounded-lg border p-3"><label className="flex items-start gap-2 text-xs leading-5"><Checkbox checked={!!test} disabled={busy || (!test && cases.length >= 20) || query.question.length > 4000} onCheckedChange={checked => setCases(current => checked ? [...current, { query_id: query.id, question: query.question, expected: "", source: "", match: "contains" }] : current.filter(test => test.query_id !== query.id))} /><span className="min-w-0 [overflow-wrap:anywhere]">{query.question}</span></label>{test && <div className="space-y-2 pl-6"><label className="block space-y-1 text-xs">Answer should contain<Input value={test.expected} maxLength={4000} onChange={event => setCases(current => current.map(item => item.query_id === query.id ? { ...item, expected: event.target.value } : item))} placeholder="Optional expected phrase" disabled={busy} /></label><label className="block space-y-1 text-xs">Expected source<Input value={test.source} maxLength={500} onChange={event => setCases(current => current.map(item => item.query_id === query.id ? { ...item, source: event.target.value } : item))} placeholder="Optional filename" disabled={busy} /></label></div>}</li>
      })}</ul>
      <p className="text-xs leading-5 text-muted-foreground">Questions without expected text or a source are marked Not checked. Runs generate fresh answers and use your provider credits. Conversation history is not replayed.</p>
      <Button size="sm" disabled={busy || active || !cases.length} onClick={() => void start()}>{busy ? <Spinner size={14} /> : <PlayIcon aria-hidden="true" />}Run {cases.length || "selected"} {cases.length === 1 ? "question" : "questions"}</Button>
    </div>}
    {failure && <p role="alert" className="text-xs text-destructive">{failure}</p>}
    {run && <div className="space-y-3">
      {isAttached && <p className="flex items-center gap-2 text-xs font-medium"><CheckCircleIcon aria-hidden="true" className="size-4 text-emerald-700 dark:text-emerald-400" />Saved resolution evidence</p>}
      <div className="flex flex-wrap items-center gap-2"><Badge variant="outline">{run.status === "completed" ? verified ? "Checks passed" : "Review results" : run.status === "preparing" ? "Preparing documents" : run.status === "running" ? "Running checks" : run.status === "failed" ? "Run failed" : "Cancelled"}</Badge><span className="text-[11px] text-muted-foreground">{new Date(run.created_at).toLocaleString()}</span></div>
      {run.status === "completed" && !run.quality_report?.case_changes && <p className="text-xs leading-5 text-muted-foreground">{run.reference_run_id && !run.quality_report ? "Comparing with the previous matching test…" : "No earlier matching test is available. These results show how the answer performs now."}</p>}
      {!current && <p className="text-xs leading-5 text-muted-foreground">Documents, settings, or gap evidence changed since this run. Verify again to attach a current result.</p>}
      {run.error && <p role="alert" className="text-xs text-destructive">{run.error}</p>}
      <EvaluationCheckResults run={run} />
      <div className="flex flex-wrap gap-2">{verified && current && !isAttached && <Button size="sm" variant="outline" onClick={() => onSelect(run.id)}><CheckCircleIcon aria-hidden="true" />{resolutionRunId === run.id ? "Selected for resolution" : "Use for resolution"}</Button>}{["preparing", "running"].includes(run.status) && <Button size="sm" variant="outline" disabled={busy} onClick={() => void cancel()}><StopIcon aria-hidden="true" />Cancel run</Button>}<Button size="sm" variant="ghost" onClick={() => void mutate()}><ArrowsClockwiseIcon aria-hidden="true" />Refresh</Button>{savedResolution && !isAttached && <Button size="sm" variant="outline" onClick={() => setSelected(savedResolution.id)}>View resolution evidence</Button>}</div>
      {data && data.runs.length > 1 && <details className="text-xs"><summary className="w-fit cursor-pointer rounded-sm text-muted-foreground focus-visible:outline-2">Previous verification runs</summary><div className="mt-2 flex flex-wrap gap-2">{data.runs.map(item => <Button key={item.id} size="sm" variant="outline" onClick={() => setSelected(item.id)}>{new Date(item.created_at).toLocaleString()}</Button>)}</div></details>}
    </div>}
    {!run && !error && !editing && <p className="text-xs text-muted-foreground">{data ? "No verification runs yet." : "Loading verification history…"}</p>}
  </section>
}
