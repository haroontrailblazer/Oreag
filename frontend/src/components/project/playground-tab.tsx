"use client"

import { ArrowUp, Plus, Square } from "@phosphor-icons/react/dist/ssr"
import { useRef, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { api, fetcher } from "@/lib/api"
import { providerUsable } from "@/lib/models"
import type { ModelsResponse, Project, QueryResponse } from "@/lib/types"

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

export function PlaygroundTab({ project }: { project: Project }) {
  const [question, setQuestion] = useState("")
  const [result, setResult] = useState<QueryResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [model, setModel] = useState(`${project.llm_provider}/${project.llm_model}`)
  const abortRef = useRef<AbortController | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const { data: models } = useSWR<ModelsResponse>("/api/models", fetcher)
  const availability = models?.availability ?? { [project.llm_provider]: true }

  function handleStop() {
    abortRef.current?.abort()
    abortRef.current = null
    setLoading(false)
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
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    setResult(null)
    setQuestion("")
    try {
      const response = await api<QueryResponse>(
        `/api/projects/${project.id}/query`,
        {
          method: "POST",
          body: JSON.stringify({ question: nextQuestion }),
          signal: controller.signal,
        }
      )
      setResult(response)
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return
      toast.error(err instanceof Error ? err.message : "Query failed")
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setLoading(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Test your RAG</CardTitle>
        <CardDescription>
          Ask a question with the same pipeline your API consumers will use.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="min-h-32 rounded-2xl border bg-background p-4">
          {loading ? (
            <div className="max-w-3xl space-y-2">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Answer
              </div>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span className="inline-flex gap-1">
                  <span className="size-1.5 animate-pulse rounded-full bg-current" />
                  <span className="size-1.5 animate-pulse rounded-full bg-current [animation-delay:150ms]" />
                  <span className="size-1.5 animate-pulse rounded-full bg-current [animation-delay:300ms]" />
                </span>
                Thinking
              </div>
            </div>
          ) : result ? (
            <div className="max-w-3xl space-y-2">
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Answer
                </div>
                <div className="text-xs text-muted-foreground">
                  {result.model} / {result.latency_ms} ms
                </div>
              </div>
              <p className="whitespace-pre-wrap text-sm leading-6">
                {result.answer}
              </p>
            </div>
          ) : (
            <div className="min-h-20" />
          )}
        </div>

        {result?.sources.length ? (
          <div className="space-y-2">
            <h3 className="text-sm font-medium">References</h3>
            {result.sources.map((source, i) => (
              <details key={i} className="rounded-lg border px-3 py-2 text-sm">
                <summary className="cursor-pointer">
                  [{i + 1}] {source.filename}
                  {source.page_number != null && ` - page ${source.page_number}`}{" "}
                  <span className="text-muted-foreground">
                    ({(source.similarity * 100).toFixed(0)}% match)
                  </span>
                </summary>
                <p className="mt-2 whitespace-pre-wrap text-muted-foreground">
                  {source.content}
                </p>
              </details>
            ))}
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
            className="min-h-10 resize-none border-0 bg-transparent px-2 py-1.5 shadow-none focus-visible:ring-0 dark:bg-transparent"
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
                <Plus weight="duotone" className="size-4" />
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
                  className="h-8 max-w-44 rounded-full border-0 bg-muted px-3 shadow-none focus:ring-0"
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
                        .map((name) => (
                          <SelectItem
                            key={`${provider}/${name}`}
                            value={`${provider}/${name}`}
                          >
                            {provider} / {name}
                          </SelectItem>
                        ))
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
                <ArrowUp weight="duotone" className="size-4" />
              )}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
