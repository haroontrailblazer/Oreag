"use client"

import {
  BrainIcon as Brain,
  CaretDownIcon as CaretDown,
  CaretUpIcon as CaretUp,
  MagnifyingGlassIcon as Search,
  TrashIcon as Trash,
} from "@phosphor-icons/react/dist/ssr"
import { useEffect, useRef, useState } from "react"
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

/** A long memory stays scannable until its reader asks for the full text.
 * Measuring the rendered paragraph instead of guessing from character count
 * keeps the control accurate across desktop, mobile and manual line breaks. */
function MemoryBody({ memory }: { memory: Memory }) {
  const contentRef = useRef<HTMLParagraphElement | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [canExpand, setCanExpand] = useState(false)

  useEffect(() => {
    if (expanded) return
    const content = contentRef.current
    if (!content) return

    const measure = () => {
      setCanExpand(content.scrollHeight > content.clientHeight + 1)
    }
    measure()

    const observer = new ResizeObserver(measure)
    observer.observe(content)
    return () => observer.disconnect()
  }, [expanded, memory.content])

  const contentId = `memory-${memory.id}-content`

  return (
    <div className="space-y-2">
      <p
        ref={contentRef}
        id={contentId}
        className={`max-w-[80ch] whitespace-pre-wrap break-words text-[0.9375rem] leading-6 text-foreground/90 ${expanded ? "" : "line-clamp-4"}`}
      >
        {memory.content}
      </p>
      {canExpand && (
        <Button
          type="button"
          variant="link"
          size="xs"
          aria-expanded={expanded}
          aria-controls={contentId}
          onClick={() => setExpanded((open) => !open)}
          className="h-auto gap-1 p-0 text-xs"
        >
          {expanded ? "Show less" : "Show more"}
          {expanded ? (
            <CaretUp className="size-3" />
          ) : (
            <CaretDown className="size-3" />
          )}
        </Button>
      )}
    </div>
  )
}

function MemoryRow({
  memory,
  onDelete,
}: {
  memory: Memory
  onDelete: (memory: Memory) => void
}) {
  return (
    <article className="group px-6 py-4 transition-colors hover:bg-muted/30 [contain-intrinsic-size:auto_9rem] [content-visibility:auto]">
      <div className="flex items-start gap-4">
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            {memory.pinned && <Badge variant="secondary">Pinned</Badge>}
            <span className="font-medium text-foreground/70">
              {memory.source}
            </span>
            <span aria-hidden="true">·</span>
            <time dateTime={memory.created_at}>
              {new Date(memory.created_at).toLocaleDateString()}
            </time>
          </div>

          <MemoryBody memory={memory} />

          {memory.tags.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              {memory.tags.map((tag) => (
                <Badge key={tag} variant="outline">
                  {tag}
                </Badge>
              ))}
            </div>
          )}
        </div>

        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Delete memory"
          title="Delete memory"
          onClick={() => onDelete(memory)}
          className="-mr-1 shrink-0 text-muted-foreground opacity-70 hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
        >
          <Trash className="size-4" />
        </Button>
      </div>
    </article>
  )
}

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
    // max-h-full, NOT h-full: the card is as tall as its memories and no
    // taller, up to the viewport. Two memories should render a small card, not
    // a full-height one with a field of empty space under them. Past that
    // point the list below scrolls while the title and filter stay pinned.
    //
    // Unprefixed so phones behave identically - it resolves there because the
    // project page is already a definite-height frame on mobile
    // (h-[calc(100dvh-6.25rem)] in projects/[id]/page.tsx). Derived from that
    // rather than carrying its own calc, because a hardcoded number goes wrong
    // the moment anything above it changes height.
    <Card className="flex max-h-full min-h-0 flex-col">
      <CardHeader className="shrink-0">
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
      {/* The filter belongs to the pinned frame, not the scrolling list -
          scrolling away the box you are filtering with is worse than useless
          on a long list. */}
      <CardContent className="shrink-0 pb-3">
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
      </CardContent>
      {/* No flex-1: that would grow the list to fill the card and put the
          empty space back. Natural height, shrinking (and so scrolling) only
          once the card reaches its cap - min-h-0 is what permits the shrink. */}
      <CardContent className="min-h-0 overflow-y-auto px-0">
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
          <div className="divide-y border-y">
            {shown.map((memory) => (
              <MemoryRow
                key={memory.id}
                memory={memory}
                onDelete={setDeleteTarget}
              />
            ))}
          </div>
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
