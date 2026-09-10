"use client"

import {
  CheckIcon as Check,
  CopyIcon as Copy,
  DotsThreeIcon as MoreHorizontal,
  KeyIcon as KeyRound,
  ShieldWarningIcon as ShieldWarning,
  PlusIcon as Plus,
  ProhibitIcon as Prohibit,
  TrashIcon as Trash,
  CodeIcon as Code,
  TerminalWindowIcon as Terminal,
  PlugsConnectedIcon as Plugs,
} from "@phosphor-icons/react/dist/ssr"
import { useEffect, useRef, useState, useSyncExternalStore } from "react"
import { toast } from "@/lib/toast"
import useSWR from "swr"

import { WebhooksPanel } from "./webhooks-panel"
import { Badge } from "@/components/ui/badge"
import { BestPractices } from "@/components/ui/best-practices"
import {
  CacheViz,
  ConversationViz,
  KeysMultiViz,
  KeyViz,
  ServerViz,
} from "@/components/ui/best-practice-visuals"
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
import { Spin } from "@/components/ui/loader"
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
import styles from "./api-tab.module.css"

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
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])

  async function copy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      clearTimeout(timer.current)
      timer.current = setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error("Couldn't copy. Select the text and copy it manually.")
    }
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      onClick={copy}
      aria-label={copied ? `${label}: copied` : label}
      title={copied ? "Copied" : label}
      data-tone={tone}
      className={styles.copyButton}
    >
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
    </Button>
  )
}

/** Production-style code block: dark canvas in both themes, header bar with a
 * label + copy action, horizontal scroll for long lines. */
function CodePanel({ title, code }: { title: string; code: string }) {
  return (
    <div className={styles.codePanel}>
      <div className={styles.codeHeader}>
        <span className="font-mono text-[11px] font-medium tracking-wide text-zinc-400">
          {title}
        </span>
        <CopyButton value={code} tone="dark" label={`Copy ${title}`} />
      </div>
      <pre tabIndex={0} aria-label={`${title} code`}>
        <code>{code}</code>
      </pre>
    </div>
  )
}

/** Mono value in a quiet field with a copy action (URLs, keys). */
function CopyRow({ value, label }: { value: string; label: string }) {
  return (
    <div className={styles.copyRow}>
      <span className="min-w-0 flex-1 break-all font-mono text-[12.5px]">
        {value}
      </span>
      <CopyButton value={value} label={label} />
    </div>
  )
}

const METHOD_STYLES: Record<string, string> = {
  GET: "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  PUT: "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400",
  DELETE: "border-rose-500/30 bg-rose-500/10 text-rose-600 dark:text-rose-400",
  POST: "border-sky-500/30 bg-sky-500/10 text-sky-600 dark:text-sky-400",
}

/** One row of the endpoint reference: method chip, path, purpose, copy URL. */
function EndpointRow({
  method,
  path,
  url,
  description,
}: {
  method: "GET" | "POST" | "PUT" | "DELETE"
  path: string
  url: string
  description: string
}) {
  return (
    <div className={styles.endpoint}>
      <Badge
        variant="outline"
        className={`w-14 justify-center font-mono text-[10.5px] font-semibold ${METHOD_STYLES[method]}`}
      >
        {method}
      </Badge>
      <div className="min-w-0 flex-1">
        <p className="break-all font-mono text-[12.5px] text-foreground">{path}</p>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{description}</p>
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
    visual: <KeyViz />,
    title: "Keys are shown once",
    detail:
      "The full oreag_sk_ key appears only at creation - store it in a secret manager immediately. Only the last 4 characters are kept for display.",
  },
  {
    visual: <ServerViz />,
    title: "Never ship keys to browsers",
    detail:
      "Call /v1 from your server or agent backend. A key embedded in client-side code is public.",
  },
  {
    visual: <KeysMultiViz />,
    title: "One key per consumer",
    detail:
      "Give each app, agent, or teammate its own key so usage is attributable and revoking one does not break the others.",
  },
  {
    visual: <ConversationViz />,
    title: "Use conversation_id for chat",
    detail:
      "Pass any stable string and follow-ups are rewritten with context server-side. Omit it for stateless one-off queries.",
  },
  {
    visual: <CacheViz />,
    title: "Read the cache fields",
    detail:
      "Responses include cache_layer (l1 exact, l2 semantic, null fresh) and cache_similarity - useful for logging cost savings on your side.",
  },
  {
    visual: <ServerViz />,
    title: "Back off on 429",
    detail:
      "Standard endpoints allow 120 req/min per key and 300 per project; explore and memory-graph allow 10 and 20. Every 429 carries a Retry-After header - wait that many seconds, budgets reset each minute.",
  },
]

