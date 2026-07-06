"use client"

import {
  Check,
  Copy,
  DotsThree as MoreHorizontal,
  Key as KeyRound,
  Plus,
  Prohibit,
  Trash,
} from "@phosphor-icons/react/dist/ssr"
import { useRef, useState, useSyncExternalStore } from "react"
import { toast } from "@/lib/toast"
import useSWR from "swr"

import { Badge } from "@/components/ui/badge"
import { BestPractices } from "@/components/ui/best-practices"
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { getApiBase, api, fetcher } from "@/lib/api"
import type { ApiKey, ApiKeyCreated, Project } from "@/lib/types"

/* ------------------------------------------------------------------ */
/* Reference / quickstart primitives                                   */
/* ------------------------------------------------------------------ */

/** Small copy button with check feedback; `tone` adapts it to dark panels. */
function CopyButton({
  value,
  tone = "light",
  label = "Copy",
}: {
  value: string
  tone?: "light" | "dark"
  label?: string
}) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    await navigator.clipboard.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      onClick={copy}
      aria-label={label}
      className={
        tone === "dark"
          ? "size-7 shrink-0 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
          : "size-7 shrink-0 text-muted-foreground hover:text-foreground"
      }
    >
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
    </Button>
  )
}

/** Production-style code block: dark canvas in both themes, header bar with a
 * label + copy action, horizontal scroll for long lines. */
function CodePanel({ title, code }: { title: string; code: string }) {
  return (
    <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950">
      <div className="flex items-center justify-between border-b border-zinc-800 bg-zinc-900/80 py-1.5 pl-4 pr-2">
        <span className="font-mono text-[11px] font-medium tracking-wide text-zinc-400">
          {title}
        </span>
        <CopyButton value={code} tone="dark" label={`Copy ${title}`} />
      </div>
      <pre className="overflow-x-auto p-4 font-mono text-[12.5px] leading-relaxed text-zinc-100">
        {code}
      </pre>
    </div>
  )
}

/** Mono value in a quiet field with a copy action (URLs, keys). */
function CopyRow({ value, label }: { value: string; label: string }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border bg-muted/40 py-2 pl-4 pr-2">
      <span className="min-w-0 flex-1 truncate font-mono text-[12.5px]">
        {value}
      </span>
      <CopyButton value={value} label={label} />
    </div>
  )
}

const METHOD_STYLES: Record<string, string> = {
  GET: "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  POST: "border-sky-500/30 bg-sky-500/10 text-sky-600 dark:text-sky-400",
}

