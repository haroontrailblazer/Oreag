"use client"

import { KeyRound } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import useSWR, { mutate as globalMutate } from "swr"

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

  async function handleRemove(provider: ProviderId) {
    if (!confirm(`Remove your ${provider} key? Projects using it will stop working.`)) {
      return
    }
    try {
      await api(`/api/provider-keys/${provider}`, { method: "DELETE" })
      mutate()
      globalMutate("/api/models")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to remove key")
    }
  }

  const editingProvider = PROVIDERS.find((p) => p.id === editing)

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
                        onClick={() => handleRemove(provider.id)}
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
              {saving ? "Saving…" : "Save key"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
