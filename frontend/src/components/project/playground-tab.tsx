"use client"

import {
  ArrowUpIcon as ArrowUp,
  BrainIcon as Brain,
  CaretDownIcon as CaretDown,
  CheckIcon as Check,
  CopyIcon as Copy,
  FileTextIcon as FileText,
  LightningIcon as Lightning,
  PlusIcon as Plus,
  SquareIcon as Square,
  WarningIcon as Warning,
} from "@phosphor-icons/react/dist/ssr"
import Link from "next/link"
import { memo, useEffect, useId, useRef, useState } from "react"
import { toast } from "@/lib/toast"
import useSWR, { mutate as globalMutate } from "swr"

import { BestPractices } from "@/components/ui/best-practices"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { LoaderOne, Spin } from "@/components/ui/loader"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { AnswerMarkdown } from "@/components/project/answer-markdown"
import {
  CacheViz,
  ChipsViz,
  ConversationViz,
  PipelineViz,
  RetrievalViz,
} from "@/components/ui/best-practice-visuals"
import { api, apiStream, fetcher } from "@/lib/api"
import { providerOf, providerUsable } from "@/lib/models"
import type {
  FileRecord,
  ModelsResponse,
  Project,
  QueryResponse,
  SourceChunk,
} from "@/lib/types"
import { cn } from "@/lib/utils"
import styles from "./playground-tab.module.css"

type Turn = { question: string; result: QueryResponse }

/** One SSE frame from the /query/stream endpoint. */
type StreamEvent =
  | { type: "token"; text: string }
  | { type: "done"; response: QueryResponse }
  | { type: "error"; detail: string }

/** Small copy-to-clipboard button with a brief "copied" checkmark. */
function CopyButton({
  text,
  label = false,
  description = "Copy",
  className,
}: {
  text: string
  label?: boolean
  description?: string
  className?: string
}) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      clearTimeout(timer.current)
      timer.current = setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error("Couldn't copy. Select the text and copy it manually.")
    }
  }
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={copied ? `${description}: copied` : description}
      title={copied ? "Copied" : description}
      className={cn(
        styles.copyButton,
        className
      )}
    >
      {copied ? (
        <Check className="size-3.5 text-emerald-500" />
      ) : (
        <Copy className="size-3.5" />
      )}
      {label ? (copied ? "Copied" : "Copy") : null}
    </button>
  )
}

/** Reference chips: file icon + name; clicking one reveals the chunk text. */
function SourceChips({ sources }: { sources: SourceChunk[] }) {
  const [open, setOpen] = useState<number | null>(null)
  const passageId = useId()
  const active = open !== null ? sources[open] : null
  return (
    <div className="space-y-2 pt-1">
      <p className={styles.sourceLabel}>Sources <span>{sources.length}</span></p>
      <div className="flex flex-wrap gap-1.5">
        {sources.map((source, i) => {
          const isMemory = source.filename === "memory"
          const Icon = isMemory ? Brain : FileText
          return (
            <button
              key={i}
              type="button"
              onClick={() => setOpen(open === i ? null : i)}
              aria-expanded={open === i}
              aria-controls={open === i ? passageId : undefined}
              title={
                isMemory
                  ? "Agent memory - click to read"
                  : `${source.filename} - click to read this passage`
              }
              className={cn(
                styles.sourceChip,
                open === i && "border-foreground/40 bg-muted"
              )}
            >
              <Icon className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="min-w-0 max-w-40 truncate">
                {isMemory ? "Memory" : source.filename}
              </span>
              {source.page_number != null ? (
                <span className="text-muted-foreground">p.{source.page_number}</span>
              ) : null}
              <span className="text-[10px] tabular-nums text-muted-foreground">
                {(source.similarity * 100).toFixed(0)}%
              </span>
              {source.cited ? (
                <span
                  aria-hidden
                  title="Cited in the answer"
                  className="size-1.5 shrink-0 rounded-full bg-foreground/70"
                />
              ) : null}
            </button>
          )
        })}
      </div>
      {active ? (
        <div id={passageId} className={styles.passage} role="region" aria-label="Source passage">
          <div className="mb-1.5 flex items-center justify-between gap-2 text-xs">
            <span className="flex min-w-0 items-center gap-1.5 font-medium">
              {active.filename === "memory" ? (
                <Brain className="size-3.5 shrink-0" />
              ) : (
                <FileText className="size-3.5 shrink-0" />
              )}
              <span className="truncate">
                {active.filename === "memory" ? "Agent memory" : active.filename}
                {active.page_number != null && ` · page ${active.page_number}`}
              </span>
            </span>
            <span className="shrink-0 text-muted-foreground">
              {active.cited ? "Cited · " : ""}
              {(active.similarity * 100).toFixed(0)}% match
            </span>
          </div>
          <p tabIndex={0} aria-label="Source text" className="max-h-48 overflow-y-auto break-words whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
            {active.content}
          </p>
        </div>
      ) : null}
    </div>
  )
}