/** One row of the endpoint reference: method chip, path, purpose, copy URL. */
function EndpointRow({
  method,
  path,
  url,
  description,
}: {
  method: "GET" | "POST"
  path: string
  url: string
  description: string
}) {
  return (
    <div className="flex items-center gap-3 border-b px-6 py-3 last:border-b-0">
      <Badge
        variant="outline"
        className={`w-14 justify-center font-mono text-[10.5px] font-semibold ${METHOD_STYLES[method]}`}
      >
        {method}
      </Badge>
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-[12.5px] text-foreground">{path}</p>
        <p className="truncate text-xs text-muted-foreground">{description}</p>
      </div>
      <CopyButton value={url} label={`Copy ${method} ${path} URL`} />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* API tab                                                             */
/* ------------------------------------------------------------------ */

const BEST_PRACTICE_TIPS = [
  {
    title: "Keys are shown once",
    detail:
      "The full oreag_sk_ key appears only at creation - store it in a secret manager immediately. Only the last 4 characters are kept for display.",
  },
  {
    title: "Never ship keys to browsers",
    detail:
      "Call /v1 from your server or agent backend. A key embedded in client-side code is public.",
  },
  {
    title: "One key per consumer",
    detail:
      "Give each app, agent, or teammate its own key so usage is attributable and revoking one does not break the others.",
  },
  {
    title: "Use conversation_id for chat",
    detail:
      "Pass any stable string and follow-ups are rewritten with context server-side. Omit it for stateless one-off queries.",
  },
  {
    title: "Read the cache fields",
    detail:
      "Responses include cache_layer (l1 exact, l2 semantic, null fresh) and cache_similarity - useful for logging cost savings on your side.",
  },
]

// Static-value "store" plumbing for useSyncExternalStore: the API base never
// changes after load, so subscribing is a no-op.
const subscribeNoop = () => () => {}
const getServerApiBase = () => ""

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
  // useSyncExternalStore keeps the server render ("") hydration-safe without
  // setting state inside an effect.
  const apiBase = useSyncExternalStore(subscribeNoop, getApiBase, getServerApiBase)

  const basePath = `/v1/projects/${project.id}`
  const endpoint = `${apiBase}${basePath}/query`

  const endpoints = [
    {
      method: "POST" as const,
      path: `${basePath}/query`,
      description:
        "Ask a question - grounded answer with cited sources and conversation memory",
    },
    {
      method: "POST" as const,
      path: `${basePath}/retrieve`,
      description: "Retrieval only - top-matching chunks, no LLM call",
    },
    {
      method: "POST" as const,
      path: `${basePath}/files`,
      description: "Ingest documents (requires a key with upload permission)",
    },
    {
      method: "GET" as const,
      path: `${basePath}/memory-graph`,
      description: "Full agent memory graph - nodes and related edges",
    },
  ]

  const curlExample = `curl -X POST ${endpoint} \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "question": "What is this document about?",
    "conversation_id": "chat-001"
  }'`

  const jsExample = `const res = await fetch(
  "${endpoint}",
  {
    method: "POST",
    headers: {
      Authorization: "Bearer YOUR_API_KEY",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      question: "What is this document about?",
      conversation_id: "chat-001", // same id keeps follow-ups conversational
    }),
  }
);

const { answer, sources, needs_clarification } = await res.json();`

  const pythonExample = `import requests

res = requests.post(
    "${endpoint}",
    headers={"Authorization": "Bearer YOUR_API_KEY"},
    json={
        "question": "What is this document about?",
        "conversation_id": "chat-001",
    },
)
data = res.json()
print(data["answer"])`

  const responseExample = `{
  "answer": "This document describes... [1]",
  "sources": [
    {
      "filename": "handbook.pdf",
      "page_number": 12,
      "chunk_index": 4,
      "content": "...",
      "similarity": 0.87
    }
  ],
  "model": "${project.llm_provider}/${project.llm_model}",
  "latency_ms": 1240,
  "depth": "short",
  "sub_queries": [],
  "needs_clarification": false,
  "clarification_questions": [],
  "conversation_id": "chat-001"
}`

  const uploadExample = `curl -X POST ${apiBase}${basePath}/files \\
  -H "Authorization: Bearer YOUR_UPLOAD_KEY" \\
  -F "uploads=@document.pdf"`

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
      // Don't close yet - let the loader finish its current animation cycle.
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
      // Don't close yet - let the loader finish its current animation cycle.
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
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>API keys</CardTitle>
              <CardDescription>
                Keys are shown once at creation - store them securely.
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <BestPractices tips={BEST_PRACTICE_TIPS} />
              <Button
                onClick={handleCreate}
                disabled={creating}
                aria-label="Create key"
                title="Create key"
              >
                {creating ? (
                  <LoaderOne />
                ) : (
                  <>
                    <Plus className="size-4" />
                    <span className="hidden sm:inline">Create key</span>
                  </>
                )}
              </Button>
            </div>
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
                    No keys yet - create one to call your RAG API.
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

      <Card>
        <CardHeader>
          <CardTitle>API reference</CardTitle>
          <CardDescription>
            Authenticate every request with{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
              Authorization: Bearer oreag_sk_…
            </code>
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <div className="flex items-center gap-3 border-b bg-muted/40 px-6 py-2.5">
            <span className="shrink-0 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Base URL
            </span>
            <span className="min-w-0 flex-1 truncate font-mono text-[12.5px]">
              {apiBase || "…"}
            </span>
            <CopyButton value={apiBase} label="Copy base URL" />
          </div>
          {endpoints.map((ep) => (
            <EndpointRow
              key={ep.path}
              method={ep.method}
              path={ep.path}
              url={`${apiBase}${ep.path}`}
              description={ep.description}
            />
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Quickstart</CardTitle>
          <CardDescription>
            Query this project from your app - swap in an API key and go. Pass
            the same{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
              conversation_id
            </code>{" "}
            to make follow-ups like &ldquo;summarize that&rdquo; conversational.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <Tabs defaultValue="curl">
            <TabsList>
              <TabsTrigger value="curl">cURL</TabsTrigger>
              <TabsTrigger value="js">JavaScript</TabsTrigger>
              <TabsTrigger value="python">Python</TabsTrigger>
            </TabsList>
            <TabsContent value="curl">
              <CodePanel title="Terminal" code={curlExample} />
            </TabsContent>
            <TabsContent value="js">
              <CodePanel title="query.ts" code={jsExample} />
            </TabsContent>
            <TabsContent value="python">
              <CodePanel title="query.py" code={pythonExample} />
            </TabsContent>
          </Tabs>

          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">Response</span>
              <Badge
                variant="outline"
                className="border-emerald-500/30 bg-emerald-500/10 font-mono text-[10.5px] text-emerald-600 dark:text-emerald-400"
              >
                200 OK
              </Badge>
            </div>
            <CodePanel title="application/json" code={responseExample} />
          </div>

          <div className="space-y-2">
            <span className="text-sm font-medium">Ingest documents</span>
            <p className="text-xs leading-relaxed text-muted-foreground">
              Upload files programmatically with a key that has{" "}
              <span className="font-medium text-foreground">uploads</span>{" "}
              enabled - read-only keys get a 403.
            </p>
            <CodePanel title="Terminal" code={uploadExample} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>MCP connector</CardTitle>
          <CardDescription>
            Give coding agents (Claude Code, Codex) persistent memory and
            document search on this project - authenticate with an API key as
            the bearer token.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <CopyRow value={mcpConnectorUrl} label="Copy MCP connector URL" />
          <CodePanel title="Terminal" code={mcpAddCommand} />
          {!process.env.NEXT_PUBLIC_MCP_URL && (
            <p className="text-xs text-amber-600 dark:text-amber-400">
              Set{" "}
              <code className="rounded bg-muted px-1 font-mono">
                NEXT_PUBLIC_MCP_URL
              </code>{" "}
              to your deployed MCP server URL to fill in the host above.
            </p>
          )}
        </CardContent>
      </Card>

      <Dialog open={newKey !== null} onOpenChange={() => setNewKey(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>API key created</DialogTitle>
            <DialogDescription>
              Copy it now - this is the only time the full key is shown.
            </DialogDescription>
          </DialogHeader>
          {newKey && (
            <div className="space-y-2">
              <CopyRow value={newKey.key} label="Copy API key" />
              <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
                Copy this key now - for security it will{" "}
                <span className="font-medium">never be shown again</span>.
              </p>
            </div>
          )}
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
            <div className="flex flex-col items-center gap-3 py-4">
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
                using it stops working immediately - this cannot be undone.
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
