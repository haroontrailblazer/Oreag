"use client"

import { FileArrowUp as FileUp, X } from "@phosphor-icons/react/dist/ssr"
import Link from "next/link"
import { useRouter } from "next/navigation"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { api, fetcher } from "@/lib/api"
import { providerOf } from "@/lib/models"
import type { ModelsResponse, Project } from "@/lib/types"

const MAX_FILE_MB = 50
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

function firstAvailableModel<T>(
  groups: Record<string, T[]>,
  availability: Record<string, boolean>,
  toValue: (provider: string, entry: T) => string
): string | null {
  for (const [provider, entries] of Object.entries(groups)) {
    if (availability[provider] && entries.length > 0) {
      return toValue(provider, entries[0])
    }
  }
  return null
}

export default function NewProjectPage() {
  const router = useRouter()
  const fileInput = useRef<HTMLInputElement>(null)

  const [step, setStep] = useState<1 | 2>(1)
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [files, setFiles] = useState<File[]>([])
  const [chunkSize, setChunkSize] = useState(1000)
  const [chunkOverlap, setChunkOverlap] = useState(200)
  const [embedding, setEmbedding] = useState("openai/text-embedding-3-small")
  const [llm, setLlm] = useState("openai/gpt-4o-mini")
  const [topK, setTopK] = useState(5)
  const [submitting, setSubmitting] = useState(false)

  const { data: models } = useSWR<ModelsResponse>("/api/models", fetcher, {
    onSuccess({ availability, catalog }) {
      setEmbedding((current) => {
        const [provider] = current.split("/", 1)
        if (availability[provider]) return current
        return (
          firstAvailableModel(catalog.embedding, availability, (p, e) => `${p}/${e.model}`) ??
          current
        )
      })
      setLlm((current) => {
        const [provider] = current.split("/", 1)
        if (availability[provider]) return current
        return firstAvailableModel(catalog.llm, availability, (p, m) => `${p}/${m}`) ?? current
      })
    },
  })

  // Project names are unique per account — flag duplicates live.
  const { data: projects } = useSWR<Project[]>("/api/projects", fetcher)
  const trimmedName = name.trim()
  const nameTaken =
    trimmedName.length > 0 &&
    (projects ?? []).some(
      (p) => p.name.trim().toLowerCase() === trimmedName.toLowerCase()
    )

  function addFiles(list: FileList | null) {
    if (!list) return
    const next = [...files]
    for (const file of Array.from(list)) {
      const extension = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`
      if (!ACCEPTED_FILE_TYPES.split(",").includes(extension)) {
        toast.error(`${file.name}: unsupported file type`)
        continue
      }
      if (file.size > MAX_FILE_MB * 1024 * 1024) {
        toast.error(`${file.name}: exceeds the ${MAX_FILE_MB} MB limit`)
        continue
      }
      if (!next.some((f) => f.name === file.name && f.size === file.size)) {
        next.push(file)
      }
    }
    setFiles(next)
  }

  async function handleCreate() {
    const [embeddingProvider, embeddingModel] = embedding.split("/", 2)
    const [llmProvider, llmModel] = llm.split("/", 2)
    setSubmitting(true)
    try {
      const project = await api<Project>("/api/projects", {
        method: "POST",
        body: JSON.stringify({
          name,
          description: description || null,
          chunk_size: chunkSize,
          chunk_overlap: chunkOverlap,
          embedding_provider: embeddingProvider,
          embedding_model: embeddingModel,
          llm_provider: llmProvider,
          llm_model: llmModel,
          top_k: topK,
        }),
      })
      if (files.length > 0) {
        const form = new FormData()
        files.forEach((file) => form.append("uploads", file))
        await api(`/api/projects/${project.id}/files`, {
          method: "POST",
          body: form,
        })
      }
      toast.success("Project created — indexing started")
      router.push(`/projects/${project.id}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create project")
      setSubmitting(false)
    }
  }

  const availability = models?.availability ?? { openai: true }
  const embAvailable = Boolean(availability[providerOf(embedding)])
  const llmAvailable = Boolean(availability[providerOf(llm)])

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold">New RAG project</h1>

      {step === 1 && (
        <Card>
          <CardHeader>
            <CardTitle>1. Name and documents</CardTitle>
            <CardDescription>
              Give the project a name and upload the files it should know about.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">Project name</Label>
              <Input
                id="name"
                placeholder="e.g. Product handbook"
                value={name}
                onChange={(e) => setName(e.target.value)}
                aria-invalid={nameTaken}
              />
              {nameTaken && (
                <p className="text-xs text-destructive">
                  A project named &ldquo;{trimmedName}&rdquo; already exists —
                  choose another name.
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="description">Description (optional)</Label>
              <Textarea
                id="description"
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>Documents</Label>
              <button
                type="button"
                onClick={() => fileInput.current?.click()}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault()
                  addFiles(e.dataTransfer.files)
                }}
                className="flex w-full flex-col items-center gap-2 rounded-lg border-2 border-dashed p-8 text-sm text-muted-foreground hover:bg-muted/40"
              >
                <FileUp className="size-6" />
                Drag and drop files here, or click to browse (max {MAX_FILE_MB}{" "}
                MB each)
              </button>
              <input
                ref={fileInput}
                type="file"
                accept={ACCEPTED_FILE_TYPES}
                multiple
                hidden
                onChange={(e) => addFiles(e.target.files)}
              />
              {files.length > 0 && (
                <ul className="space-y-1">
                  {files.map((file) => (
                    <li
                      key={file.name + file.size}
                      className="flex items-center justify-between rounded border px-3 py-1.5 text-sm"
                    >
                      <span className="truncate">{file.name}</span>
                      <button
                        type="button"
                        onClick={() =>
                          setFiles(files.filter((f) => f !== file))
                        }
                      >
                        <X className="size-4 text-muted-foreground" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => router.push("/dashboard")}>
                Cancel
              </Button>
              <Button
                onClick={() => setStep(2)}
                disabled={!name.trim() || nameTaken}
              >
                Configure
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {step === 2 && (
        <Card>
          <CardHeader>
            <CardTitle>2. RAG configuration</CardTitle>
            <CardDescription>
              Sensible defaults — tune them if you know your documents.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {models && (!embAvailable || !llmAvailable) && (
              <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-300">
                You don&apos;t have a key for a selected model yet. Add one in{" "}
                <Link href="/settings/api-keys" className="font-medium underline">
                  Settings → API keys
                </Link>{" "}
                — or run a local Ollama model — then pick a model here.
              </div>
            )}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="chunk-size">Chunk size</Label>
                <Input
                  id="chunk-size"
                  type="number"
                  min={100}
                  max={8000}
                  value={chunkSize}
                  onChange={(e) => setChunkSize(Number(e.target.value))}
                />
                <p className="text-xs text-muted-foreground">
                  Characters per chunk. Smaller = more precise retrieval,
                  larger = more context per match.
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="chunk-overlap">Chunk overlap</Label>
                <Input
                  id="chunk-overlap"
                  type="number"
                  min={0}
                  value={chunkOverlap}
                  onChange={(e) => setChunkOverlap(Number(e.target.value))}
                />
                <p className="text-xs text-muted-foreground">
                  Characters shared between neighboring chunks so sentences
                  aren&apos;t cut mid-thought.
                </p>
              </div>
            </div>

            <div className="space-y-2">
              <Label>Embedding model</Label>
              <Select value={embedding} onValueChange={setEmbedding}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {models
                    ? Object.entries(models.catalog.embedding).flatMap(
                        ([provider, entries]) =>
                          entries
                            .filter(
                              (entry) =>
                                availability[provider] ||
                                `${provider}/${entry.model}` === embedding
                            )
                            .map((entry) => (
                              <SelectItem
                                key={`${provider}/${entry.model}`}
                                value={`${provider}/${entry.model}`}
                              >
                                {provider} / {entry.model} ({entry.dimensions}d)
                              </SelectItem>
                            ))
                      )
                    : (
                      <SelectItem value="openai/text-embedding-3-small">
                        openai / text-embedding-3-small (1536d)
                      </SelectItem>
                    )}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                How your text is turned into vectors. Cannot be changed later
                without re-indexing.
              </p>
            </div>

            <div className="space-y-2">
              <Label>Answer model (LLM)</Label>
              <Select value={llm} onValueChange={setLlm}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {models
                    ? Object.entries(models.catalog.llm).flatMap(
                        ([provider, names]) =>
                          names
                            .filter(
                              (model) =>
                                availability[provider] ||
                                `${provider}/${model}` === llm
                            )
                            .map((model) => (
                              <SelectItem
                                key={`${provider}/${model}`}
                                value={`${provider}/${model}`}
                              >
                                {provider} / {model}
                              </SelectItem>
                            ))
                      )
                    : (
                      <SelectItem value="openai/gpt-4o-mini">
                        openai / gpt-4o-mini
                      </SelectItem>
                    )}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="top-k">Top-K results: {topK}</Label>
              <Input
                id="top-k"
                type="range"
                min={1}
                max={20}
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
              />
              <p className="text-xs text-muted-foreground">
                How many document chunks are retrieved per question.
              </p>
            </div>

            <div className="flex justify-between">
              <Button variant="outline" onClick={() => setStep(1)}>
                Back
              </Button>
              <Button
                onClick={handleCreate}
                disabled={
                  submitting || nameTaken || !embAvailable || !llmAvailable
                }
              >
                {submitting
                  ? "Creating…"
                  : files.length > 0
                    ? `Create & index ${files.length} file${files.length === 1 ? "" : "s"}`
                    : "Create project"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
