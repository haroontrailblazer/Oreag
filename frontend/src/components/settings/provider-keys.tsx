"use client"

import { Key as KeyRound } from "@phosphor-icons/react/dist/ssr"
import { useRef, useState } from "react"
import { toast } from "@/lib/toast"
import useSWR, { mutate as globalMutate } from "swr"

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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoaderOne } from "@/components/ui/loader"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { api, fetcher } from "@/lib/api"
import type { ProviderId, ProviderKey } from "@/lib/types"

const PROVIDERS: { id: ProviderId; label: string; hint: string }[] = [
  { id: "openai", label: "OpenAI", hint: "Embeddings + chat (sk-…)" },
  { id: "gemini", label: "Google Gemini", hint: "Embeddings + chat" },
  { id: "anthropic", label: "Anthropic (Claude)", hint: "Chat only" },
  { id: "sarvam", label: "Sarvam AI", hint: "Chat only (Indic LLMs)" },
]

export function ProviderKeys() {
  const { data: keys, mutate } = useSWR<ProviderKey[]>(
    "/api/provider-keys",
    fetcher
  )
  const byProvider = new Map((keys ?? []).map((k) => [k.provider, k]))

  const [editing, setEditing] = useState<ProviderId | null>(null)
  const [value, setValue] = useState("")
  const [saving, setSaving] = useState(false)
  const [removeTarget, setRemoveTarget] = useState<ProviderId | null>(null)
  const [removing, setRemoving] = useState(false)
  const removeDone = useRef(false)

  function openEditor(provider: ProviderId) {
    setValue("")
    setEditing(provider)
  }

  async function handleSave() {
    if (!editing || !value.trim()) return
    setSaving(true)
    try {
      await api("/api/provider-keys", {
        method: "PUT",
        body: JSON.stringify({ provider: editing, key: value.trim() }),
      })
      toast.success("Key saved")
      setEditing(null)
      mutate()
      // availability is per-user, so refresh the wizard/settings catalog too
      globalMutate("/api/models")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save key")
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
      // Don't close yet — let the loader finish its current animation cycle.
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
    <Card>
      <CardHeader>
        <CardTitle>Provider API keys</CardTitle>
        <CardDescription>
          Bring your own keys. They&apos;re encrypted at rest and used for this
          account&apos;s projects. A project can override these with its own key.
          Prefer not to use a key? Run a local Ollama model instead.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-6">Provider</TableHead>
              <TableHead>Key</TableHead>
              <TableHead className="w-40 pr-6" />
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
                  <TableCell className="space-x-2 pr-6 text-right">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => openEditor(provider.id)}
                    >
                      {existing ? "Replace" : "Add"}
                    </Button>
                    {existing && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setRemoveTarget(provider.id)}
                      >
                        Remove
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </CardContent>

      <Dialog open={editing !== null} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              <KeyRound className="mr-1 inline size-4" />
              {editingProvider?.label} API key
            </DialogTitle>
            <DialogDescription>
              Pasted keys are encrypted before they&apos;re stored. We only keep
              the last 4 characters for display.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="provider-key">API key</Label>
            <Input
              id="provider-key"
              type="password"
              autoComplete="off"
              placeholder="Paste your key"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSave()
              }}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={saving || !value.trim()}>
              {saving ? <LoaderOne /> : "Save key"}
            </Button>
          </DialogFooter>
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
                Projects that rely on this account key — and have no key of
                their own — will stop embedding and answering until you add a
                new one.
              </DialogDescription>
            )}
          </DialogHeader>
          {removing ? (
            <div className="flex flex-col items-center gap-2 py-4">
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
