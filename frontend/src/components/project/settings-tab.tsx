"use client"

import { useRouter } from "next/navigation"
import { useRef, useState } from "react"
import { toast } from "@/lib/toast"
import useSWR, { mutate as globalMutate } from "swr"

import { ProviderKeyField } from "@/components/project/provider-key-field"
import { BoxLoader } from "@/components/ui/box-loader"
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
import { EncryptingLoader } from "@/components/ui/encrypting-loader"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoaderOne } from "@/components/ui/loader"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { api, fetcher } from "@/lib/api"
import { providerOf, providerUsable } from "@/lib/models"
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

  // General
  const [name, setName] = useState(project.name)
  const [topK, setTopK] = useState(project.top_k)
  const [saving, setSaving] = useState(false)

  // Answer model (LLM) — instant save
  const [llm, setLlm] = useState(`${project.llm_provider}/${project.llm_model}`)
  const [llmKeyInput, setLlmKeyInput] = useState("")
  const [llmEditingKey, setLlmEditingKey] = useState(false)
  const [savingLlm, setSavingLlm] = useState(false)
  // True only while a NEW key is being encrypted + stored (drives the
  // encrypting animation; plain model changes keep the quiet button spinner).
  const [encryptingLlm, setEncryptingLlm] = useState(false)

  // Indexing + embedding — key-only change is instant; model/chunk change re-indexes
  const [chunkSize, setChunkSize] = useState(project.chunk_size)
  const [chunkOverlap, setChunkOverlap] = useState(project.chunk_overlap)
  const [embedding, setEmbedding] = useState(
    `${project.embedding_provider}/${project.embedding_model}`
  )
  const [embKeyInput, setEmbKeyInput] = useState("")
  const [embEditingKey, setEmbEditingKey] = useState(false)
  const [savingEmbKey, setSavingEmbKey] = useState(false)
  const [encryptingEmb, setEncryptingEmb] = useState(false)
  const [confirmReindex, setConfirmReindex] = useState(false)
  const [reindexing, setReindexing] = useState(false)

  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const deleteDone = useRef(false)

  // --- LLM derived state -----------------------------------------------------
  const llmProvider = providerOf(llm)
  const llmAccountHasKey = Boolean(availability[llmProvider])
  const llmOverrideLast4 =
    project.llm_provider === llmProvider ? project.llm_key_last4 : null
  const llmUsable =
    llmAccountHasKey || Boolean(llmOverrideLast4) || Boolean(llmKeyInput.trim())
  const llmChanged = llm !== `${project.llm_provider}/${project.llm_model}`
  const canSaveLlm = (llmChanged || Boolean(llmKeyInput.trim())) && llmUsable
  // No account key and no override → the input is shown unconditionally.
  const llmForcedInput = !llmAccountHasKey && !llmOverrideLast4

  // --- Embedding derived state ----------------------------------------------
  const embProvider = providerOf(embedding)
  const embAccountHasKey = Boolean(availability[embProvider])
  const embOverrideLast4 =
    project.embedding_provider === embProvider
      ? project.embedding_key_last4
      : null
  const embUsable =
    embAccountHasKey || Boolean(embOverrideLast4) || Boolean(embKeyInput.trim())
  const embModelChanged =
    embedding !== `${project.embedding_provider}/${project.embedding_model}`
  const chunkChanged =
    chunkSize !== project.chunk_size || chunkOverlap !== project.chunk_overlap
  const reindexNeeded = embModelChanged || chunkChanged
  const embKeyOnly = !reindexNeeded && Boolean(embKeyInput.trim())
  const embForcedInput = !embAccountHasKey && !embOverrideLast4

  function changeLlm(value: string) {
    setLlm(value)
    setLlmKeyInput("")
    setLlmEditingKey(false)
  }

  function changeEmbedding(value: string) {
    setEmbedding(value)
    setEmbKeyInput("")
    setEmbEditingKey(false)
  }

  async function handleSave() {
    setSaving(true)
    try {
      await api(`/api/projects/${project.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name, top_k: topK }),
      })
      toast.success("Settings saved")
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed")
    } finally {
      setSaving(false)
    }
  }

  async function handleSaveLlm() {
    const [provider, model] = llm.split("/", 2)
    const body: Record<string, unknown> = {
      llm_provider: provider,
      llm_model: model,
    }
    if (llmKeyInput.trim()) {
      body.llm_api_key = llmKeyInput.trim()
    } else if (provider !== project.llm_provider && project.llm_key_last4) {
      // Switching providers without a new key: the stored override belonged to
      // the old provider, so drop it and fall back to the account key.
      body.llm_api_key = ""
    }
    // A pasted key gets the encrypting animation (with a minimum display so
    // it reads, not flashes); a plain model change stays quiet.
    const encrypting = Boolean(body.llm_api_key)
    setSavingLlm(true)
    if (encrypting) setEncryptingLlm(true)
    try {
      await Promise.all([
        api(`/api/projects/${project.id}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        }),
        encrypting
          ? new Promise((resolve) => setTimeout(resolve, 1400))
          : Promise.resolve(),
      ])
      toast.success("Answer model saved")
      setLlmKeyInput("")
      setLlmEditingKey(false)
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed")
    } finally {
      setSavingLlm(false)
      setEncryptingLlm(false)
    }
  }

  async function patchLlmKey(value: string) {
    const encrypting = value !== ""
    setSavingLlm(true)
    if (encrypting) setEncryptingLlm(true)
    try {
      await Promise.all([
        api(`/api/projects/${project.id}`, {
          method: "PATCH",
          body: JSON.stringify({ llm_api_key: value }),
        }),
        encrypting
          ? new Promise((resolve) => setTimeout(resolve, 1400))
          : Promise.resolve(),
      ])
      toast.success(value === "" ? "Reverted to account key" : "Project key saved")
      setLlmKeyInput("")
      setLlmEditingKey(false)
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update key")
    } finally {
      setSavingLlm(false)
      setEncryptingLlm(false)
    }
  }

  async function patchEmbeddingKey(value: string) {
    const encrypting = value !== ""
    setSavingEmbKey(true)
    if (encrypting) setEncryptingEmb(true)
    try {
      await Promise.all([
        api(`/api/projects/${project.id}`, {
          method: "PATCH",
          body: JSON.stringify({ embedding_api_key: value }),
        }),
        encrypting
          ? new Promise((resolve) => setTimeout(resolve, 1400))
          : Promise.resolve(),
      ])
      toast.success(value === "" ? "Reverted to account key" : "Project key saved")
      setEmbKeyInput("")
      setEmbEditingKey(false)
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update key")
    } finally {
      setSavingEmbKey(false)
      setEncryptingEmb(false)
    }
  }

  async function handleReindex() {
    const [embeddingProvider, embeddingModel] = embedding.split("/", 2)
    const body: Record<string, unknown> = {
      chunk_size: chunkSize,
      chunk_overlap: chunkOverlap,
      embedding_provider: embeddingProvider,
      embedding_model: embeddingModel,
    }
    if (embKeyInput.trim()) {
      body.embedding_api_key = embKeyInput.trim()
    } else if (
      embeddingProvider !== project.embedding_provider &&
      project.embedding_key_last4
    ) {
      // Switching embedding providers without a new key: drop the stale
      // override so resolution falls back to the account key.
      body.embedding_api_key = ""
    }
    setReindexing(true)
    try {
      await api(`/api/projects/${project.id}/reindex`, {
        method: "POST",
        body: JSON.stringify(body),
      })
      toast.success("Re-indexing started — all files will be processed again")
      setConfirmReindex(false)
      setEmbKeyInput("")
      setEmbEditingKey(false)
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Re-index failed")
    } finally {
      setReindexing(false)
    }
  }

  async function handleDelete() {
    deleteDone.current = false
    setDeleting(true)
    try {
      await api(`/api/projects/${project.id}`, { method: "DELETE" })
      // Drop it from the dashboard/sidebar list right away so the deleted card
      // is gone the instant we navigate back (no stale flash before revalidate).
      globalMutate<Project[]>(
        "/api/projects",
        (list) => list?.filter((p) => p.id !== project.id),
        { revalidate: false }
      )
      // Don't navigate yet — let the loader finish its current animation cycle.
      deleteDone.current = true
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed")
      setDeleting(false)
    }
  }

  function handleDeleteCycle() {
    if (!deleteDone.current) return
    deleteDone.current = false
    toast.success("Project deleted")
    router.push("/dashboard")
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
              maxLength={20}
            />
            <div
              className={`text-right text-xs tabular-nums ${
                name.length >= 20
                  ? "text-amber-600 dark:text-amber-400"
                  : "text-muted-foreground"
              }`}
            >
              {name.length}/20
            </div>
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
          <Button onClick={handleSave} disabled={saving}>
            {saving ? <LoaderOne /> : "Save"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Answer model (LLM)</CardTitle>
          <CardDescription>
            The chat model used to write answers. Only providers you have a key
            for appear — add more in{" "}
            <a href="/settings/api-keys" className="underline">
              Settings → API keys
            </a>
            .
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>Model</Label>
            <Select value={llm} onValueChange={changeLlm}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {models ? (
                  Object.entries(models.catalog.llm).flatMap(([provider, names]) =>
                    names
                      .filter(
                        (model) =>
                          providerUsable(provider, "llm", availability, project) ||
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
                ) : (
                  <SelectItem value={llm}>{llm}</SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>
          {encryptingLlm ? (
            <EncryptingLoader rows={3} />
          ) : (
            <ProviderKeyField
              provider={llmProvider}
              last4={llmOverrideLast4}
              accountHasKey={llmAccountHasKey}
              value={llmKeyInput}
              onChange={setLlmKeyInput}
              editing={llmEditingKey}
              onEditingChange={setLlmEditingKey}
              onRemove={() => patchLlmKey("")}
              busy={savingLlm}
            />
          )}
          {!encryptingLlm && (llmEditingKey || llmForcedInput || llmChanged) && (
            <div className="flex gap-2">
              {llmEditingKey && (
                <Button
                  variant="outline"
                  onClick={() => {
                    setLlmKeyInput("")
                    setLlmEditingKey(false)
                  }}
                >
                  Cancel
                </Button>
              )}
              <Button onClick={handleSaveLlm} disabled={!canSaveLlm || savingLlm}>
                {savingLlm ? <LoaderOne /> : "Save"}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Indexing &amp; embedding</CardTitle>
          <CardDescription>
            The embedding model turns text into vectors. Changing the model or
            chunking re-processes every file; changing only the key is instant.
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
            <Select value={embedding} onValueChange={changeEmbedding}>
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
          </div>
          {encryptingEmb ? (
            <EncryptingLoader rows={3} />
          ) : (
            <ProviderKeyField
              provider={embProvider}
              last4={embOverrideLast4}
              accountHasKey={embAccountHasKey}
              value={embKeyInput}
              onChange={setEmbKeyInput}
              editing={embEditingKey}
              onEditingChange={setEmbEditingKey}
              onRemove={() => patchEmbeddingKey("")}
              busy={savingEmbKey}
            />
          )}
          {!encryptingEmb && (reindexNeeded || embEditingKey || embForcedInput) && (
            <div className="flex gap-2">
              {embEditingKey && (
                <Button
                  variant="outline"
                  onClick={() => {
                    setEmbKeyInput("")
                    setEmbEditingKey(false)
                  }}
                >
                  Cancel
                </Button>
              )}
              {reindexNeeded ? (
                <Button
                  onClick={() => setConfirmReindex(true)}
                  disabled={!embUsable || reindexing}
                >
                  Change &amp; re-index
                </Button>
              ) : (
                <Button
                  onClick={() => patchEmbeddingKey(embKeyInput.trim())}
                  disabled={!embKeyOnly || savingEmbKey}
                >
                  {savingEmbKey ? <LoaderOne /> : "Save"}
                </Button>
              )}
            </div>
          )}
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
              {reindexing ? <LoaderOne /> : "Re-index"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={confirmDelete}
        onOpenChange={(open) => {
          if (!open && !deleting) setConfirmDelete(false)
        }}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete {project.name}?</DialogTitle>
            {!deleting && (
              <DialogDescription>
                This permanently removes the project, its files, index, and API
                keys. Apps calling its endpoint will break.
              </DialogDescription>
            )}
          </DialogHeader>
          {deleting ? (
            <div className="flex flex-col items-center gap-3 py-4">
              <BoxLoader scale={0.5} onCycle={handleDeleteCycle} />
              <p className="text-xs text-muted-foreground">
                Permanently deleting…
              </p>
            </div>
          ) : (
            <DialogFooter>
              <Button variant="outline" onClick={() => setConfirmDelete(false)}>
                Cancel
              </Button>
              <Button variant="destructive" onClick={handleDelete}>
                Delete forever
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
