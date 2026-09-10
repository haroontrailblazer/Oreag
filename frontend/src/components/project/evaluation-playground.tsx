"use client"

import { useEffect, useRef, useState } from "react"
import { useSWRConfig } from "swr"
import { PlusIcon, PlayIcon, StopIcon, DownloadSimpleIcon, UploadSimpleIcon, TrashIcon, FlaskIcon } from "@phosphor-icons/react/dist/ssr"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { FilterSelect } from "@/components/filter-select"
import { AnswerMarkdown } from "./answer-markdown"
import { AnswerFeedback } from "@/components/answer-feedback"
import { api, isSessionExpired } from "@/lib/api"
import { createClient } from "@/lib/supabase/client"
import { MAX_CASES, parseSuite, runEvaluation, type EvaluationCase, type EvaluationResult, type EvaluationSuite } from "@/lib/evaluation"
import { queryCacheLabel, queryLatency } from "@/lib/query-explorer"
import type { Project, QueryResponse } from "@/lib/types"
import { cn } from "@/lib/utils"

type Run = { suite: EvaluationSuite; startedAt: string; model: string; results: EvaluationResult[]; finished: boolean }
const newCase = (): EvaluationCase => ({ id: crypto.randomUUID(), question: "", expected: "", match: "contains", source: "" })

