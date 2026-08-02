"use client"

import {
  ArrowsClockwise,
  DotsThree as MoreHorizontal,
  Key as KeyRound,
  Trash,
} from "@phosphor-icons/react/dist/ssr"
import Link from "next/link"
import { useRef, useState } from "react"
import { toast } from "@/lib/toast"
import useSWR, { mutate as globalMutate } from "swr"

import { BoxLoader } from "@/components/ui/box-loader"
import { Button } from "@/components/ui/button"
import { EncryptingLoader } from "@/components/ui/encrypting-loader"
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ApiError, api, fetcher } from "@/lib/api"
import type { ProviderId, ProviderKey } from "@/lib/types"

const PROVIDERS: { id: ProviderId; label: string; hint: string }[] = [
  { id: "openai", label: "OpenAI", hint: "Embeddings + chat (sk-…)" },
  {
    id: "gemini",
    label: "Google Gemini",
    hint: "Embeddings + chat (AI Studio AIza… or Vertex express AQ.… keys)",
  },
  { id: "anthropic", label: "Anthropic (Claude)", hint: "Chat only" },
  {
    id: "azure",
    label: "Azure OpenAI",
    hint: "Embeddings + chat (your resource endpoint + key; deployments named after models)",
  },
  { id: "mistral", label: "Mistral", hint: "Embeddings + chat" },
  { id: "cohere", label: "Cohere", hint: "Embeddings + chat" },
  { id: "together", label: "Together AI", hint: "Embeddings + chat (open models)" },
  { id: "fireworks", label: "Fireworks AI", hint: "Embeddings + chat (open models)" },
  { id: "xai", label: "xAI (Grok)", hint: "Chat only" },
  { id: "groq", label: "Groq", hint: "Chat only (fast open models)" },
  { id: "deepseek", label: "DeepSeek", hint: "Chat only" },
  { id: "openrouter", label: "OpenRouter", hint: "Chat only (one key, many models)" },
  { id: "perplexity", label: "Perplexity", hint: "Chat only (Sonar)" },
  { id: "voyage", label: "Voyage AI", hint: "Embeddings only" },
  { id: "jina", label: "Jina AI", hint: "Embeddings only" },
  { id: "sarvam", label: "Sarvam AI", hint: "Chat only (Indic LLMs)" },
]

function ProviderKeyActions({
  provider,
  existing,
  onEdit,
  onRefresh,
  refreshing,
  onRemove,
}: {
  provider: (typeof PROVIDERS)[number]
  existing?: ProviderKey
  onEdit: (provider: ProviderId) => void
  onRefresh: (provider: ProviderId) => void
  refreshing: boolean
  onRemove: (provider: ProviderId) => void
}) {
  return existing ? (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`${provider.label} key actions`}
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => onEdit(provider.id)}>
          <ArrowsClockwise className="size-4" />
          Replace
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={refreshing}
          onSelect={(e) => {
            // Keep the menu open while the vendor call is in flight, so the
            // disabled//"Checking" state is actually visible.
            e.preventDefault()
            onRefresh(provider.id)
          }}
        >
          <ArrowsClockwise className="size-4" />
          {refreshing ? "Checking…" : "Refresh model list"}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          variant="destructive"
          onSelect={() => onRemove(provider.id)}
        >
          <Trash className="size-4" />
          Remove
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  ) : (
    <Button variant="outline" size="sm" onClick={() => onEdit(provider.id)}>
      Add
    </Button>
  )
}

