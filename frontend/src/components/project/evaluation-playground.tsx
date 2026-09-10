"use client"

import { useEffect, useRef, useState } from "react"
import useSWR, { useSWRConfig } from "swr"
import { ArrowLeftIcon, PlusIcon, PlayIcon, StopIcon, DownloadSimpleIcon, UploadSimpleIcon, TrashIcon, FloppyDiskIcon, FlaskIcon } from "@phosphor-icons/react/dist/ssr"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { FilterSelect } from "@/components/filter-select"
import { AnswerMarkdown } from "./answer-markdown"
import { AnswerFeedback } from "@/components/answer-feedback"
import { EvaluationConfigCard } from "./evaluation-config"
import { api, fetcher, isSessionExpired } from "@/lib/api"
import { importEvaluation, MAX_CASES, projectEvaluationConfig, type EvaluationCase, type EvaluationDefinition, type EvaluationRun, type SavedEvaluation } from "@/lib/evaluation"
import { queryLatency } from "@/lib/query-explorer"
import type { ModelsResponse, Project } from "@/lib/types"
import { cn } from "@/lib/utils"

const newCase = (): EvaluationCase => ({ id: crypto.randomUUID(), question: "", expected: "", match: "contains", source: "" })
const active = (run: EvaluationRun) => run.status === "preparing" || run.status === "running"
function download(name: string, value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }))
  const a = document.createElement("a"); a.href = url; a.download = name; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function EvaluationPlayground({ project, onBack }: { project: Project; onBack: () => void }) {
  const base = `/api/projects/${project.id}/evaluations`
  const { data: saved, error: loadError, mutate: reload } = useSWR<SavedEvaluation>(`${base}/suite`, fetcher, { revalidateOnFocus: false })
  const { data: models, error: modelsError } = useSWR<ModelsResponse>("/api/models", fetcher)
  const { data: history, mutate: reloadHistory } = useSWR<EvaluationRun[]>(`${base}/runs`, fetcher)
  const baseline = projectEvaluationConfig(project)
  const [draft, setDraft] = useState<EvaluationDefinition | null>(null)
  const [draftRevision, setDraftRevision] = useState<number | null>(null)
  const suite = draft ?? saved?.suite ?? { version: 2, cases: [], variants: [baseline, { ...baseline, top_k: baseline.top_k === 10 ? 5 : 10 }] } as EvaluationDefinition
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [run, setRun] = useState<EvaluationRun | null>(null)
  const [running, setRunning] = useState(false)
  const [saving, setSaving] = useState(false)
  const [starting, setStarting] = useState(false)
  const startingRef = useRef(false)
  const controller = useRef<AbortController | null>(null)
  const mounted = useRef(true)
  const fileInput = useRef<HTMLInputElement>(null)
  const { mutate } = useSWRConfig()
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; controller.current?.abort() } }, [])
  function update(next: EvaluationDefinition) { if (draftRevision === null) setDraftRevision(saved?.revision ?? 0); setDraft(next); setError(""); setNotice("") }
  function edit(id: string, patch: Partial<EvaluationCase>) { update({ ...suite, cases: suite.cases.map(item => item.id === id ? { ...item, ...patch } : item) }) }
  function showError(err: unknown) { if (!isSessionExpired(err)) setError(err instanceof Error ? err.message : "Request failed.") }

  async function save() {
    if (suite.cases.some(c => !c.question.trim())) throw new Error("Fill in each question before saving.")
    setSaving(true)
    try {
      const result = await api<SavedEvaluation>(`${base}/suite`, { method: "PUT", body: JSON.stringify({ revision: draftRevision ?? saved?.revision ?? 0, suite }) })
      await reload(result, { revalidate: false })
      setDraft(null); setDraftRevision(null); setNotice("Test set and configurations saved to the database.")
      return result.suite!
    } finally { setSaving(false) }
  }
  async function drive(current: EvaluationRun) {
    const abort = new AbortController(); controller.current = abort; setRunning(true); setError("")
    try {
      while (active(current) && !abort.signal.aborted) {
        current = await api<EvaluationRun>(`${base}/runs/${current.id}/advance`, { method: "POST", signal: abort.signal })
        if (mounted.current) setRun(current)
      }
    } catch (err) { if (!abort.signal.aborted && mounted.current) showError(err) }
    finally {
      if (controller.current === abort) controller.current = null
      if (mounted.current) { setRunning(false); void reloadHistory() }
      // Provider spend remains visible, but evaluation does not change live query metrics.
      void mutate((key: unknown) => typeof key === "string" && key.startsWith("/api/account/usage"))
    }
  }
  async function start() {
    if (controller.current || saving || startingRef.current) return
    startingRef.current = true; setStarting(true)
    setError("")
    try {
      if (!suite.cases.length) throw new Error("Add at least one question.")
      const snapshot = await save()
      const current = await api<EvaluationRun>(`${base}/runs`, { method: "POST", body: JSON.stringify({ id: crypto.randomUUID(), suite: snapshot }) })
      setRun(current); await drive(current)
    } catch (err) { showError(err) } finally { startingRef.current = false; setStarting(false) }
  }
  async function resume() {
    if (!run || controller.current) return
    try { const current = await api<EvaluationRun>(`${base}/runs/${run.id}/resume`, { method: "POST" }); setRun(current); await drive(current) } catch (err) { showError(err) }
  }
  async function stop() {
    if (!run) return
    // Stop issuing steps immediately; the in-flight server step observes DB cancellation.
    controller.current?.abort()
    try { setRun(await api<EvaluationRun>(`${base}/runs/${run.id}/cancel`, { method: "POST" })); void reloadHistory() } catch (err) { showError(err) }
  }
  async function selectRun(id: string) {
    try { setRun(await api<EvaluationRun>(`${base}/runs/${id}`)) } catch (err) { showError(err) }
  }
  async function removeRun() {
    if (!run) return
    try { await api(`${base}/runs/${run.id}`, { method: "DELETE" }); setRun(null); void reloadHistory() } catch (err) { showError(err) }
  }
  async function importFile(file?: File) {
    if (!file) return
    try { if (file.size > 256_000) throw new Error("Choose a test set smaller than 256 KB."); update(importEvaluation(JSON.parse(await file.text()), baseline)) } catch (err) { showError(err) }
  }
  const busy = running || saving || starting
  const ready = !!saved && !!models && !loadError
  // Anchor hidden labels inside this content so they cannot extend the page
  // beyond the evaluator's scroll container, especially on mobile.
  return <div className="relative min-w-0 space-y-5 pb-5">
    <header className="space-y-3 border-b pb-4">
      <Button variant="ghost" size="sm" className="-ml-2 text-muted-foreground" onClick={onBack}><ArrowLeftIcon />Back to conversation</Button>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="text-xl font-semibold tracking-tight">Evaluator</h2><p className="mt-1 text-xs text-muted-foreground">Compare complete model configurations against the same knowledge snapshot.</p></div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" disabled={!ready || busy} onClick={() => void save().catch(showError)}><FloppyDiskIcon />Save set</Button>
          {running ? <Button variant="outline" size="sm" onClick={() => void stop()}><StopIcon />Stop run</Button> : <Button size="sm" disabled={!ready || busy || !suite.cases.length} onClick={() => void start()}><PlayIcon />Run comparison</Button>}
        </div>
      </div>
    </header>
    {(error || loadError || modelsError) && <div role="alert" className="space-y-2 rounded-lg border border-destructive/30 p-3 text-sm"><p>{error || "Could not load saved evaluations or available models."}</p><Button variant="outline" size="sm" onClick={() => { setError(""); void reload(); void mutate("/api/models") }}>Retry loading</Button></div>}
    {notice && <p role="status" className="text-xs text-muted-foreground">{notice}</p>}
    <fieldset disabled={!ready || busy} className="min-w-0 space-y-4 disabled:opacity-60">
      <legend className="sr-only">Evaluation settings</legend>
      <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-medium">Configurations</h3><label className="flex items-center gap-2 text-xs"><input type="checkbox" className="accent-foreground" checked={suite.variants.length === 2} onChange={e => update({ ...suite, variants: e.target.checked ? [suite.variants[0], { ...suite.variants[0] }] : [suite.variants[0]] })} />Compare two configurations</label></div>
      {models && <div className={cn("grid gap-4", suite.variants.length === 2 && "lg:grid-cols-2")}>{suite.variants.map((config, index) => <EvaluationConfigCard key={index} value={config} index={index} models={models} project={project} onChange={value => update({ ...suite, variants: suite.variants.map((v, i) => i === index ? value : v) })} />)}</div>}
      <p className="text-xs leading-5 text-muted-foreground">Evaluation settings, scores, and feedback stay in this workspace. Live project settings, vectors, query history, and Health metrics are unchanged. Provider spend is still metered separately as evaluation usage.</p>
      <section className="overflow-hidden rounded-xl border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b p-3"><h3 className="text-sm font-medium">Test set <span className="text-muted-foreground">{suite.cases.length}/{MAX_CASES}</span></h3><div className="flex gap-1">
          <input ref={fileInput} type="file" accept="application/json,.json" aria-label="Import test set file" className="hidden" onChange={e => { void importFile(e.target.files?.[0]); e.target.value = "" }} />
          <Button variant="ghost" size="icon" className="size-8" aria-label="Import test set" onClick={() => fileInput.current?.click()}><UploadSimpleIcon /></Button>
          <Button variant="ghost" size="icon" className="size-8" aria-label="Export test set" onClick={() => download("evaluation-test-set.json", suite)}><DownloadSimpleIcon /></Button>
          <Button variant="outline" size="sm" disabled={suite.cases.length >= MAX_CASES} onClick={() => update({ ...suite, cases: [...suite.cases, newCase()] })}><PlusIcon />Add question</Button>
        </div></div>
        {!suite.cases.length ? <div className="space-y-2 px-5 py-8 text-center"><FlaskIcon className="mx-auto size-6 text-muted-foreground" /><p className="text-sm font-medium">Add the questions your application needs to answer</p><p className="text-xs text-muted-foreground">Optional text and source checks make comparisons repeatable.</p></div> : <ol className="divide-y">{suite.cases.map((item, index) => <li key={item.id} className="space-y-3 p-4">
          <div className="flex items-center justify-between"><h4 className="text-xs font-medium">Question {index + 1}</h4><Button variant="ghost" size="icon" className="size-8" aria-label={`Remove question ${index + 1}`} onClick={() => update({ ...suite, cases: suite.cases.filter(c => c.id !== item.id) })}><TrashIcon /></Button></div>
          <label className="block space-y-1.5 text-xs">Question<Textarea maxLength={4000} value={item.question} onChange={e => edit(item.id, { question: e.target.value })} placeholder="What should your application ask?" /></label>
          <div className="grid gap-3 md:grid-cols-2"><label className="block space-y-1.5 text-xs">Expected answer text<Textarea maxLength={4000} value={item.expected} onChange={e => edit(item.id, { expected: e.target.value })} placeholder="Optional expected text" /></label><div className="space-y-3"><FilterSelect label={`Question ${index + 1} text check`} value={item.match} onChange={v => edit(item.id, { match: v as EvaluationCase["match"] })} options={[{ value: "contains", label: "Contains expected text" }, { value: "exact", label: "Exact text match" }]} /><label className="block space-y-1.5 text-xs">Expected source filename<Input maxLength={500} value={item.source} onChange={e => edit(item.id, { source: e.target.value })} placeholder="Optional filename" /></label></div></div>
        </li>)}</ol>}
      </section>
    </fieldset>
    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground"><p>{draft ? "Unsaved changes" : saved?.suite ? "Saved in the project database" : "Create and save a test set"} · Text checks ignore case and extra whitespace.</p>{draft && <Button variant="ghost" size="sm" disabled={busy} onClick={() => { setDraft(null); setDraftRevision(null); void reload() }}>Load saved set</Button>}</div>
    <section aria-label="Saved evaluation runs" className="space-y-3 border-t pt-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-sm font-semibold">Saved runs</h3><div className="w-full min-w-0 sm:w-72"><FilterSelect label="Choose a saved run" hideLabel value={run?.id ?? ""} onChange={id => { if (id && !running) void selectRun(id) }} options={[{ value: "", label: history?.length ? "Select a run" : "No runs yet" }, ...(history ?? []).map(r => ({ value: r.id, label: `${new Date(r.created_at).toLocaleString()} · ${r.status}` }))]} /></div></div>
      {run && <>
        <div className="flex flex-wrap items-center justify-between gap-2"><p role="status" className="text-sm capitalize">{run.status} · {run.prepared}/{run.corpus_count * run.suite.variants.length} vectors · {run.results.length}/{run.suite.cases.length * run.suite.variants.length} answers</p><div className="flex flex-wrap gap-2">
          {!running && (active(run) || run.status === "failed") && <Button variant="outline" size="sm" onClick={() => void resume()}><PlayIcon />Resume run</Button>}
          {!running && active(run) && <Button variant="outline" size="sm" onClick={() => void stop()}>Cancel run</Button>}
          <Button variant="outline" size="sm" onClick={() => download("evaluation-results.json", run)}><DownloadSimpleIcon />Export results</Button>
          {!running && !active(run) && <Button variant="ghost" size="icon" aria-label="Delete saved run" onClick={() => void removeRun()}><TrashIcon /></Button>}
        </div></div>
        {run.error && <p role="alert" className="text-sm text-destructive">{run.error}</p>}
        <p className="text-xs leading-5 text-muted-foreground">{new Date(run.created_at).toLocaleString()} · {run.corpus_count} source passages. Results use this run’s saved configurations. Pass counts measure text/source rules, not factual accuracy.</p>
        <div className={cn("grid gap-3", run.suite.variants.length === 2 && "md:grid-cols-2")}>{run.suite.variants.map((config, variant) => {
          const results = run.results.filter(r => r.variant === variant), checked = results.filter(r => r.status === "passed" || r.status === "failed")
          const measured = results.flatMap(r => r.response?.latency_ms != null ? [r.response.latency_ms] : [])
          return <div key={variant} className="min-w-0 space-y-1 rounded-xl border p-3 text-xs leading-5"><h4 className="break-words font-medium">{variant === 0 ? "A" : "B"} · {config.llm_provider}/{config.llm_model}</h4><p className="break-words text-muted-foreground">{config.embedding_provider}/{config.embedding_model} · {config.embedding_dimensions} dimensions · top_k {config.top_k}</p><p>{results.filter(r => r.status === "passed").length}/{checked.length} checked passed · {results.filter(r => r.status === "review").length} to review</p><p>Mean latency: {measured.length ? queryLatency(Math.round(measured.reduce((a, b) => a + b, 0) / measured.length)) : "Not measured"}</p></div>
        })}</div>
        {run.suite.cases.map((item, index) => <article key={item.id} className="overflow-hidden rounded-xl border"><div className="space-y-1 border-b bg-muted/20 p-4"><h4 className="break-words text-sm font-medium">{index + 1}. {item.question}</h4>{item.expected && <p className="break-words text-xs text-muted-foreground">Expected ({item.match}): {item.expected}</p>}{item.source && <p className="break-words text-xs text-muted-foreground">Source: {item.source}</p>}</div><div className={cn("grid", run.suite.variants.length === 2 && "md:grid-cols-2")}>{run.suite.variants.map((config, variant) => {
          const result = run.results.find(r => r.caseId === item.id && r.variant === variant)
          return <div key={variant} className={cn("min-w-0 space-y-3 p-4", variant === 1 && "border-t md:border-t-0 md:border-l")}><div className="flex items-center justify-between gap-2 text-xs"><span className="font-medium">{variant === 0 ? "A" : "B"}</span><span className={cn("rounded-full bg-muted px-2 py-1 capitalize", result?.status === "passed" && "bg-emerald-500/10 text-emerald-600", result?.status === "failed" && "bg-red-500/10 text-red-600")}>{result?.status ?? (active(run) ? "Pending" : "Not run")}</span></div>{result?.response && <><p className="break-words text-xs text-muted-foreground">{queryLatency(result.response.latency_ms)} · {result.response.model} · Fresh answer</p><div className="max-h-80 overflow-y-auto break-words text-sm"><AnswerMarkdown>{result.response.answer}</AnswerMarkdown></div><details className="text-xs"><summary className="cursor-pointer">Sources ({result.response.sources.length})</summary><ul className="mt-2 space-y-2">{result.response.sources.map((source, i) => <li key={i} className="rounded-lg border p-2"><p className="break-words font-medium">{source.filename}{source.page_number != null ? ` · p.${source.page_number}` : ""}</p><p className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap break-words leading-5 text-muted-foreground">{source.content}</p></li>)}</ul></details>{!active(run) && <AnswerFeedback key={`${run.id}:${index}:${variant}`} queryId="evaluation" initialRating={result.feedback_rating} initialNote={result.feedback_note}
 resourceUrl={`${base}/runs/${run.id}/results/${run.results.indexOf(result)}/feedback`}
 onSaved={(feedback_rating, feedback_note) => setRun(current => current ? { ...current, results: current.results.map(r => r.caseId === item.id && r.variant === variant ? { ...r, feedback_rating, feedback_note } : r) } : current)} /> }</>}</div>
        })}</div></article>)}
      </>}
    </section>
  </div>
}
