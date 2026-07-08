"use client"

import {
  ArrowUp,
  Brain,
  CaretDown,
  Check,
  Copy,
  FileText,
  Lightning,
  Plus,
  Square,
  Warning,
} from "@phosphor-icons/react/dist/ssr"
import Link from "next/link"
import { useEffect, useRef, useState } from "react"
import { toast } from "@/lib/toast"
import useSWR from "swr"

import { BestPractices } from "@/components/ui/best-practices"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { LoaderOne } from "@/components/ui/loader"
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
  ModelsResponse,
  Project,
  QueryResponse,
  SourceChunk,
} from "@/lib/types"
import { cn } from "@/lib/utils"

const ACCEPTED_FILE_TYPES = [
  ".pdf",
  ".docx",
  ".pptx",
  ".xlsx",
  ".xls",
  ".html",
  ".htm",
  ".csv",
  ".json",
  ".xml",
  ".txt",
  ".md",
  ".rtf",
  ".odt",
  ".ods",
  ".odp",
  ".epub",
  ".eml",
  ".jpg",
  ".jpeg",
  ".png",
  ".gif",
  ".bmp",
  ".tif",
  ".tiff",
  ".wav",
  ".mp3",
  ".m4a",
  ".zip",
].join(",")

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
  className,
}: {
  text: string
  label?: boolean
  className?: string
}) {
  const [copied, setCopied] = useState(false)
  function copy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button
      type="button"
      onClick={copy}
      aria-label="Copy"
      title="Copy"
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
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
  const active = open !== null ? sources[open] : null
  return (
    <div className="space-y-2 pt-1">
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
              title={
                isMemory
                  ? "Agent memory - click to read"
                  : `${source.filename} - click to read this passage`
              }
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border bg-background px-2.5 py-1 text-xs font-medium transition-colors hover:bg-muted",
                open === i && "border-foreground/40 bg-muted"
              )}
            >
              <Icon className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="max-w-40 truncate">
                {isMemory ? "Memory" : source.filename}
              </span>
              {source.page_number != null ? (
                <span className="text-muted-foreground">p.{source.page_number}</span>
              ) : null}
              <span className="text-[10px] tabular-nums text-muted-foreground">
                {(source.similarity * 100).toFixed(0)}%
              </span>
            </button>
          )
        })}
      </div>
      {active ? (
        <div className="rounded-lg border bg-muted/40 p-3">
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
              {(active.similarity * 100).toFixed(0)}% match
            </span>
          </div>
          <p className="max-h-48 overflow-y-auto break-words whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
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
function TurnView({ question, result }: Turn) {
  return (
    <div className="space-y-2">
      {/* Question, right-aligned, with a copy button that appears on hover. */}
      <div className="group flex items-start justify-end gap-1">
        <CopyButton
          text={question}
          className="mt-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
        />
        <div className="max-w-[85%] rounded-2xl bg-muted px-3 py-1.5 text-sm break-words">
          {question}
        </div>
      </div>
      <div className="group max-w-3xl space-y-2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
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
          <div className="text-xs text-muted-foreground">
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
              label
              className="opacity-70 transition-opacity group-hover:opacity-100"
            />
          </div>
        ) : null}
      </div>
    </div>
  )
}

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
  const bottomRef = useRef<HTMLDivElement>(null) // sentinel at the very bottom
  const streamTopRef = useRef<HTMLDivElement>(null) // top of the newest turn
  // Shown when there's more conversation below the fold - lets the user jump to
  // the latest instead of the view auto-yanking to the end of a long answer.
  const [showScrollDown, setShowScrollDown] = useState(false)
  // A conversation id ties follow-ups together so "summarize that" works. Lazily
  // created on the first ask (client only) to avoid an SSR hydration mismatch.
  const conversationId = useRef<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
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
    const raf = requestAnimationFrame(() =>
      streamTopRef.current?.scrollIntoView({ block: "start", behavior: "smooth" })
    )
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
    bottomRef.current?.scrollIntoView({ block: "end", behavior: "smooth" })
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
  }

  async function handleUpload(list: FileList | null) {
    if (!list || list.length === 0) return
    const form = new FormData()
    for (const file of Array.from(list)) {
      const extension = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`
      if (!ACCEPTED_FILE_TYPES.split(",").includes(extension)) {
        toast.error(`${file.name}: unsupported file type`)
        return
      }
      form.append("uploads", file)
    }
    setUploading(true)
    try {
      await api(`/api/projects/${project.id}/files`, {
        method: "POST",
        body: form,
      })
      toast.success("Upload complete. Indexing started.")
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
    <Card className="flex h-full min-h-0 flex-col gap-3 py-3 sm:gap-6 sm:py-6">
      <CardHeader className="shrink-0">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1.5">
            <CardTitle>Test your RAG</CardTitle>
            <CardDescription className="hidden sm:block">
              Ask a question with the same pipeline your API consumers will use.
              Follow-ups remember the conversation.
            </CardDescription>
          </div>
          <div className="flex shrink-0 items-center gap-2">
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
            {turns.length > 0 ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleNewChat}
                aria-label="New chat"
                title="New chat"
                className="gap-1.5"
              >
                <Plus className="size-4" />
                <span className="hidden sm:inline">New chat</span>
              </Button>
            ) : null}
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col gap-3 pb-4">
        <div className="relative min-h-0 flex-1">
          <div
            ref={scrollRef}
            onScroll={refreshScrollDown}
            className="h-full space-y-5 overflow-y-auto rounded-2xl border bg-background px-4 py-4 sm:px-6"
          >
            {turns.length === 0 && !loading ? (
              <div className="flex min-h-20 items-center justify-center text-center text-sm text-muted-foreground">
                Ask a question to test retrieval, the agentic loop, and grounded
                answers. Follow-ups like “summarize that” keep context.
              </div>
            ) : null}
            {turns.map((turn, i) => (
              <TurnView key={i} question={turn.question} result={turn.result} />
            ))}
            {streaming ? (
              <div ref={streamTopRef} className="space-y-2 scroll-mt-4">
                <div className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl bg-muted px-3 py-1.5 text-sm break-words">
                    {streaming.question}
                  </div>
                </div>
                {streaming.text ? (
                  // Answer grows in place; the caret marks the live cursor.
                  <div className="max-w-3xl">
                    <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Answer
                    </div>
                    <div className="playground-streaming">
                      <AnswerMarkdown>{streaming.text}</AnswerMarkdown>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <LoaderOne />
                    Thinking
                  </div>
                )}
              </div>
            ) : null}
            <div ref={bottomRef} />
          </div>
          {showScrollDown ? (
            <button
              type="button"
              onClick={scrollToLatest}
              aria-label="Scroll to latest"
              title="Scroll to latest"
              className="absolute bottom-3 left-1/2 z-10 flex size-8 -translate-x-1/2 items-center justify-center rounded-full border bg-background/90 text-muted-foreground shadow-md backdrop-blur transition-colors hover:text-foreground"
            >
              <CaretDown className="size-4" />
            </button>
          ) : null}
        </div>

        {/* Static footer: cache rate, any key warning, and the input row. */}
        <div className="shrink-0 space-y-3">
        {cacheStats && cacheStats.queries > 0 ? (
          <div
            className="flex items-center justify-end gap-1.5 text-xs text-muted-foreground"
            title="Project-wide cache performance across the playground and the /v1 API. Cached answers skip retrieval and the LLM."
          >
            <Lightning
              className={cn(
                "size-3.5",
                cacheStats.cache_hits > 0 && "text-emerald-500"
              )}
              weight={cacheStats.cache_hits > 0 ? "fill" : "regular"}
            />
            Cache hit rate {Math.round(cacheStats.hit_rate * 100)}% (
            {cacheStats.cache_hits}/{cacheStats.queries} queries · {cacheStats.l1}{" "}
            exact, {cacheStats.l2} similar)
          </div>
        ) : null}

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

        <div className="rounded-xl border bg-background p-1.5 shadow-xs focus-within:border-foreground">
          <Textarea
            rows={1}
            placeholder="Ask anything about this knowledge base"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
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
          <div className="flex items-center justify-between gap-2 px-1 pt-1">
            <div className="flex min-w-0 items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className="shrink-0 rounded-full"
                title="Add files"
                aria-label="Add files"
                disabled={uploading}
                onClick={() => fileInput.current?.click()}
              >
                <Plus className="size-4" />
              </Button>
              <input
                ref={fileInput}
                type="file"
                accept={ACCEPTED_FILE_TYPES}
                multiple
                hidden
                onChange={(event) => handleUpload(event.target.files)}
              />
              <Select value={model} onValueChange={handleModelChange}>
                <SelectTrigger
                  size="sm"
                  aria-label="Answer model"
                  className={cn(
                    "h-8 max-w-44 rounded-full border-0 bg-muted px-3 shadow-none focus:ring-0",
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
              className="size-8 shrink-0 rounded-full"
              onClick={loading ? handleStop : handleAsk}
              disabled={!loading && !question.trim()}
              aria-label={loading ? "Stop" : "Ask"}
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
