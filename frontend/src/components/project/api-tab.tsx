"use client"

import { Key as KeyRound, Plus } from "@phosphor-icons/react/dist/ssr"
import { useEffect, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { CopyField } from "@/components/copy-field"
import { Badge } from "@/components/ui/badge"
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
import { LoaderOne } from "@/components/ui/loader"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { getApiBase, api, fetcher } from "@/lib/api"
import type { ApiKey, ApiKeyCreated, Project } from "@/lib/types"

export function ApiTab({ project }: { project: Project }) {
  const { data: keys, mutate } = useSWR<ApiKey[]>(
    `/api/projects/${project.id}/keys`,
    fetcher
  )
  // Active keys (newest first) on top; revoked keys sink to the bottom.
  const sortedKeys = [...(keys ?? [])].sort((a, b) => {
    const aRevoked = a.revoked_at ? 1 : 0
    const bRevoked = b.revoked_at ? 1 : 0
    if (aRevoked !== bRevoked) return aRevoked - bRevoked
    return a.created_at < b.created_at ? 1 : -1
  })
  const [newKey, setNewKey] = useState<ApiKeyCreated | null>(null)
  const [creating, setCreating] = useState(false)
  const [revokeTarget, setRevokeTarget] = useState<ApiKey | null>(null)
  const [revoking, setRevoking] = useState(false)

  // Resolve the public base URL on the client so the copyable endpoint reflects
  // the host the dashboard is actually open on (localhost or a LAN IP).
  const [apiBase, setApiBase] = useState("")
  useEffect(() => setApiBase(getApiBase()), [])

  const endpoint = `${apiBase}/v1/projects/${project.id}/query`
  const memoryGraphEndpoint = `${apiBase}/v1/projects/${project.id}/memory-graph`

  const curlExample = `curl -X POST ${endpoint} \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"question": "What is this document about?"}'`

  const fetchExample = `const res = await fetch("${endpoint}", {
  method: "POST",
  headers: {
    Authorization: "Bearer YOUR_API_KEY",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ question: "What is this document about?" }),
});
const { answer, sources } = await res.json();`

  async function handleCreate() {
    setCreating(true)
    try {
      const created = await api<ApiKeyCreated>(
        `/api/projects/${project.id}/keys`,
        { method: "POST", body: JSON.stringify({ name: "default" }) }
      )
      setNewKey(created)
      mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create key")
    } finally {
      setCreating(false)
    }
  }

  async function confirmRevoke() {
    if (!revokeTarget) return
    setRevoking(true)
    try {
      await api(`/api/projects/${project.id}/keys/${revokeTarget.id}`, {
        method: "DELETE",
      })
      mutate()
      setRevokeTarget(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to revoke key")
    } finally {
      setRevoking(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Your RAG endpoint</CardTitle>
          <CardDescription>
            POST a question with an API key and get a grounded answer with
            sources.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <CopyField value={endpoint} />
          <div className="space-y-2">
            <h3 className="text-sm font-medium">Agent memory graph</h3>
            <CopyField value={memoryGraphEndpoint} />
          </div>
          <div className="space-y-2">
            <h3 className="text-sm font-medium">curl</h3>
            <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-xs">
              {curlExample}
            </pre>
          </div>
          <div className="space-y-2">
            <h3 className="text-sm font-medium">JavaScript</h3>
            <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-xs">
              {fetchExample}
            </pre>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>API keys</CardTitle>
              <CardDescription>
                Keys are shown once at creation — store them securely.
              </CardDescription>
            </div>
            <Button onClick={handleCreate} disabled={creating}>
              {creating ? (
                <LoaderOne />
              ) : (
                <>
                  <Plus className="size-4" /> Create key
                </>
              )}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-6">Key</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Last used</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-20 pr-6" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {!keys ? (
                [0, 1, 2].map((i) => (
                  <TableRow key={i}>
                    <TableCell className="pl-6">
                      <Skeleton className="h-4 w-24" />
                    </TableCell>
                    <TableCell>
                      <Skeleton className="h-4 w-20" />
                    </TableCell>
                    <TableCell>
                      <Skeleton className="h-4 w-28" />
                    </TableCell>
                    <TableCell>
                      <Skeleton className="h-5 w-16 rounded-full" />
                    </TableCell>
                    <TableCell className="pr-6" />
                  </TableRow>
                ))
              ) : keys.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="py-10 text-center text-muted-foreground"
                  >
                    <KeyRound className="mx-auto mb-2 size-6" />
                    No keys yet — create one to call your RAG API.
                  </TableCell>
                </TableRow>
              ) : (
                sortedKeys.map((key) => (
                  <TableRow key={key.id}>
                    <TableCell className="pl-6 font-mono text-xs">
                      {key.key_prefix}…
                    </TableCell>
                    <TableCell>
                      {new Date(key.created_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell>
                      {key.last_used_at
                        ? new Date(key.last_used_at).toLocaleString()
                        : "Never"}
                    </TableCell>
                    <TableCell>
                      {key.revoked_at ? (
                        <Badge variant="secondary">Revoked</Badge>
                      ) : (
                        <Badge className="border-transparent bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400">
                          Active
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="pr-6">
                      {!key.revoked_at && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setRevokeTarget(key)}
                        >
                          Revoke
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={newKey !== null} onOpenChange={() => setNewKey(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>API key created</DialogTitle>
            <DialogDescription>
              Copy it now — this is the only time the full key is shown.
            </DialogDescription>
          </DialogHeader>
          {newKey && <CopyField value={newKey.key} />}
        </DialogContent>
      </Dialog>

      <Dialog
        open={revokeTarget !== null}
        onOpenChange={(open) => !open && setRevokeTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revoke this API key?</DialogTitle>
            <DialogDescription>
              Key{" "}
              <span className="font-mono">{revokeTarget?.key_prefix}…</span> will
              stop working immediately. Any app or agent using it will start
              getting 401 errors. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRevokeTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={confirmRevoke}
              disabled={revoking}
            >
              {revoking ? <LoaderOne /> : "Revoke key"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
