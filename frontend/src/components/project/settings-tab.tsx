"use client"

import { useRouter } from "next/navigation"
import { useState } from "react"
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { api, fetcher } from "@/lib/api"
import type { ModelsResponse, Project } from "@/lib/types"

export function SettingsTab({
  project,
  onChanged,
}: {
  project: Project
  onChanged: () => void
}) {
  const router = useRouter()
  const { data: models } = useSWR<ModelsResponse>("/api/models", fetcher)
  const availability = models?.availability ?? { openai: true }

  // instant edits
  const [name, setName] = useState(project.name)
  const [topK, setTopK] = useState(project.top_k)
  const [llm, setLlm] = useState(`${project.llm_provider}/${project.llm_model}`)
  const [saving, setSaving] = useState(false)

  // reindex-required edits
  const [chunkSize, setChunkSize] = useState(project.chunk_size)
  const [chunkOverlap, setChunkOverlap] = useState(project.chunk_overlap)
  const [embedding, setEmbedding] = useState(
    `${project.embedding_provider}/${project.embedding_model}`
  )
  const [confirmReindex, setConfirmReindex] = useState(false)
  const [reindexing, setReindexing] = useState(false)

  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const reindexNeeded =
    chunkSize !== project.chunk_size ||
    chunkOverlap !== project.chunk_overlap ||
    embedding !== `${project.embedding_provider}/${project.embedding_model}`

  async function handleSave() {
    const [llmProvider, llmModel] = llm.split("/", 2)
    setSaving(true)
    try {
      await api(`/api/projects/${project.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name,
          top_k: topK,
          llm_provider: llmProvider,
          llm_model: llmModel,
        }),
      })
      toast.success("Settings saved")
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed")
    } finally {
      setSaving(false)
    }
  }

  async function handleReindex() {
    const [embeddingProvider, embeddingModel] = embedding.split("/", 2)
    setReindexing(true)
    try {
      await api(`/api/projects/${project.id}/reindex`, {
        method: "POST",
        body: JSON.stringify({
          chunk_size: chunkSize,
          chunk_overlap: chunkOverlap,
          embedding_provider: embeddingProvider,
          embedding_model: embeddingModel,
        }),
      })
      toast.success("Re-indexing started — all files will be processed again")
      setConfirmReindex(false)
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Re-index failed")
    } finally {
      setReindexing(false)
    }
  }

  async function handleDelete() {
    setDeleting(true)
    try {
      await api(`/api/projects/${project.id}`, { method: "DELETE" })
      toast.success("Project deleted")
      router.push("/dashboard")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed")
      setDeleting(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>General</CardTitle>
          <CardDescription>These take effect immediately.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="settings-name">Project name</Label>
            <Input
              id="settings-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Answer model (LLM)</Label>
              <Select value={llm} onValueChange={setLlm}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {models ? (
                    Object.entries(models.catalog.llm).flatMap(
                      ([provider, names]) =>
                        names.map((model) => (
                          <SelectItem
                            key={`${provider}/${model}`}
                            value={`${provider}/${model}`}
                            disabled={!availability[provider]}
                          >
                            {provider} / {model}
                          </SelectItem>
                        ))
                    )
                  ) : (
                    <SelectItem value={llm}>{llm}</SelectItem>
                  )}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="settings-topk">Top-K results</Label>
              <Input
                id="settings-topk"
                type="number"
                min={1}
                max={20}
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
              />
            </div>
          </div>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Indexing configuration</CardTitle>
          <CardDescription>
            Changing these requires re-processing every file (&quot;update
            memory&quot;). Existing chunks are replaced.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="settings-chunk-size">Chunk size</Label>
              <Input
                id="settings-chunk-size"
                type="number"
                min={100}
                max={8000}
                value={chunkSize}
                onChange={(e) => setChunkSize(Number(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="settings-chunk-overlap">Chunk overlap</Label>
              <Input
                id="settings-chunk-overlap"
                type="number"
                min={0}
                value={chunkOverlap}
                onChange={(e) => setChunkOverlap(Number(e.target.value))}
              />
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
                      entries.map((entry) => (
                        <SelectItem
                          key={`${provider}/${entry.model}`}
                          value={`${provider}/${entry.model}`}
                          disabled={!availability[provider]}
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
          </div>
          <Button
            variant={reindexNeeded ? "default" : "outline"}
            disabled={!reindexNeeded && project.status !== "error"}
            onClick={() => setConfirmReindex(true)}
          >
            Change &amp; re-index
          </Button>
        </CardContent>
      </Card>

      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="text-destructive">Danger zone</CardTitle>
          <CardDescription>
            Deletes the project, all files, chunks, and API keys. Cannot be
            undone.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="destructive" onClick={() => setConfirmDelete(true)}>
            Delete project
          </Button>
        </CardContent>
      </Card>

      <Dialog open={confirmReindex} onOpenChange={setConfirmReindex}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Re-index all files?</DialogTitle>
            <DialogDescription>
              All {project.file_count} file(s) will be re-chunked and
              re-embedded with the new configuration. Queries may return
              incomplete results until indexing finishes.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmReindex(false)}>
              Cancel
            </Button>
            <Button onClick={handleReindex} disabled={reindexing}>
              {reindexing ? "Starting…" : "Re-index"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {project.name}?</DialogTitle>
            <DialogDescription>
              This permanently removes the project, its files, index, and API
              keys. Apps calling its endpoint will break.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDelete(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting ? "Deleting…" : "Delete forever"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