/** Badge showing which cache layer answered (exact, semantic, or nothing). */
function CacheBadge({ result }: { result: QueryResponse }) {
  if (!result.cache_layer) return null
  const label =
    result.cache_layer === "l1"
      ? "Cached · exact"
      : `Cached · similar${
          result.cache_similarity != null
            ? ` ${(result.cache_similarity * 100).toFixed(0)}%`
            : ""
        }`
  return (
    <span
      title={
        result.cache_layer === "l1"
          ? "Served from the exact-match cache (L1) - no retrieval, no LLM call"
          : "A semantically similar question was answered before (L2) - reused at the cost of one embedding call"
      }
      className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-emerald-600 dark:text-emerald-400"
    >
      {label}
    </span>
  )
}

/** One question + its grounded answer (depth badge, search plan, references). */
const TurnView = memo(function TurnView({ question, result }: Turn) {
  return (
    <div className={styles.turn}>
      {/* Question, right-aligned, with a copy button that appears on hover. */}
      <div className="group flex items-start justify-end gap-1">
        <CopyButton
          text={question}
          description="Copy question"
          className="mt-0.5"
        />
        <div className={styles.question}>
          {question}
        </div>
      </div>
      <div className={styles.answer}>
        <div className={styles.answerHeader}>
          <div className="flex flex-wrap items-center gap-2">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {result.needs_clarification ? "Needs a bit more detail" : "Answer"}
            </div>
            {result.depth === "long" && !result.needs_clarification ? (
              <span className="rounded-full bg-sky-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-sky-600 dark:text-sky-400">
                Detailed
              </span>
            ) : null}
            <CacheBadge result={result} />
          </div>
          <div className={styles.answerMeta}>
            {result.model} / {result.latency_ms} ms
          </div>
        </div>
        {result.needs_clarification ? (
          <p className="break-words whitespace-pre-wrap text-sm leading-6">
            {result.answer}
          </p>
        ) : (
          <AnswerMarkdown>{result.answer}</AnswerMarkdown>
        )}
        {result.sub_queries && result.sub_queries.length > 1 ? (
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">
              Search plan ({result.sub_queries.length} sub-queries)
            </summary>
            <ul className="mt-1.5 ml-1 space-y-1">
              {result.sub_queries.map((sub, i) => (
                <li key={i} className="break-words">
                  {i + 1}. {sub}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
        {result.sources.length ? <SourceChips sources={result.sources} /> : null}
        {!result.needs_clarification && result.answer ? (
          <div className="flex items-center pt-0.5">
            <CopyButton
              text={result.answer}
              description="Copy answer"
              label
              className="opacity-70 transition-opacity group-hover:opacity-100"
            />
          </div>
        ) : null}
      </div>
    </div>
  )
})

export function PlaygroundTab({ project }: { project: Project }) {
  const [question, setQuestion] = useState("")
  const [turns, setTurns] = useState<Turn[]>([])
  // The in-flight answer as it streams in. `text` grows token by token; it
  // becomes a finished Turn (with sources/cache) once the "done" event lands.
  const [streaming, setStreaming] = useState<{
    question: string
    text: string
  } | null>(null)
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [model, setModel] = useState(`${project.llm_provider}/${project.llm_model}`)
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null) // the scrollable conversation
  const questionInput = useRef<HTMLTextAreaElement>(null)
  const cacheDetails = useRef<HTMLDetailsElement>(null)
  const streamTopRef = useRef<HTMLDivElement>(null) // top of the newest turn
  // Shown when there's more conversation below the fold - lets the user jump to
  // the latest instead of the view auto-yanking to the end of a long answer.
  const [showScrollDown, setShowScrollDown] = useState(false)
  // A conversation id ties follow-ups together so "summarize that" works. Lazily
  // created on the first ask (client only) to avoid an SSR hydration mismatch.
  const conversationId = useRef<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      const details = cacheDetails.current
      if (details?.open && !details.contains(event.target as Node)) details.open = false
    }
    const escape = (event: KeyboardEvent) => {
      const details = cacheDetails.current
      if (event.key === "Escape" && details?.open) {
        details.open = false
        details.querySelector("summary")?.focus()
      }
    }
    document.addEventListener("pointerdown", dismiss)
    document.addEventListener("keydown", escape)
    return () => {
      document.removeEventListener("pointerdown", dismiss)
      document.removeEventListener("keydown", escape)
    }
  }, [])
  const { data: models } = useSWR<ModelsResponse>("/api/models", fetcher)
  const availability = models?.availability ?? { [project.llm_provider]: true }
  // Project-wide cache performance (playground + /v1 API), not this session -
  // sourced from query_logs and revalidated after each ask.
  const { data: cacheStats, mutate: mutateStats } = useSWR<{
    queries: number
    cache_hits: number
    l1: number
    l2: number
    hit_rate: number
  }>(`/api/projects/${project.id}/query-stats`, fetcher)

  function refreshScrollDown() {
    const el = scrollRef.current
    if (!el) return
    setShowScrollDown(el.scrollHeight - el.scrollTop - el.clientHeight > 120)
  }

  // On a NEW question, bring it to the top of the view so the answer streams in
  // below it - the user reads from the start and scrolls down, rather than the
  // view chasing the last token. `streaming.question` only changes per ask.
  useEffect(() => {
    if (!streaming) return
    const raf = requestAnimationFrame(() => {
      const container = scrollRef.current
      const turn = streamTopRef.current
      if (!container || !turn) return
      container.scrollTo({
        top: container.scrollTop + turn.getBoundingClientRect().top - container.getBoundingClientRect().top - 16,
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
      })
    })
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streaming?.question])

  // As content grows (streaming tokens, finished turns), recompute whether the
  // "scroll to latest" affordance is needed - without moving the viewport.
  useEffect(() => {
    const raf = requestAnimationFrame(refreshScrollDown)
    return () => cancelAnimationFrame(raf)
  }, [streaming?.text, turns.length])

  function scrollToLatest() {
    const container = scrollRef.current
    container?.scrollTo({
      top: container.scrollHeight,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
    })
  }
  // The selected model's provider may have lost its key since it was chosen -
  // flag it (grey trigger + warning) instead of silently letting a query 503.
  const currentModelUsable = providerUsable(
    providerOf(model),
    "llm",
    availability,
    project
  )
  // Which providers still have a usable key, and the first model to switch to.
  // Lets the "key removed" notice tell the user exactly what IS available and
  // offer a one-click switch, instead of a dead-end error.
  const availableLlmProviders = models
    ? Object.keys(models.catalog.llm).filter((p) =>
        providerUsable(p, "llm", availability, project)
      )
    : []
  const firstAvailableModel = models
    ? Object.entries(models.catalog.llm).flatMap(([provider, names]) =>
        providerUsable(provider, "llm", availability, project)
          ? names.map((n) => `${provider}/${n}`)
          : []
      )[0] ?? null
    : null

  function handleStop() {
    abortRef.current?.abort()
    abortRef.current = null
    setLoading(false)
    setStreaming(null)
  }

  function handleNewChat() {
    conversationId.current = null
    setTurns([])
    setStreaming(null)
    questionInput.current?.focus({ preventScroll: true })
  }

  async function handleUpload(list: FileList | null) {
    if (!list || list.length === 0) return
    // No extension whitelist: the backend ingests any file it can extract
    // text from and rejects only opaque binary with a per-file error.
    const form = new FormData()
    for (const file of Array.from(list)) {
      form.append("uploads", file)
    }
    setUploading(true)
    try {
      const created = await api<FileRecord[]>(`/api/projects/${project.id}/files`, {
        method: "POST",
        body: form,
      })
      // Never toasted unconditionally: with version tracking on, an upload
      // that looks like a new edition is HELD rather than indexed, and this is
      // one of the two upload paths outside the Files tab - so "indexing
      // started" would be the only thing the user is told, and it would be
      // wrong.
      const parked = created.filter((f) => f.status === "review").length
      toast.success(
        parked
          ? `${parked} file${parked === 1 ? "" : "s"} need a version confirmed`
          : "Upload complete. Indexing started.",
        parked
          ? { description: "Confirm what they replace in the Files tab." }
          : undefined
      )
      // Nothing here used to be revalidated at all, so a file uploaded from the
      // Playground never appeared in the Files tab or the sidebar - not while
      // indexing, not after it finished - until a full page reload. Seeding the
      // files key with the server's response also arms that tab's poll, which
      // only starts once its cached list contains a pending row.
      globalMutate(`/api/projects/${project.id}/files`, created, {
        revalidate: false,
      })
      globalMutate(`/api/projects/${project.id}`)
      globalMutate("/api/projects")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Upload failed")
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ""
    }
  }

  async function handleModelChange(value: string) {
    const previous = model
    const [llmProvider, llmModel] = value.split("/", 2)
    setModel(value)
    try {
      await api(`/api/projects/${project.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          llm_provider: llmProvider,
          llm_model: llmModel,
        }),
      })
      toast.success("Playground model updated")
      // This PATCH changes the model for the whole PROJECT, not just this tab.
      // Without revalidating, the Settings tab keeps rendering the old value -
      // and pressing Save there then writes that stale value back, silently
      // undoing the change just made here.
      globalMutate(`/api/projects/${project.id}`)
      globalMutate("/api/projects")
    } catch (err) {
      setModel(previous)
      toast.error(err instanceof Error ? err.message : "Model update failed")
    }
  }

  async function handleAsk() {
    const nextQuestion = question.trim()
    if (!nextQuestion || loading) return
    // The selected model's key was removed - don't fire a request that would
    // 503. If another provider still has a key, switch to it automatically and
    // continue; otherwise guide the user to add a key. Never a raw error.
    if (!currentModelUsable) {
      if (firstAvailableModel) {
        handleModelChange(firstAvailableModel)
        toast.info(
          `Switched to ${firstAvailableModel.split("/")[1]} - the key for ${providerOf(model)} was removed.`
        )
      } else {
        toast.info(
          `No usable answer model - add a provider key in Settings to continue.`
        )
      }
      return
    }
    if (!conversationId.current) conversationId.current = crypto.randomUUID()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    setStreaming({ question: nextQuestion, text: "" })
    setQuestion("")

    let final: QueryResponse | null = null
    let streamError: string | null = null
    try {
      await apiStream(
        `/api/projects/${project.id}/query/stream`,
        {
          question: nextQuestion,
          conversation_id: conversationId.current,
        },
        {
          signal: controller.signal,
          onEvent: (event) => {
            const ev = event as StreamEvent
            if (ev.type === "token") {
              setStreaming((s) =>
                s ? { ...s, text: s.text + ev.text } : s
              )
            } else if (ev.type === "done") {
              final = ev.response
            } else if (ev.type === "error") {
              streamError = ev.detail
            }
          },
        }
      )
      if (streamError) {
        toast.error(streamError)
      } else if (final) {
        setTurns((prev) => [
          ...prev,
          { question: nextQuestion, result: final as QueryResponse },
        ])
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return
      toast.error(err instanceof Error ? err.message : "Query failed")
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setLoading(false)
      setStreaming(null)
      // The query was logged server-side; refresh the project-wide hit rate.
      mutateStats()
    }
  }

  return (
    // Fixed frame: header (title) and the input row stay put; only the
    // conversation in the middle scrolls - the same on mobile and desktop.
    // Tighter padding + hidden description on mobile give the answers more room.
    <Card className={styles.page} data-empty={turns.length === 0 && !loading}>
      <CardHeader className="shrink-0">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1 space-y-1.5">
            <CardTitle className={styles.title}>Conversation</CardTitle>
            <div className={styles.sessionStatus} role="status" data-busy={loading}>
              <span aria-hidden="true" />{loading ? "Answering" : currentModelUsable ? "Ready to chat" : "Model unavailable"}
            </div>
          </div>
          <div className="ml-auto flex shrink-0 items-center gap-2">
        {cacheStats && cacheStats.queries > 0 ? (
          <details
            ref={cacheDetails}
            className={styles.cacheStats}
            title="Project-wide cache performance across the playground and the /v1 API. Cached answers skip retrieval and the LLM."
          >
            <summary>
            <Lightning
              className={cn(
                "size-3.5",
                cacheStats.cache_hits > 0 && "text-emerald-500"
              )}
              weight={cacheStats.cache_hits > 0 ? "fill" : "regular"}
            />
            Project cache <strong>{Math.round(cacheStats.hit_rate * 100)}% hit rate</strong><CaretDown aria-hidden="true" className="size-3" />
            </summary>
            <p>{cacheStats.cache_hits}/{cacheStats.queries} queries cached · {cacheStats.l1} exact, {cacheStats.l2} similar. Includes Playground and API requests.</p>
          </details>
        ) : null}


            <BestPractices
              tips={[
                {
                  visual: <ConversationViz />,
                  title: "Follow-ups keep context",
                  detail:
                    'Asking "summarize that" works - the server rewrites follow-ups into standalone questions using the conversation. Use New chat to reset context.',
                },
                {
                  visual: <CacheViz />,
                  title: "Watch the cache badges",
                  detail:
                    "Cached - exact means the same question was asked before (L1). Cached - similar means a semantically close question was answered (L2, similarity shown). Fresh answers have no badge and cost retrieval + an LLM call.",
                },
                {
                  visual: <ChipsViz />,
                  title: "Click the reference chips",
                  detail:
                    "Each chip is a chunk that grounded the answer - click to read the exact passage and its match score. Memory chips (brain icon) are agent memories blended in.",
                },
                {
                  visual: <RetrievalViz />,
                  title: "Exact terms are caught too",
                  detail:
                    "Retrieval is hybrid: meaning-based vector search plus full-text keyword search, so error codes and IDs match even when embeddings miss them.",
                },
                {
                  visual: <PipelineViz />,
                  title: "This is exactly the /v1 pipeline",
                  detail:
                    "The playground calls the same code path as your public API and MCP tools - what you see here is what your consumers get.",
                },
              ]}
            />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleNewChat}
                disabled={loading || turns.length === 0}
                aria-label="New chat"
                title="New chat"
                className="gap-1.5"
              >
                <Plus className="size-4" />
                <span className="hidden sm:inline">New chat</span>
              </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className={styles.content}>
        <div className={styles.conversationArea}>
          <div
            ref={scrollRef}
            onScroll={refreshScrollDown}
            className={styles.conversation}
            role="region"
            aria-label="Conversation"
            tabIndex={0}
          >
            {turns.length === 0 && !loading ? (
              <div className={styles.empty}>
                <h2>What would you like to know?</h2>
                <p>Ask a question about your documents and memories.</p>
              </div>
            ) : null}
            {turns.map((turn, i) => (
              <TurnView key={i} question={turn.question} result={turn.result} />
            ))}
            {streaming ? (
              <div ref={streamTopRef} className="space-y-2 scroll-mt-4">
                <div className="flex justify-end">
                  <div className={styles.question}>
                    {streaming.question}
                  </div>
                </div>
                {streaming.text ? (
                  // Answer grows in place; the caret marks the live cursor.
                  <div className={styles.answer}>
                    <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Answer
                    </div>
                    <div className="playground-streaming">
                      <AnswerMarkdown>{streaming.text}</AnswerMarkdown>
                    </div>
                  </div>
                ) : (
                  <div className={styles.thinking} role="status">
                    <LoaderOne />
                    Thinking
                  </div>
                )}
              </div>
            ) : null}
          </div>
          {showScrollDown && (turns.length > 0 || streaming) ? (
            <button
              type="button"
              onClick={scrollToLatest}
              aria-label="Scroll to latest"
              title="Scroll to latest"
              className={styles.scrollButton}
            >
              <CaretDown className="size-4" />
            </button>
          ) : null}
        </div>

        {/* Static footer: cache rate, any key warning, and the input row. */}
        <div className={styles.footer}>
        {!currentModelUsable ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2.5 text-xs text-amber-900 dark:border-amber-800/50 dark:bg-amber-950/40 dark:text-amber-200">
            <Warning className="size-4 shrink-0" weight="fill" />
            <span className="min-w-0 flex-1">
              The API key for <strong>{providerOf(model)}</strong> was removed,
              so this model can no longer answer.
              {firstAvailableModel
                ? ` You still have a key for ${availableLlmProviders.join(", ")}.`
                : " Add a provider key to keep answering."}
            </span>
            {firstAvailableModel ? (
              <Button
                size="sm"
                variant="outline"
                className="h-7 shrink-0 border-amber-400/60 bg-transparent"
                onClick={() => handleModelChange(firstAvailableModel)}
              >
                Switch to {firstAvailableModel.split("/")[1]}
              </Button>
            ) : (
              <Button
                asChild
                size="sm"
                variant="outline"
                className="h-7 shrink-0 border-amber-400/60 bg-transparent"
              >
                <Link href="/settings/api-keys">Add a key</Link>
              </Button>
            )}
          </div>
        ) : null}

        <div className={styles.composer}>
          <Textarea
            ref={questionInput}
            aria-label="Your question"
            rows={1}
            placeholder="Ask about your knowledge base…"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                if (loading) {
                  handleStop()
                } else {
                  handleAsk()
                }
              }
            }}
            className="styled-scrollbar max-h-32 min-h-10 resize-none overflow-y-auto border-0 bg-transparent px-2 py-1.5 shadow-none focus-visible:ring-0 dark:bg-transparent"
          />
          <div className={styles.composerControls}>
            <div className={styles.modelControls}>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className={styles.attachButton}
                title="Add files"
                aria-label="Add files"
                disabled={uploading}
                onClick={() => fileInput.current?.click()}
              >
                {uploading ? <Spin /> : <Plus className="size-4" />}
              </Button>
              <input
                ref={fileInput}
                type="file"
                multiple
                hidden
                onChange={(event) => handleUpload(event.target.files)}
              />
              <Select value={model} onValueChange={handleModelChange} disabled={loading}>
                <SelectTrigger
                  size="sm"
                  aria-label="Answer model"
                  title="Changes the answer model for this project"
                  className={cn(
                    styles.modelSelect,
                    !currentModelUsable && "text-muted-foreground"
                  )}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {models ? (
                    Object.entries(models.catalog.llm).flatMap(([provider, names]) =>
                      names
                        .filter(
                          (name) =>
                            providerUsable(provider, "llm", availability, project) ||
                            `${provider}/${name}` === model
                        )
                        .map((name) => {
                          const value = `${provider}/${name}`
                          const usable = providerUsable(
                            provider,
                            "llm",
                            availability,
                            project
                          )
                          return (
                            <SelectItem
                              key={value}
                              value={value}
                              className={cn(
                                !usable && "text-muted-foreground opacity-70"
                              )}
                            >
                              {provider} / {name}
                              {!usable ? " · key removed" : ""}
                            </SelectItem>
                          )
                        })
                    )
                  ) : (
                    <SelectItem value={model}>{model}</SelectItem>
                  )}
                </SelectContent>
              </Select>
            </div>
            <Button
              size="icon"
              className={styles.sendButton}
              data-stopping={loading}
              onClick={loading ? handleStop : handleAsk}
              disabled={!loading && !question.trim()}
              aria-label={loading ? "Stop" : "Ask"}
              title={loading ? "Stop generating" : "Send question"}
            >
              {loading ? (
                <Square className="size-3 fill-current" />
              ) : (
                <ArrowUp className="size-4" />
              )}
            </Button>
          </div>
        </div>
        </div>
      </CardContent>
    </Card>
  )
}