function download(name: string, value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }))
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = name
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function EvaluationPlayground({ project }: { project: Project }) {
  const [suite, setSuite] = useState<EvaluationSuite>({ version: 1, cases: [], topK: [project.top_k, project.top_k === 10 ? 5 : 10], compare: true })
  const [ready, setReady] = useState(false)
  const [storageKey, setStorageKey] = useState<string | null>(null)
  const [saveMessage, setSaveMessage] = useState("Loading saved test set…")
  const [error, setError] = useState("")
  const [run, setRun] = useState<Run | null>(null)
  const [running, setRunning] = useState(false)
  const controller = useRef<AbortController | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const { mutate } = useSWRConfig()

  useEffect(() => {
    let active = true
    const client = createClient()
    void client.auth.getSession().then(({ data }) => {
      if (!active) return
      if (!data.session) { setReady(true); setSaveMessage("Export your test set to keep it."); return }
      const key = `oreag:evaluation:v1:${data.session.user.id}:${project.id}`
      try {
        const stored = localStorage.getItem(key)
        if (stored) setSuite(parseSuite(JSON.parse(stored)))
        setStorageKey(key)
        setSaveMessage("Test set saved in this browser. Results stay in this session.")
      } catch {
        setSaveMessage("Saved test set could not be loaded. Import a backup or start a new test set.")
      }
      setReady(true)
    }).catch(() => { if (active) { setReady(true); setSaveMessage("Browser saving unavailable. Export your test set to keep it.") } })
    return () => { active = false; controller.current?.abort() }
  }, [project.id])

  function update(next: EvaluationSuite) {
    setSuite(next)
    setError("")
    if (storageKey) {
      try { localStorage.setItem(storageKey, JSON.stringify(next)); setSaveMessage("Test set saved in this browser. Results stay in this session.") }
      catch { setSaveMessage("Browser saving unavailable. Export your test set to keep it.") }
    }
  }

  function edit(id: string, patch: Partial<EvaluationCase>) {
    update({ ...suite, cases: suite.cases.map(item => item.id === id ? { ...item, ...patch } : item) })
  }

  async function importFile(file?: File) {
    if (!file) return
    try {
      if (file.size > 256_000) throw new Error("Choose a test set smaller than 256 KB.")
      const imported = parseSuite(JSON.parse(await file.text()))
      update(imported)
    } catch (err) { setError(err instanceof Error ? err.message : "Could not import test set.") }
  }

  async function start() {
    if (controller.current || !ready) return
    if (!suite.cases.length || suite.cases.some(item => !item.question.trim())) { setError("Add a question to every test case before running."); return }
    if (suite.compare && suite.topK[0] === suite.topK[1]) { setError("Choose different retrieval counts for A and B."); return }
    const snapshot = parseSuite(suite)
    const abort = new AbortController()
    controller.current = abort
    setError("")
    setRunning(true)
    setRun({ suite: snapshot, startedAt: new Date().toISOString(), model: `${project.llm_provider}/${project.llm_model}`, results: [], finished: false })
    try {
      await runEvaluation(snapshot, async (question, topK, signal) => {
        // Isolated questions, with the exact same contract as public POST /query.
        return api<QueryResponse>(`/api/projects/${project.id}/query`, {
          method: "POST", signal, body: JSON.stringify({ question, top_k: topK }),
        })
      }, abort.signal, result => {
        setRun(previous => previous ? { ...previous, results: [...previous.results, result] } : previous)
      })
    } catch (err) {
      if (!isSessionExpired(err)) setError(err instanceof Error ? err.message : "Evaluation failed.")
    } finally {
      controller.current = null
      setRunning(false)
      setRun(previous => previous ? { ...previous, finished: true } : previous)
      void mutate((key: unknown) => typeof key === "string" && (key.startsWith("/api/account/queries") || key === "/api/account/knowledge-health" || key === `/api/projects/${project.id}/query-stats`))
    }
  }

  const total = suite.cases.length * (suite.compare ? 2 : 1)
  const runTotal = run ? run.suite.cases.length * (run.suite.compare ? 2 : 1) : 0
  return <div className="min-w-0 space-y-4 pb-4">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 space-y-1">
        <h2 className="text-lg font-semibold">Evaluation playground</h2>
        <p className="text-xs leading-5 text-muted-foreground">Test expected answers and compare retrieval settings on the same questions.</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <input ref={fileInput} type="file" accept="application/json,.json" aria-label="Import test set file" className="hidden" onChange={event => { void importFile(event.target.files?.[0]); event.target.value = "" }} />
        <Button variant="outline" size="sm" disabled={!ready || running} onClick={() => fileInput.current?.click()}><UploadSimpleIcon />Import</Button>
        <Button variant="outline" size="sm" disabled={!ready || !suite.cases.length} onClick={() => download("evaluation-test-set.json", suite)}><DownloadSimpleIcon />Export set</Button>
        {running ? <Button variant="outline" size="sm" onClick={() => controller.current?.abort()}><StopIcon />Stop</Button> :
          <Button size="sm" disabled={!ready || !suite.cases.length} onClick={() => void start()}><PlayIcon />Run {total ? `${total} ${total === 1 ? "query" : "queries"}` : "tests"}</Button>}
      </div>
    </header>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 p-3 text-sm text-destructive">{error}</p>}
    <fieldset disabled={running || !ready} className="min-w-0 space-y-4 disabled:opacity-70">
      <legend className="sr-only">Evaluation configuration</legend>
      <div className="space-y-3 rounded-xl border bg-card p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-sm font-medium">Query settings</h3>
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" className="accent-foreground" checked={suite.compare} onChange={event => update({ ...suite, compare: event.target.checked })} />Compare A / B</label>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {(suite.compare ? [0, 1] : [0]).map(variant => <div key={variant} className="space-y-2 rounded-lg border p-3 text-xs">
            <p className="font-medium">{variant === 0 ? "A · Baseline" : "B · Comparison"}</p>
            <FilterSelect label={`Variant ${variant === 0 ? "A" : "B"} retrieved chunks (top_k)`} value={String(suite.topK[variant])} onChange={value => {
              const topK: [number, number] = [...suite.topK]
              topK[variant] = Number(value)
              update({ ...suite, topK })
            }} options={Array.from({ length: 20 }, (_, i) => ({ value: String(i + 1), label: String(i + 1) }))} />
          </div>)}
        </div>
        <p className="break-words text-xs leading-5 text-muted-foreground">Both use {project.llm_provider}/{project.llm_model} and the project’s answer policy. Each question runs independently. Normal caching and usage charges apply; completed queries appear in Queries and Health.</p>
      </div>
      <section className="overflow-hidden rounded-xl border bg-card">
        <div className="flex items-center justify-between gap-2 border-b px-4 py-3">
          <h3 className="text-sm font-medium">Test set <span className="ml-1 text-muted-foreground">{suite.cases.length}/{MAX_CASES}</span></h3>
          <Button variant="outline" size="sm" disabled={suite.cases.length >= MAX_CASES} onClick={() => update({ ...suite, cases: [...suite.cases, newCase()] })}><PlusIcon />Add question</Button>
        </div>
        {!suite.cases.length ? <div className="space-y-2 px-5 py-8 text-center">
          <FlaskIcon className="mx-auto size-6 text-muted-foreground" />
          <p className="text-sm font-medium">Build a repeatable test set</p>
          <p className="text-xs leading-5 text-muted-foreground">Add questions your application needs to answer. Include expected text or a source to check automatically.</p>
        </div> : <ol className="divide-y">{suite.cases.map((item, index) => <li key={item.id} className="space-y-3 p-4">
          <div className="flex items-center justify-between"><span className="text-xs font-medium">Question {index + 1}</span><Button variant="ghost" size="icon" className="size-8" aria-label={`Remove question ${index + 1}`} onClick={() => update({ ...suite, cases: suite.cases.filter(c => c.id !== item.id) })}><TrashIcon className="size-3.5" /></Button></div>
          <label className="block space-y-1.5 text-xs">Question<Textarea value={item.question} maxLength={4000} onChange={event => edit(item.id, { question: event.target.value })} placeholder="What should your application ask?" className="min-h-16 text-base md:text-sm" /></label>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="block space-y-1.5 text-xs">Expected answer text (optional)<Textarea value={item.expected} maxLength={4000} onChange={event => edit(item.id, { expected: event.target.value })} placeholder="Text the answer should include" className="min-h-16 text-base md:text-sm" /></label>
            <div className="space-y-3">
              <FilterSelect label={`Question ${index + 1} text check`} value={item.match} onChange={value => edit(item.id, { match: value as EvaluationCase["match"] })} options={[{ value: "contains", label: "Contains expected text" }, { value: "exact", label: "Exact text match" }]} />
              <label className="block space-y-1.5 text-xs">Expected source filename (optional)<Input value={item.source} maxLength={500} onChange={event => edit(item.id, { source: event.target.value })} placeholder="handbook.pdf" className="text-base md:text-sm" /></label>
            </div>
          </div>
        </li>)}</ol>}
      </section>
    </fieldset>
    <p className="text-xs leading-5 text-muted-foreground">{saveMessage} Text checks ignore case and extra whitespace. A source check matches a returned filename. These checks measure your rules; review answers for factual correctness.</p>
    {run && <section aria-label="Evaluation results" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold"><span role="status">{running ? "Running" : run.results.length < runTotal || run.results.some(r => r.status === "cancelled") ? "Run stopped" : "Run complete"} · {run.results.length}/{runTotal}</span></h3>
        <Button variant="outline" size="sm" disabled={running} onClick={() => download("evaluation-results.json", { project_id: project.id, ...run })}><DownloadSimpleIcon />Export results</Button>
      </div>
      <p className="text-xs text-muted-foreground">Run started {new Date(run.startedAt).toLocaleString()}. Results use the test set captured at run time.</p>
      <div className={cn("grid gap-3", run.suite.compare && "sm:grid-cols-2")}>
        {(run.suite.compare ? [0, 1] : [0]).map(variant => {
          const results = run.results.filter(r => r.variant === variant)
          const checked = results.filter(r => r.status === "passed" || r.status === "failed")
          const measured = results.flatMap(r => r.response?.latency_ms != null ? [r.response.latency_ms] : [])
          return <div key={variant} className="rounded-xl border p-3 text-xs leading-6">
            <p className="font-medium">{variant === 0 ? "A · Baseline" : "B · Comparison"} · top_k {run.suite.topK[variant]}</p>
            <p>{results.filter(r => r.status === "passed").length}/{checked.length} checked passed · {results.filter(r => r.status === "review").length} to review · {results.filter(r => r.status === "error").length} errors</p>
            <p className="text-muted-foreground">Mean latency {measured.length ? queryLatency(Math.round(measured.reduce((a, b) => a + b, 0) / measured.length)) : "Not measured"} · {results.filter(r => r.response?.cache_layer).length} cached</p>
          </div>
        })}
      </div>
      {run.suite.cases.map((item, index) => <article key={item.id} className="overflow-hidden rounded-xl border">
        <div className="space-y-1 border-b bg-muted/20 p-4"><h4 className="break-words text-sm font-medium">{index + 1}. {item.question}</h4>{item.expected && <p className="break-words text-xs text-muted-foreground">Expected ({item.match}): {item.expected}</p>}{item.source && <p className="break-words text-xs text-muted-foreground">Source: {item.source}</p>}</div>
        <div className={cn("grid", run.suite.compare && "md:grid-cols-2")}>
          {(run.suite.compare ? [0, 1] : [0]).map(variant => {
            const result = run.results.find(r => r.caseId === item.id && r.variant === variant)
            return <div key={variant} className={cn("min-w-0 space-y-3 p-4", variant === 1 && "border-t md:border-t-0 md:border-l")}>
              <div className="flex items-center justify-between gap-2 text-xs"><span className="font-medium">{variant === 0 ? "A" : "B"} · top_k {run.suite.topK[variant]}</span><span className={cn("rounded-full bg-muted px-2 py-1 capitalize", result?.status === "passed" && "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400", (result?.status === "failed" || result?.status === "error") && "bg-red-500/10 text-red-600 dark:text-red-400")}>{result?.status ?? (run.finished ? "Not run" : run.results.length === index * (run.suite.compare ? 2 : 1) + variant ? "Running" : "Pending")}</span></div>
              {result?.error && <p className="break-words text-sm text-destructive">{result.error}</p>}
              {result?.response && <>
                <p className="break-words text-xs text-muted-foreground">{queryLatency(result.response.latency_ms)} · {queryCacheLabel(result.response.cache_layer ?? null)} · {result.response.model}</p>
                {result.response.needs_clarification && <p className="text-xs text-amber-600 dark:text-amber-400">The answer requests clarification.</p>}
                <div className="max-h-80 overflow-y-auto break-words text-sm"><AnswerMarkdown>{result.response.answer}</AnswerMarkdown></div>
                <details className="text-xs"><summary className="cursor-pointer">Sources ({result.response.sources.length})</summary><ul className="mt-2 space-y-2">{result.response.sources.map((source, i) => <li key={i} className="rounded-lg border p-2"><p className="break-words font-medium">{source.filename}{source.page_number != null ? ` · p.${source.page_number}` : ""}{source.cited ? " · Cited" : ""}</p><p className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap break-words leading-5 text-muted-foreground">{source.content}</p></li>)}</ul></details>
                {result.response.query_id && <AnswerFeedback key={result.response.query_id} queryId={result.response.query_id} />}
              </>}
            </div>
          })}
        </div>
      </article>)}
    </section>}
  </div>
}
