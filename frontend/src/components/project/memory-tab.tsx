"use client"

import { Brain, MagnifyingGlass as Search } from "@phosphor-icons/react/dist/ssr"
import { useState } from "react"
import { toast } from "@/lib/toast"
import useSWR from "swr"

import { Badge } from "@/components/ui/badge"
import { BestPractices } from "@/components/ui/best-practices"
import {
  MemoryViz,
  PinViz,
  RetrievalViz,
  TagViz,
  VectorViz,
} from "@/components/ui/best-practice-visuals"
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
import { Spin } from "@/components/ui/loader"
import { Skeleton } from "@/components/ui/skeleton"
import { api, fetcher } from "@/lib/api"
import type { Memory, Project } from "@/lib/types"

const BEST_PRACTICE_TIPS = [
  {
    visual: <MemoryViz />,
    title: "One fact per memory",
    detail:
      "Short, self-contained memories retrieve better than long notes - they embed into a single clean vector, like a good chunk.",
  },
  {
    visual: <TagViz />,
    title: "Tag for humans, not for search",
    detail:
      "Search is semantic (meaning-based). Tags help YOU filter and audit this list - they do not boost retrieval.",
  },
  {
    visual: <PinViz />,
    title: "Pin what must persist",
    detail:
      "Pinned memories are protected from bulk cleanup - use pins for decisions and constraints agents must never lose.",
  },
  {
    visual: <RetrievalViz />,
    title: "Memories join RAG answers",
    detail:
      "Relevant memories are blended into /query answers alongside document chunks (shown as memory sources), and they live in the same vector space as your files.",
  },
  {
    visual: <VectorViz />,
    title: "Unembedded memories are invisible",
    detail:
      "A memory saved while no embedding key was available has no vector and cannot be searched - re-save it (or change models) to embed it.",
  },
]

export function MemoryTab({ project }: { project: Project }) {
  const { data: memories, error, mutate } = useSWR<Memory[]>(
    `/api/projects/${project.id}/memory`,
    fetcher
  )
  const [filter, setFilter] = useState("")

  const loading = memories === undefined && !error
  const all = memories ?? []
  const term = filter.trim().toLowerCase()
  const shown = all.filter((m) => m.content.toLowerCase().includes(term))

  // Deleting a memory is irreversible and there is no undo, so it goes through
  // a confirmation step exactly like deleting a file does. Before this, a
  // single stray click destroyed a memory outright - and because the old
  // handler showed no feedback at all, people clicked again and destroyed a
  // second one without ever seeing the first go.
  const [deleteTarget, setDeleteTarget] = useState<Memory | null>(null)
  const [deleting, setDeleting] = useState(false)

  async function confirmDelete() {
    const target = deleteTarget
    if (!target || deleting) return
    const id = target.id
    setDeleting(true)
    try {
      // OPTIMISTIC. This used to be `await api(...); mutate()`, which left the
      // row sitting on screen through BOTH round trips - the DELETE and then
      // the refetch - with no spinner, no disabled button and no toast. It read
      // as a dead click, and clicking again just queued another DELETE.
      //
      // The row now vanishes on the same tick, and `revalidate: false` skips
      // the follow-up GET entirely: removing one known row from a list is
      // deterministic, so there is nothing to ask the server about.
      // rollbackOnError puts it back if the request actually fails.
      await mutate(
        async () => {
          await api(`/api/projects/${project.id}/memory/${id}`, {
            method: "DELETE",
          })
          return (memories ?? []).filter((m) => m.id !== id)
        },
        {
          optimisticData: (current?: Memory[]) =>
            (current ?? []).filter((m) => m.id !== id),
          rollbackOnError: true,
          populateCache: true,
          revalidate: false,
        }
      )
      toast.success("Memory deleted")
      setDeleteTarget(null)
    } catch (err) {
      // The row is already back on screen via rollbackOnError, so the toast is
      // the only thing that has to explain what happened. The dialog stays OPEN
      // on failure - closing it would imply the delete had worked.
      toast.error(err instanceof Error ? err.message : "Failed to delete")
    } finally {
      setDeleting(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <CardTitle>Agent memory</CardTitle>
            <CardDescription>
              Notes your connected agents (via the MCP server) have saved for
              this project.
            </CardDescription>
          </div>
          <BestPractices className="ml-auto" tips={BEST_PRACTICE_TIPS} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            placeholder="Filter memories"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            disabled={all.length === 0 && !loading}
            className="pl-8"
          />
        </div>
        {error ? (
          <p className="text-sm text-destructive">
            Could not load memories: {error.message}
          </p>
        ) : loading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-16 rounded-md" />
            ))}
          </div>
        ) : all.length === 0 ? (
          <div className="py-10 text-center">
            <div className="mx-auto mb-3 flex size-11 items-center justify-center rounded-xl bg-muted text-muted-foreground">
              <Brain className="size-5" />
            </div>
            <p className="text-sm font-medium">No memories yet</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Notes your connected agents save will appear here.
            </p>
          </div>
        ) : shown.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No memories match &ldquo;{filter.trim()}&rdquo;.
          </p>
        ) : (
          shown.map((m) => (
            <div
              key={m.id}
              className="flex items-start justify-between gap-3 rounded-md border p-3"
            >
              <div className="min-w-0 space-y-1">
                <p className="text-sm">{m.content}</p>
                <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                  {m.pinned && <Badge variant="secondary">pinned</Badge>}
                  {m.tags.map((t) => (
                    <Badge key={t} variant="outline">
                      {t}
                    </Badge>
                  ))}
                  <span>{m.source}</span>
                  <span>· {new Date(m.created_at).toLocaleDateString()}</span>
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setDeleteTarget(m)}
                className="shrink-0"
              >
                Delete
              </Button>
            </div>
          ))
        )}
      </CardContent>

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          // Not dismissable mid-request - closing under a delete would leave
          // the user unsure whether it went through.
          if (!open && !deleting) setDeleteTarget(null)
        }}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete this memory?</DialogTitle>
            <DialogDescription asChild>
              <div>
                {/* Quote it back. Memories have no filename to identify them
                    by, so the text IS the identifier - without it the dialog
                    asks you to confirm deleting something unnamed. */}
                <span className="line-clamp-4 italic text-foreground">
                  &ldquo;{deleteTarget?.content}&rdquo;
                </span>
                <span className="mt-2 block">
                  Agents will no longer recall this. It can&apos;t be undone.
                </span>
              </div>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={deleting}
              onClick={() => setDeleteTarget(null)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={deleting}
              onClick={confirmDelete}
            >
              {deleting ? <Spin /> : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
