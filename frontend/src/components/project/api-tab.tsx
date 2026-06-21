"use client"

import {
  DotsThree as MoreHorizontal,
  Key as KeyRound,
  Plus,
  Prohibit,
  Trash,
} from "@phosphor-icons/react/dist/ssr"
import { useEffect, useRef, useState } from "react"
import { toast } from "@/lib/toast"
import useSWR from "swr"

import { CopyField } from "@/components/copy-field"
import { Badge } from "@/components/ui/badge"
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
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
  const [togglingId, setTogglingId] = useState<string | null>(null)
  const [revokeTarget, setRevokeTarget] = useState<ApiKey | null>(null)
  const [revoking, setRevoking] = useState(false)
  const revokeDone = useRef(false)
  const [deleteTarget, setDeleteTarget] = useState<ApiKey | null>(null)
  const [deleting, setDeleting] = useState(false)
  const deleteDone = useRef(false)

  // Resolve the public base URL on the client so the copyable endpoint reflects
  // the host the dashboard is actually open on (localhost or a LAN IP).
  const [apiBase, setApiBase] = useState("")
  useEffect(() => setApiBase(getApiBase()), [])

  const endpoint = `${apiBase}/v1/projects/${project.id}/query`
  const uploadEndpoint = `${apiBase}/v1/projects/${project.id}/files`
  const memoryGraphEndpoint = `${apiBase}/v1/projects/${project.id}/memory-graph`

  const uploadCurl = `curl -X POST ${uploadEndpoint} \\
  -H "Authorization: Bearer YOUR_UPLOAD_KEY" \\
  -F "uploads=@document.pdf"`

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

  // Per-project remote MCP connector (the multi-tenant mcp-server/). The host
  // comes from NEXT_PUBLIC_MCP_URL; callers authenticate with an API key as the
  // bearer token. Falls back to a placeholder host when the env isn't set.
  const mcpBase = (
    process.env.NEXT_PUBLIC_MCP_URL || "https://your-mcp-host"
  ).replace(/\/+$/, "")
  const mcpConnectorUrl = `${mcpBase}/projects/${project.id}/mcp`
  const mcpAddCommand = `claude mcp add --transport http oreag \\
  ${mcpConnectorUrl} \\
  --header "Authorization: Bearer YOUR_API_KEY"`

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

  async function handleToggleUpload(key: ApiKey, value: boolean) {
    setTogglingId(key.id)
    // Optimistically flip the row, then PATCH; revert on failure.
    mutate(
      (current) =>
        current?.map((k) => (k.id === key.id ? { ...k, can_upload: value } : k)),
      { revalidate: false }
    )
    try {
      await api(`/api/projects/${project.id}/keys/${key.id}`, {
        method: "PATCH",
        body: JSON.stringify({ can_upload: value }),
      })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update key")
      mutate()
    } finally {
      setTogglingId(null)
    }
  }

  async function confirmRevoke() {
    if (!revokeTarget) return
    revokeDone.current = false
    setRevoking(true)
    try {
      await api(`/api/projects/${project.id}/keys/${revokeTarget.id}`, {
        method: "DELETE",
      })
      mutate()
      // Don't close yet — let the loader finish its current animation cycle.
      revokeDone.current = true
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to revoke key")
      setRevoking(false)
    }
  }

  function handleRevokeCycle() {
    if (!revokeDone.current) return
    revokeDone.current = false
    setRevokeTarget(null)
    setRevoking(false)
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    deleteDone.current = false
    setDeleting(true)
    try {
      await api(`/api/projects/${project.id}/keys/${deleteTarget.id}/purge`, {
        method: "DELETE",
      })
      mutate()
      // Don't close yet — let the loader finish its current animation cycle.
      deleteDone.current = true
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete key")
      setDeleting(false)
    }
  }

  function handleDeleteCycle() {
    if (!deleteDone.current) return
    deleteDone.current = false
    setDeleteTarget(null)
    setDeleting(false)
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
          <div className="space-y-2">
            <h3 className="text-sm font-medium">Upload documents</h3>
            <p className="text-xs text-muted-foreground">
              Ingest files programmatically with a key that has{" "}
              <span className="font-medium">Allow uploads</span> enabled
              (read-only keys can&apos;t):
            </p>
            <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-xs">
              {uploadCurl}
            </pre>
          </div>
          <div className="space-y-2">
            <h3 className="text-sm font-medium">MCP connector (coding agents)</h3>
            <p className="text-xs text-muted-foreground">
              Connect Claude / Codex to this project — it adds memory and
              document search/answer tools. Add it as a remote MCP server,
              authenticating with an API key as the bearer token:
            </p>
            <CopyField value={mcpConnectorUrl} />
            <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-xs">
              {mcpAddCommand}
            </pre>
            {!process.env.NEXT_PUBLIC_MCP_URL && (
              <p className="text-xs text-amber-600 dark:text-amber-400">
                Set{" "}
                <code className="rounded bg-background px-1">
                  NEXT_PUBLIC_MCP_URL
                </code>{" "}
                to your deployed MCP server URL to fill in the host above.
              </p>
            )}
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
                <TableHead>Access</TableHead>
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
                      <Skeleton className="h-5 w-20 rounded-full" />
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
                    <TableCell className="w-20 pr-6 text-right" />
                  </TableRow>
                ))
              ) : keys.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={6}
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
                      <label
                        className={
                          key.revoked_at
                            ? "inline-flex items-center gap-1.5 text-xs opacity-50"
                            : "inline-flex cursor-pointer items-center gap-1.5 text-xs"
                        }
                      >
                        <input
                          type="checkbox"
                          checked={key.can_upload}
                          disabled={!!key.revoked_at || togglingId === key.id}
                          onChange={(e) => handleToggleUpload(key, e.target.checked)}
                          className="size-3.5 accent-foreground"
                        />
                        Uploads
                      </label>
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
                    <TableCell className="w-20 pr-6 text-right">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`${key.key_prefix} actions`}
                          >
                            <MoreHorizontal className="size-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {!key.revoked_at && (
                            <>
                              <DropdownMenuItem onSelect={() => setRevokeTarget(key)}>
                                <Prohibit className="size-4" />
                                Revoke
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                            </>
                          )}
                          <DropdownMenuItem
                            variant="destructive"
                            onSelect={() => setDeleteTarget(key)}
                          >
                            <Trash className="size-4" />
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
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
        onOpenChange={(open) => {
          if (!open && !revoking) setRevokeTarget(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revoke this API key?</DialogTitle>
            {!revoking && (
              <DialogDescription>
                Key{" "}
                <span className="font-mono">{revokeTarget?.key_prefix}…</span>{" "}
                will stop working immediately. Any app or agent using it will
                start getting 401 errors. This cannot be undone.
              </DialogDescription>
            )}
          </DialogHeader>
          {revoking ? (
            <div className="flex flex-col items-center gap-2 py-4">
              <BoxLoader scale={0.5} onCycle={handleRevokeCycle} />
              <p className="text-sm text-muted-foreground">Revoking key…</p>
            </div>
          ) : (
            <DialogFooter>
              <Button variant="outline" onClick={() => setRevokeTarget(null)}>
                Cancel
              </Button>
              <Button variant="destructive" onClick={confirmRevoke}>
                Revoke key
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open && !deleting) setDeleteTarget(null)
        }}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete this API key?</DialogTitle>
            {!deleting && (
              <DialogDescription>
                Key{" "}
                <span className="font-mono">{deleteTarget?.key_prefix}…</span>{" "}
                will be permanently removed from the database. Any app or agent
                using it stops working immediately — this cannot be undone.
              </DialogDescription>
            )}
          </DialogHeader>
          {deleting ? (
            <div className="flex flex-col items-center gap-6 px-6 py-6">
              <BoxLoader scale={0.5} onCycle={handleDeleteCycle} />
              <p className="text-xs text-muted-foreground">
                Permanently deleting…
              </p>
            </div>
          ) : (
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleteTarget(null)}>
                Cancel
              </Button>
              <Button variant="destructive" onClick={confirmDelete}>
                Delete
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
