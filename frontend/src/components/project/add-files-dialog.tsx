"use client"

import { FileArrowUp as FileUp, X } from "@phosphor-icons/react/dist/ssr"
import { useRef, useState } from "react"
import { toast } from "@/lib/toast"
import useSWR from "swr"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Spin } from "@/components/ui/loader"
import { Progress } from "@/components/ui/progress"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { cn } from "@/lib/utils"
import { fetcher, uploadWithProgress } from "@/lib/api"
import { dimensionOptions, providerUsable } from "@/lib/models"
import type { ModelsResponse, Project } from "@/lib/types"

// No extension whitelist: the backend ingests any file it can extract text
// from (rich formats via MarkItDown, everything else as plain text) and
// rejects only opaque binary with a per-file error.
const MAX_FILE_MB = 50

export function AddFilesDialog({
  project,
  onUploaded,
}: {
  project: Project
  onUploaded: () => void
}) {
  const { data: models } = useSWR<ModelsResponse>("/api/models", fetcher)
  const fileInput = useRef<HTMLInputElement>(null)

  const [open, setOpen] = useState(false)
  const [files, setFiles] = useState<File[]>([])
  const [chunkSize, setChunkSize] = useState(project.chunk_size)
  const [chunkOverlap, setChunkOverlap] = useState(project.chunk_overlap)
  const [topK, setTopK] = useState(project.top_k)
  const [embedding, setEmbedding] = useState(
    `${project.embedding_provider}/${project.embedding_model}`
  )
  const [embDimensions, setEmbDimensions] = useState(project.embedding_dimensions)
  const [submitting, setSubmitting] = useState(false)
  const [progress, setProgress] = useState(0)
  const abortRef = useRef<AbortController | null>(null)

  const projectEmbedding = `${project.embedding_provider}/${project.embedding_model}`
  const embeddingChanged = embedding !== projectEmbedding
  const [embProvider] = embedding.split("/", 1)
  const embEntry = models?.catalog.embedding[embProvider]?.find(
    (entry) => `${embProvider}/${entry.model}` === embedding
  )
  const embDimOptions = embEntry ? dimensionOptions(embEntry) : [embDimensions]
  // Same MRL model at a smaller size: instant in-place truncation, no re-embed.
  const instantShrink =
    !embeddingChanged && embDimensions < project.embedding_dimensions
  const availability = models?.availability ?? {
    [project.embedding_provider]: true,
  }
  // The selected embedding model's provider may have lost its key - grey it and
  // warn, since indexing the upload needs an embedding key.
  const embCurrentUsable = providerUsable(
    embProvider,
    "embedding",
    availability,
    project
  )

  function changeEmbedding(value: string) {
    setEmbedding(value)
    const [prov, mod] = value.split("/", 2)
    if (value === projectEmbedding) {
      setEmbDimensions(project.embedding_dimensions)
    } else {
      const entry = models?.catalog.embedding[prov]?.find((e) => e.model === mod)
      setEmbDimensions(entry?.dimensions ?? project.embedding_dimensions)
    }
  }

  function onOpenChange(next: boolean) {
    // Closing mid-upload (overlay/Esc/X) cancels the in-flight request.
    if (!next && submitting) abortRef.current?.abort()
    setOpen(next)
    if (next) {
      setFiles([])
      setProgress(0)
      setChunkSize(project.chunk_size)
      setChunkOverlap(project.chunk_overlap)
      setTopK(project.top_k)
      setEmbedding(projectEmbedding)
      setEmbDimensions(project.embedding_dimensions)
    }
  }

  function addFiles(list: FileList | null) {
    if (!list) return
    const next = [...files]
    for (const file of Array.from(list)) {
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

  async function handleSubmit() {
    if (files.length === 0) return
    if (chunkOverlap >= chunkSize) {
      toast.error("Chunk overlap must be smaller than chunk size")
      return
    }
    const [embeddingProvider, embeddingModel] = embedding.split("/", 2)
    const form = new FormData()
    files.forEach((f) => form.append("uploads", f))
    form.append("chunk_size", String(chunkSize))
    form.append("chunk_overlap", String(chunkOverlap))
    form.append("top_k", String(topK))
    form.append("embedding_provider", embeddingProvider)
    form.append("embedding_model", embeddingModel)
    form.append("embedding_dimensions", String(embDimensions))
    const controller = new AbortController()
    abortRef.current = controller
    setProgress(0)
    setSubmitting(true)
    try {
      await uploadWithProgress(`/api/projects/${project.id}/files`, form, {
        onProgress: setProgress,
        signal: controller.signal,
      })
      toast.success(
        embeddingChanged
          ? "Upload complete - re-indexing the whole project"
          : instantShrink
            ? "Upload complete - vector size applied instantly, indexing new files"
            : "Upload complete - indexing started"
      )
      setOpen(false)
      onUploaded()
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        toast.info("Upload canceled")
      } else {
        toast.error(err instanceof Error ? err.message : "Upload failed")
      }
    } finally {
      abortRef.current = null
      setSubmitting(false)
      setProgress(0)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button
          aria-label="Add files"
          title="Add files"
          // Square icon button on mobile (matches the 3-dots actions button);
          // the default padded label from sm+ (desktop untouched).
          className="shrink-0 max-sm:w-9 max-sm:p-0"
        >
          <FileUp className="size-4" />
          <span className="hidden sm:inline">Add files</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto no-scrollbar sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add files</DialogTitle>
          <DialogDescription>
            Choose documents and how they should be indexed.
          </DialogDescription>
        </DialogHeader>

        <div className="min-w-0 space-y-4">
          <div className="space-y-2">
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault()
                addFiles(e.dataTransfer.files)
              }}
              className="flex w-full flex-col items-center gap-2 rounded-lg border-2 border-dashed p-6 text-sm text-muted-foreground hover:bg-muted/40"
            >
              <FileUp className="size-5" />
              Drag &amp; drop or click to choose (max {MAX_FILE_MB} MB each)
            </button>
            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              onChange={(e) => addFiles(e.target.files)}
            />
            {files.length > 0 && (
              <ul className="max-h-48 space-y-1 overflow-y-auto no-scrollbar">
                {files.map((file) => (
                  <li
                    key={file.name + file.size}
                    className="flex items-center gap-2 rounded border px-3 py-1.5 text-sm"
                  >
                    <span className="min-w-0 flex-1 truncate">{file.name}</span>
                    <button
                      type="button"
                      className="shrink-0"
                      onClick={() => setFiles(files.filter((f) => f !== file))}
                    >
                      <X className="size-4 text-muted-foreground" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="add-chunk-size">Chunk size</Label>
              <Input
                id="add-chunk-size"
                type="number"
                min={100}
                max={8000}
                value={chunkSize}
                onChange={(e) => setChunkSize(Number(e.target.value))}
              />
              <p className="text-xs text-muted-foreground">
                Characters per chunk, for these files.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="add-chunk-overlap">Chunk overlap</Label>
              <Input
                id="add-chunk-overlap"
                type="number"
                min={0}
                value={chunkOverlap}
                onChange={(e) => setChunkOverlap(Number(e.target.value))}
              />
              <p className="text-xs text-muted-foreground">
                Shared characters between chunks.
              </p>
            </div>
          </div>

          <div className="space-y-2">
            <Label>Embedding model</Label>
            <Select value={embedding} onValueChange={changeEmbedding}>
              <SelectTrigger className={cn("w-full", !embCurrentUsable && "text-muted-foreground")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {models ? (
                  Object.entries(models.catalog.embedding).flatMap(
                    ([provider, entries]) =>
                      entries
                        // Offer models whose provider has a usable key (account
                        // key or this project's override). The project's OWN
                        // current model stays selectable even if its key was
                        // removed - shown greyed with a "key removed" tag - so
                        // the Select is never empty.
                        .filter(
                          (entry) =>
                            providerUsable(
                              provider,
                              "embedding",
                              availability,
                              project
                            ) || `${provider}/${entry.model}` === projectEmbedding
                        )
                        .map((entry) => {
                          const value = `${provider}/${entry.model}`
                          const usable = providerUsable(
                            provider,
                            "embedding",
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
                              {provider} / {entry.model} ({entry.dimensions}d)
                              {!usable ? " · key removed" : ""}
                            </SelectItem>
                          )
                        })
                  )
                ) : (
                  <SelectItem value={embedding}>{embedding}</SelectItem>
                )}
              </SelectContent>
            </Select>
            {!embCurrentUsable && (
              <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
                The API key for {embProvider} was removed. Add it in Settings or
                choose a model whose provider still has a key - indexing needs an
                embedding key.
              </p>
            )}
            {embeddingChanged &&
              (project.file_count > 0 ? (
                <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
                  The embedding model is project-wide. Changing it re-indexes all{" "}
                  {project.file_count} existing file
                  {project.file_count === 1 ? "" : "s"} too.
                </p>
              ) : (
                <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
                  Sets the embedding model for this project. No existing files to
                  re-index yet.
                </p>
              ))}
          </div>

          {embDimOptions.length > 1 && (
            <div className="space-y-2">
              <Label>Vector dimensions</Label>
              <Select
                value={String(embDimensions)}
                onValueChange={(v) => setEmbDimensions(Number(v))}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {embDimOptions.map((d) => (
                    <SelectItem key={d} value={String(d)}>
                      {d}d{d === embEntry?.dimensions ? " (default)" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {instantShrink && (
                <p className="rounded-md bg-sky-50 px-3 py-2 text-xs text-sky-800 dark:bg-sky-950/40 dark:text-sky-300">
                  Same model, smaller size: existing vectors are truncated in
                  place (Matryoshka) - instant, nothing is re-embedded.
                </p>
              )}
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="add-topk">Top-K results: {topK}</Label>
            <Input
              id="add-topk"
              type="range"
              min={1}
              max={20}
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
            />
            <p className="text-xs text-muted-foreground">
              How many chunks are retrieved per question (project-wide).
            </p>
          </div>

          {submitting && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>
                  {progress < 100
                    ? `Uploading ${files.length} file${files.length === 1 ? "" : "s"}…`
                    : "Processing on the server…"}
                </span>
                <span className="tabular-nums">{progress}%</span>
              </div>
              <Progress value={progress} />
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              if (submitting) abortRef.current?.abort()
              else setOpen(false)
            }}
          >
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={submitting || files.length === 0}>
            {submitting
              ? <Spin />
              : embeddingChanged
                ? "Add & re-index"
                : files.length > 0
                  ? `Add ${files.length} file${files.length === 1 ? "" : "s"}`
                  : "Add files"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
