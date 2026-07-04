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
import { LoaderOne } from "@/components/ui/loader"
import { Progress } from "@/components/ui/progress"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { fetcher, uploadWithProgress } from "@/lib/api"
import { providerUsable } from "@/lib/models"
import type { ModelsResponse, Project } from "@/lib/types"

const ACCEPTED_FILE_TYPES = [
  ".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".html", ".htm", ".csv", ".json",
  ".xml", ".txt", ".md", ".rtf", ".odt", ".ods", ".odp", ".epub", ".eml",
  ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".wav", ".mp3",
  ".m4a", ".zip",
]
const ACCEPT_ATTR = ACCEPTED_FILE_TYPES.join(",")
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
  const [submitting, setSubmitting] = useState(false)
  const [progress, setProgress] = useState(0)
  const abortRef = useRef<AbortController | null>(null)

  const projectEmbedding = `${project.embedding_provider}/${project.embedding_model}`
  const embeddingChanged = embedding !== projectEmbedding
  const availability = models?.availability ?? {
    [project.embedding_provider]: true,
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
    }
  }

  function addFiles(list: FileList | null) {
    if (!list) return
    const next = [...files]
    for (const file of Array.from(list)) {
      const ext = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`
      if (!ACCEPTED_FILE_TYPES.includes(ext)) {
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
        <Button>
          <FileUp className="size-4" />
          Add files
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
              accept={ACCEPT_ATTR}
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
            <Select value={embedding} onValueChange={setEmbedding}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {models ? (
                  Object.entries(models.catalog.embedding).flatMap(
                    ([provider, entries]) =>
                      entries
                        .filter(
                          (entry) =>
                            providerUsable(
                              provider,
                              "embedding",
                              availability,
                              project
                            ) || `${provider}/${entry.model}` === embedding
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
                ) : (
                  <SelectItem value={embedding}>{embedding}</SelectItem>
                )}
              </SelectContent>
            </Select>
            {embeddingChanged && (
              <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
                The embedding model is project-wide. Changing it re-indexes all{" "}
                {project.file_count} existing file
                {project.file_count === 1 ? "" : "s"} too.
              </p>
            )}
          </div>

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
              ? <LoaderOne />
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