export function ProviderKeys() {
  const { data: keys, mutate } = useSWR<ProviderKey[]>(
    "/api/provider-keys",
    fetcher
  )
  const byProvider = new Map((keys ?? []).map((k) => [k.provider, k]))

  const [editing, setEditing] = useState<ProviderId | null>(null)
  const [value, setValue] = useState("")
  const [endpoint, setEndpoint] = useState("")
  const [saving, setSaving] = useState(false)
  // A key the provider REFUSED is a problem with the field, not an event: it
  // belongs beside the input, staying put while the user fetches the right
  // credential. The 340px toast auto-dismisses in 3s, which is not enough to
  // read "this is an OAuth token, you need an API key" and act on it.
  const [keyError, setKeyError] = useState<string | null>(null)
  const [removeTarget, setRemoveTarget] = useState<ProviderId | null>(null)
  const [removing, setRemoving] = useState(false)
  const [refreshing, setRefreshing] = useState<ProviderId | null>(null)
  const removeDone = useRef(false)

  async function refreshModels(provider: ProviderId) {
    setRefreshing(provider)
    try {
      await api(`/api/provider-keys/${provider}/refresh`, { method: "POST" })
      toast.success("Model list updated")
      mutate()
      // The merged catalog lives in /api/models, so the pickers only narrow
      // once that is revalidated too.
      globalMutate("/api/models")
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Could not refresh the model list"
      )
    } finally {
      setRefreshing(null)
    }
  }

  function openEditor(provider: ProviderId) {
    setValue("")
    setEndpoint("")
    setKeyError(null)
    setEditing(provider)
  }

  async function handleSave() {
    if (!editing || !value.trim()) return
    if (editing === "azure" && !endpoint.trim()) return
    setSaving(true)
    setKeyError(null)
    try {
      const body: Record<string, unknown> = {
        provider: editing,
        key: value.trim(),
      }
      if (editing === "azure") body.endpoint = endpoint.trim()
      // Minimum display time so the encrypting animation reads, not flashes.
      await Promise.all([
        api("/api/provider-keys", {
          method: "PUT",
          body: JSON.stringify(body),
        }),
        new Promise((resolve) => setTimeout(resolve, 1400)),
      ])
      toast.success("Key saved")
      setEditing(null)
      mutate()
      // availability is per-user, so refresh the wizard/settings catalog too
      globalMutate("/api/models")
    } catch (err) {
      // 422 is the provider itself refusing the credential - keep the dialog
      // open with the reason attached to the field so the key can be corrected
      // without retyping the rest. Everything else (network, 5xx) is a
      // transient event and stays a toast.
      const message = err instanceof Error ? err.message : "Failed to save key"
      if (err instanceof ApiError && err.status === 422) {
        setKeyError(message)
      } else {
        toast.error(message)
      }
    } finally {
      setSaving(false)
    }
  }

  async function confirmRemove() {
    if (!removeTarget) return
    removeDone.current = false
    setRemoving(true)
    try {
      await api(`/api/provider-keys/${removeTarget}`, { method: "DELETE" })
      mutate()
      globalMutate("/api/models")
      // Don't close yet - let the loader finish its current animation cycle.
      removeDone.current = true
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to remove key")
      setRemoving(false)
    }
  }

  function handleRemoveCycle() {
    if (!removeDone.current) return
    removeDone.current = false
    setRemoveTarget(null)
    setRemoving(false)
  }

  const editingProvider = PROVIDERS.find((p) => p.id === editing)
  const removingProvider = PROVIDERS.find((p) => p.id === removeTarget)

  return (
    // Fills the page's leftover height; only the table rows scroll (the card
    // title and the table header row stay pinned).
    <Card className="flex min-h-0 flex-1 flex-col gap-3 py-4 sm:gap-6 sm:py-6">
      <CardHeader className="shrink-0 gap-1.5 px-4 sm:gap-2 sm:px-6">
        <CardTitle>Provider API keys</CardTitle>
        <CardDescription className="text-xs leading-relaxed sm:text-sm">
          Bring your own keys. They&apos;re encrypted at rest and used for this
          account&apos;s projects. A project can override these with its own key.
          Prefer not to use a key? Run a local Ollama model instead.{" "}
          <Link
            href="/settings/report-key-issue"
            className="font-medium text-foreground underline underline-offset-4 transition-colors hover:text-foreground/70"
          >
            Key doesn&apos;t work or isn&apos;t supported? Report it.
          </Link>
        </CardDescription>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 overflow-y-auto p-0">
        <div className="sm:hidden">
          {PROVIDERS.map((provider) => {
            const existing = byProvider.get(provider.id)
            return (
              <div
                key={provider.id}
                className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3 border-b px-4 py-3 last:border-b-0"
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium">{provider.label}</div>
                  <div className="mt-0.5 text-xs leading-snug text-muted-foreground">
                    {provider.hint}
                  </div>
                </div>
                <div className="flex min-w-20 shrink-0 flex-col items-end gap-1.5">
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {existing ? `••••${existing.last4}` : "Not set"}
                  </span>
                  <ProviderKeyActions
                    provider={provider}
                    existing={existing}
                    onEdit={openEditor}
                    onRefresh={refreshModels}
                    refreshing={refreshing === provider.id}
                    onRemove={setRemoveTarget}
                  />
                </div>
              </div>
            )
          })}
        </div>

        <div className="hidden sm:block">
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-card">
              <TableRow>
                <TableHead className="pl-6">Provider</TableHead>
                <TableHead>Key</TableHead>
                <TableHead className="w-20 pr-6" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {PROVIDERS.map((provider) => {
                const existing = byProvider.get(provider.id)
                return (
                  <TableRow key={provider.id}>
                    <TableCell className="pl-6">
                      <div className="font-medium">{provider.label}</div>
                      <div className="text-xs text-muted-foreground">
                        {provider.hint}
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {existing ? (
                        <span>••••••••{existing.last4}</span>
                      ) : (
                        <span className="text-muted-foreground">Not set</span>
                      )}
                    </TableCell>
                    <TableCell className="w-20 pr-6 text-right">
                      <ProviderKeyActions
                        provider={provider}
                        existing={existing}
                        onEdit={openEditor}
                        onRefresh={refreshModels}
                        refreshing={refreshing === provider.id}
                        onRemove={setRemoveTarget}
                      />
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      </CardContent>

      <Dialog
        open={editing !== null}
        onOpenChange={(o) => {
          if (!o && !saving) setEditing(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              <KeyRound className="mr-1 inline size-4" />
              {editingProvider?.label} API key
            </DialogTitle>
            <DialogDescription>
              The key is checked with the provider before it&apos;s saved, then
              encrypted. We only keep the last 4 characters for display.
            </DialogDescription>
          </DialogHeader>
          {saving ? (
            <EncryptingLoader />
          ) : (
            <>
              {editing === "azure" && (
                <div className="space-y-2">
                  <Label htmlFor="provider-endpoint">Resource endpoint</Label>
                  <Input
                    id="provider-endpoint"
                    autoComplete="off"
                    placeholder="https://<resource>.openai.azure.com"
                    value={endpoint}
                    onChange={(e) => setEndpoint(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Deployments must be named after their model (e.g. a
                    deployment of gpt-4o called &quot;gpt-4o&quot;).
                  </p>
                </div>
              )}
              <div className="space-y-2">
                <Label htmlFor="provider-key">API key</Label>
                <Input
                  id="provider-key"
                  type="password"
                  autoComplete="off"
                  placeholder="Paste your key"
                  value={value}
                  aria-invalid={keyError !== null}
                  aria-describedby={keyError ? "provider-key-error" : undefined}
                  onChange={(e) => {
                    setValue(e.target.value)
                    // Clear on edit: a stale rejection sitting under a key the
                    // user has already replaced reads as a fresh failure.
                    if (keyError) setKeyError(null)
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleSave()
                  }}
                />
                {keyError && (
                  <p
                    id="provider-key-error"
                    role="alert"
                    className="text-xs leading-relaxed text-destructive"
                  >
                    {keyError}
                  </p>
                )}
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setEditing(null)}>
                  Cancel
                </Button>
                <Button
                  onClick={handleSave}
                  disabled={
                    saving ||
                    !value.trim() ||
                    (editing === "azure" && !endpoint.trim())
                  }
                >
                  Save key
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={removeTarget !== null}
        onOpenChange={(open) => {
          if (!open && !removing) setRemoveTarget(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove your {removingProvider?.label} key?</DialogTitle>
            {!removing && (
              <DialogDescription>
                Projects that rely on this account key - and have no key of
                their own - will stop embedding and answering until you add a
                new one.
              </DialogDescription>
            )}
          </DialogHeader>
          {removing ? (
            <div className="flex flex-col items-center gap-3 py-4">
              <BoxLoader scale={0.5} onCycle={handleRemoveCycle} />
              <p className="text-sm text-muted-foreground">Removing key…</p>
            </div>
          ) : (
            <DialogFooter>
              <Button variant="outline" onClick={() => setRemoveTarget(null)}>
                Cancel
              </Button>
              <Button variant="destructive" onClick={confirmRemove}>
                Remove key
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    </Card>
  )
}