// Static-value "store" plumbing for useSyncExternalStore: the API base never
// changes after load, so subscribing is a no-op.
const subscribeNoop = () => () => {}
const getServerApiBase = () => ""

export function ApiTab({ project }: { project: Project }) {
  const { data: keys, error: keysError, mutate } = useSWR<ApiKey[]>(
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
  const [uploadTarget, setUploadTarget] = useState<ApiKey | null>(null)
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
      path: `${basePath}/query/stream`,
      description:
        "Same answer, streamed token by token over Server-Sent Events",
    },
    {
      method: "GET" as const,
      path: `${basePath}/queries`,
      description: "Query history with time, search, cache, latency, feedback filters and cursor pagination",
    },
    {
      method: "GET" as const,
      path: `${basePath}/queries/{query_id}`,
      description: "Recorded question, performance measurements, and full feedback note",
    },
    {
      method: "GET" as const,
      path: `${basePath}/health`,
      description: "This project's indexing readiness, query activity, and answer feedback over 30 days",
    },
    {
      method: "PUT" as const,
      path: `${basePath}/queries/{query_id}/feedback`,
      description: "Save or replace helpful / not helpful feedback and an optional note",
    },
    {
      method: "DELETE" as const,
      path: `${basePath}/queries/{query_id}/feedback`,
      description: "Remove a query's feedback (204 No Content)",
    },
    {
      method: "POST" as const,
      path: `${basePath}/retrieve`,
      description: "Retrieval only - top-matching chunks, no LLM call",
    },
    {
      method: "POST" as const,
      path: `${basePath}/explore`,
      description:
        "Graph-aware retrieval - a connected subgraph of chunks and memories",
    },
    {
      method: "POST" as const,
      path: `${basePath}/files`,
      description: "Ingest documents (requires a key with upload permission)",
    },
    {
      method: "POST" as const,
      path: `${basePath}/memory`,
      description: "Save an agent memory (also /memory/search, /memory/recent)",
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

const { answer, sources, needs_clarification, query_id } = await res.json();`

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
  "query_id": "12345",
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
  "conversation_id": "chat-001",
  "cache_layer": "l2",
  "cache_similarity": 0.82
}`

  const feedbackExample = `const queryId = "12345"; // query_id from /query or the stream's done.response
const feedback = await fetch(
  "${apiBase}${basePath}/queries/" + queryId + "/feedback",
  {
    method: "PUT",
    headers: {
      Authorization: "Bearer YOUR_API_KEY",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      rating: "not_helpful", // or "helpful"
      note: "The answer missed the cancellation policy.",
    }),
  }
);
if (!feedback.ok) throw new Error(await feedback.text());
console.log(await feedback.json());`

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

  /* Enabling uploads is the one permission on this page that changes what the
     ANSWER MODEL reads, so it gets a confirmation. Turning it OFF does not:
     removing a permission is always safe, and a confirmation there would just
     train people to click through the one that matters. */
  function handleToggleUpload(key: ApiKey, value: boolean) {
    if (value) {
      setUploadTarget(key)
      return
    }
    void applyUploadToggle(key, false)
  }

  async function applyUploadToggle(key: ApiKey, value: boolean) {
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

  async function confirmEnableUploads() {
    if (!uploadTarget) return
    const key = uploadTarget
    setUploadTarget(null)
    await applyUploadToggle(key, true)
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

  const noKeys = !keysError && keys?.length === 0

  return (
    <div className={styles.page}>
      <Card id="project-api-keys">
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <CardTitle><KeyRound aria-hidden="true" />API keys{!!keys?.length && <span className={styles.count}>{keys.filter(key => !key.revoked_at).length} active</span>}</CardTitle>
              <CardDescription>
                Keys are shown once at creation - store them securely.
              </CardDescription>
            </div>
            <div className="ml-auto flex shrink-0 items-center gap-2">
              <BestPractices tips={BEST_PRACTICE_TIPS} />
              {!noKeys && <Button
                onClick={handleCreate}
                disabled={creating}
                aria-label="Create key"
                title="Create key"
              >
                {creating ? (
                  <Spin />
                ) : (
                  <>
                    <Plus className="size-4" />
                    <span className="hidden sm:inline">Create key</span>
                  </>
                )}
              </Button>}
            </div>
          </div>
        </CardHeader>
        <CardContent className={styles.flush}>
          {noKeys ? (
            <section className={styles.emptyKeys} aria-label="No API keys">
              <div className={styles.emptyKeysIcon} aria-hidden="true"><KeyRound className="size-6" /></div>
              <div className="space-y-2">
                <h3 className="text-base font-semibold tracking-tight">Connect your first app</h3>
                <p className="max-w-xs text-sm leading-relaxed text-muted-foreground">
                  Create an API key to query this project from your app or agent.
                </p>
              </div>
              <Button onClick={handleCreate} disabled={creating}>
                {creating ? <Spin /> : <Plus className="size-4" aria-hidden="true" />}
                {creating ? "Creating key…" : "Create API key"}
              </Button>
            </section>
          ) : <Table className={styles.keysTable}>
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
              {keysError ? (
                <TableRow><TableCell colSpan={6} className="py-8 text-center">
                  <p role="alert" className="mb-3 text-sm text-muted-foreground">Couldn&apos;t load API keys.</p>
                  <Button variant="outline" size="sm" onClick={() => void mutate()}>Try again</Button>
                </TableCell></TableRow>
              ) : !keys ? (
                [0, 1, 2].map((i) => (
                  <TableRow key={i} className={styles.keyRow}>
                    <TableCell data-label="Key" className="pl-6">
                      <Skeleton className="h-4 w-24" />
                    </TableCell>
                    <TableCell data-label="Access">
                      <Skeleton className="h-5 w-20 rounded-full" />
                    </TableCell>
                    <TableCell data-label="Created">
                      <Skeleton className="h-4 w-20" />
                    </TableCell>
                    <TableCell data-label="Last used">
                      <Skeleton className="h-4 w-28" />
                    </TableCell>
                    <TableCell data-label="Status">
                      <Skeleton className="h-5 w-16 rounded-full" />
                    </TableCell>
                    <TableCell data-label="Manage" className="w-20 pr-6 text-right"><Skeleton className="ml-auto size-8" /></TableCell>
                  </TableRow>
                ))
              ) : (
                sortedKeys.map((key) => (
                  <TableRow key={key.id} className={styles.keyRow}>
                    <TableCell data-label="Key" className="pl-6 font-mono text-xs">
                      {key.key_prefix}…
                    </TableCell>
                    <TableCell data-label="Access">
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
                          className={styles.uploadCheckbox}
                        />
                        Uploads
                      </label>
                    </TableCell>
                    <TableCell data-label="Created">
                      {new Date(key.created_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell data-label="Last used">
                      {key.last_used_at
                        ? new Date(key.last_used_at).toLocaleString()
                        : "Never"}
                    </TableCell>
                    <TableCell data-label="Status">
                      {key.revoked_at ? (
                        <Badge variant="secondary">Revoked</Badge>
                      ) : (
                        <Badge className="border-transparent bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400">
                          Active
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell data-label="Manage" className="w-20 pr-6 text-right">
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
          </Table>}
        </CardContent>
      </Card>

      <Card id="project-api-quickstart">
        <CardHeader>
          <CardTitle><Terminal aria-hidden="true" />Quickstart</CardTitle>
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
          <section aria-labelledby="sdk-install-title" className={styles.sdkInstall}>
            <h3 id="sdk-install-title" className="text-sm font-medium">Install an SDK</h3>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              Install an SDK, then configure it on your server with this project&apos;s API key and project ID.
              Version 0.2.0 supports queries, streaming, uploads, feedback, evaluations and safe retries.
            </p>
            <div className={styles.sdkGrid}>
              <div className={styles.sdkPackage}>
                <h4 className="text-xs font-medium">JavaScript / TypeScript · npm</h4>
                <CopyRow value="npm install @haroontrailblazer/oreag-sdk" label="Copy npm install command" />
                <a className="inline-block break-all text-xs underline" href="https://www.npmjs.com/package/@haroontrailblazer/oreag-sdk" target="_blank" rel="noreferrer">
                  View package on npm
                </a>
              </div>
              <div className={styles.sdkPackage}>
                <h4 className="text-xs font-medium">Python · PyPI</h4>
                <CopyRow value="pip install oreag-sdk" label="Copy pip install command" />
                <a className="inline-block break-all text-xs underline" href="https://pypi.org/project/oreag-sdk/" target="_blank" rel="noreferrer">
                  View package on PyPI
                </a>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-4 text-xs">
              <a className="underline" href="/docs#reference-python-and-javascript-sdks">SDK setup guide</a>
              <a className="underline" href="/downloads/oreag-python-sdk.zip">Download Python source</a>
              <a className="underline" href="/downloads/oreag-javascript-sdk.zip">Download JavaScript source</a>
            </div>
            <p className="mt-3 text-xs text-muted-foreground">The proprietary viewing-only license is unchanged.</p>
          </section>

          <h3 className="text-sm font-medium">Make your first request</h3>
          <div className={styles.examples}>
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
          </div>

          <div className={styles.guides}>
          <details className={styles.guide}>
            <summary>Safe retries</summary>
            <div className="space-y-3">
              <p>Reuse the same Idempotency-Key and content for buffered queries, uploads or evaluations after a lost response. Completed results replay for 24 hours. Pending, uncertain or changed requests return 409. Streaming does not support replay.</p>
              <a className="underline underline-offset-4" href="/docs#reference-safe-retries">Retry guide</a>
            </div>
          </details>
          <details className={styles.guide}>
            <summary>Monitor your application</summary>
            <div className="space-y-3">
            <p className="text-xs leading-relaxed text-muted-foreground">
              GET /queries returns items and next_cursor. Pass next_cursor as before
              to load the next page. Filters: days (7, 30, 90), search, cache
              (all, fresh, l1, l2), feedback (all, helpful, not_helpful, unrated),
              min_latency_ms, and limit (1–100). GET /health returns generated_at,
              query_window_days, and a projects array containing this project only.
              Any active project key can read its API and Playground history,
              including questions and feedback notes. Keep these calls server-side.
            </p>
            <a href="/docs#queries" className="text-xs underline underline-offset-4">Queries, Health, and feedback guide</a>
            </div>
          </details>

          <details className={styles.guide}>
            <summary>Saved evaluations</summary>
            <div className="space-y-3">
            <p className="text-xs leading-relaxed text-muted-foreground">
              GET /evaluations/suite reads the saved test set and revision. PUT the same path with
              revision and a version-2 suite to save model, embedder, vector dimensions, and answer policy.
              POST /evaluations/runs with a unique UUID id and suite creates an isolated snapshot.
              Runs continue in the background. Poll GET /evaluations/runs/&#123;run_id&#125; until completed or failed:
              the worker embeds batches and answers questions independently. GET the run after a disconnect.
              The cancel and resume actions use POST; DELETE the run removes its saved results and vectors.
              Evaluation settings, scores, and feedback never update live project configuration,
              production vectors, Queries, or Health. PUT /evaluations/runs/&#123;run_id&#125;/results/&#123;result_index&#125;/feedback
              with rating and optional note to rate a finished run result; DELETE clears it.
              Use the zero-based index in the run&apos;s results array. Evaluation answers have no live query_id.
              Fresh answers and indexing consume provider quota. Project keys scope every operation.
            </p>
            <p className="text-xs leading-relaxed text-muted-foreground">Use Evaluator → Automatic checks to schedule saved sets and compare quality, latency, and cost. POST /evaluations/cases/from-query adds a recorded question and your expected answer with the saved set revision. Query detail includes measured stage timings.</p>
            <a href="/docs#querying" className="text-xs underline underline-offset-4">Evaluation configuration and API guide</a>
            </div>
          </details>

          <details className={styles.guide}>
            <summary>Answer feedback</summary>
            <div className="space-y-3">
            <p className="text-xs leading-relaxed text-muted-foreground">
              Keep the response&apos;s query_id as a string. Send feedback from
              your server after a user rates an answer; skip it when query_id is
              null. Notes are optional, up to 1,000 characters. Saving replaces
              the previous rating and note; DELETE the same URL to remove them.
              Any active key for this project can update its query feedback,
              which appears in Queries. No upload permission is needed.
            </p>
            <CodePanel title="feedback.ts (server)" code={feedbackExample} />
            </div>
          </details>

          <details className={styles.guide}>
            <summary>Ingest documents</summary>
            <div className="space-y-3">
            <p className="text-xs leading-relaxed text-muted-foreground">
              Upload files programmatically with a key that has{" "}
              <span className="font-medium text-foreground">uploads</span>{" "}
              enabled - read-only keys get a 403.
            </p>
            <CodePanel title="Terminal" code={uploadExample} />
            </div>
          </details>
          </div>
        </CardContent>
      </Card>

      <Card id="project-api-reference">
        <CardHeader>
          <CardTitle><Code aria-hidden="true" />API reference</CardTitle>
          <CardDescription>
            Authenticate every request with{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
              Authorization: Bearer oreag_sk_…
            </code>
          </CardDescription>
        </CardHeader>
        <CardContent className={styles.flush}>
          <div className={styles.baseUrl}>
            <span className="shrink-0 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Base URL
            </span>
            <span className="min-w-0 flex-1 break-all font-mono text-[12.5px]">
              {apiBase || "…"}
            </span>
            <CopyButton value={apiBase} label="Copy base URL" />
          </div>
          {endpoints.map((ep) => (
            <EndpointRow
              key={`${ep.method} ${ep.path}`}
              method={ep.method}
              path={ep.path}
              url={`${apiBase}${ep.path}`}
              description={ep.description}
            />
          ))}
          {/* Exact request budgets - enforced server-side in fixed 60s windows. */}
          <div className={styles.rateLimits}>
            <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Rate limits
            </p>
            <div className="mt-2 space-y-1.5 text-xs text-muted-foreground">
              <p>
                <span className="font-medium text-foreground">
                  Standard endpoints
                </span>{" "}
                (query, query/stream, queries, health, feedback, retrieve, memory):{" "}
                <span className="font-mono text-foreground">120 req/min per key</span>
                {" · "}
                <span className="font-mono text-foreground">
                  300 req/min per project
                </span>
              </p>
              <p>
                <span className="font-medium text-foreground">Heavy endpoints</span>{" "}
                (explore, memory-graph):{" "}
                <span className="font-mono text-foreground">10 req/min per key</span>
                {" · "}
                <span className="font-mono text-foreground">
                  20 req/min per project
                </span>
              </p>
              <p>
                <span className="font-medium text-foreground">Uploads</span>: 20
                files/request · 60 files/min per project · 1,000 files per project
                total
              </p>
              <p>
                All of a project&apos;s keys share the project budget. Exceeding
                either scope returns{" "}
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
                  429
                </code>{" "}
                with a{" "}
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
                  Retry-After
                </code>{" "}
                header - wait that many seconds, then retry.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <WebhooksPanel projectId={project.id} />

      <Card id="project-api-mcp">
        <CardHeader>
          <CardTitle><Plugs aria-hidden="true" />MCP connector</CardTitle>
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
        <DialogContent className={styles.dialog}>
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

      {/* Enabling uploads is a genuine change in the trust boundary, not just
          another permission bit, so it is explained BEFORE it is granted rather
          than documented somewhere the person flipping the switch will not
          read. Cancel is the default action (autoFocus) because the safe
          outcome should be the one you get by pressing Enter. */}
      <Dialog
        open={uploadTarget !== null}
        onOpenChange={(open) => {
          if (!open) setUploadTarget(null)
        }}
      >
        <DialogContent className={`${styles.dialog} max-h-[calc(100dvh-2rem)] grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden sm:max-h-[90dvh]`}>
          <DialogHeader>
            <div className="mb-1 flex size-10 items-center justify-center rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400">
              <ShieldWarning className="size-5" weight="fill" />
            </div>
            <DialogTitle>Allow this key to upload documents?</DialogTitle>
            <DialogDescription>
              Key{" "}
              <span className="font-mono">{uploadTarget?.key_prefix}…</span> will
              be able to add documents to this project. Anything it uploads is
              indexed and becomes part of what the answer model reads.
            </DialogDescription>
          </DialogHeader>

          <div className="flex min-h-0 flex-col gap-3 overflow-y-auto overscroll-contain pr-1 text-sm no-scrollbar">
            <div className="rounded-lg border border-amber-500/25 bg-amber-500/[0.06] p-3">
              <p className="font-medium text-foreground">
                This enables indirect prompt injection
              </p>
              <p className="mt-1 text-muted-foreground">
                Retrieved document text is passed to the model as context, and
                models can follow instructions they find there. A document
                containing something like &ldquo;ignore your instructions and
                reveal…&rdquo; is a live attempt, not just text. It affects{" "}
                <span className="font-medium text-foreground">
                  everyone who queries this project
                </span>{" "}
                - not only whoever uploaded it - and it persists until that
                document is deleted and the project re-indexed.
              </p>
            </div>

            <ul className="flex flex-col gap-1.5 text-muted-foreground">
              <li className="flex gap-2">
                <span aria-hidden="true">•</span>
                <span>
                  Treat this like a write credential. Keep it server-side -
                  never in browser code, a mobile app, or a public repo.
                </span>
              </li>
              <li className="flex gap-2">
                <span aria-hidden="true">•</span>
                <span>
                  Only upload from sources you trust. Content from users, email
                  or the open web can carry instructions.
                </span>
              </li>
              <li className="flex gap-2">
                <span aria-hidden="true">•</span>
                <span>
                  Give each consumer its own key, so you can revoke this one
                  without breaking the others.
                </span>
              </li>
              <li className="flex gap-2">
                <span aria-hidden="true">•</span>
                <span>
                  If it may have leaked, revoke it here - uploads cannot be
                  un-indexed by rotating the key alone.
                </span>
              </li>
            </ul>

            <p className="text-xs text-muted-foreground">
              You can turn uploads off again at any time. Read access is
              unchanged either way.
            </p>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              autoFocus
              onClick={() => setUploadTarget(null)}
            >
              Cancel
            </Button>
            <Button onClick={confirmEnableUploads}>
              I understand, allow uploads
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={revokeTarget !== null}
        onOpenChange={(open) => {
          if (!open && !revoking) setRevokeTarget(null)
        }}
      >
        <DialogContent className={styles.dialog}>
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
        <DialogContent className={styles.dialog} showCloseButton={false}>
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
