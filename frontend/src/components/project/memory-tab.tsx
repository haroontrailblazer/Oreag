"use client"

import {
  BrainIcon as Brain,
  CircleDashedIcon as CircleDashed,
  ClockIcon as Clock,
  CodeIcon as Code,
  MagnifyingGlassIcon as Search,
  PlugsConnectedIcon as PlugsConnected,
  PushPinIcon as PushPin,
  RobotIcon as Robot,
  TagIcon,
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
import { api, fetcher, isSessionExpired } from "@/lib/api"
import { cn } from "@/lib/utils"
import type { Memory, Project } from "@/lib/types"

const BEST_PRACTICE_TIPS = [
  {
    visual: <MemoryViz />,
    title: "One fact per memory",
    detail:
      "One idea per memory still retrieves best. Long ones are now split into pieces with their own vectors, so they stay findable - but a focused memory needs no splitting at all.",
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
      "Pinned memories come first in the recent list - what an agent sees at the start of a session before it searches. Pinning does not boost search ranking.",
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
    <div className="flex flex-col gap-2">
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
          className="h-auto self-start p-0"
        >
          {expanded ? "Show less" : "Show more"}
        </Button>
      )}
    </div>
  )
}

/* Who wrote this memory, as one glyph.
   Colour-coded so a long list separates by origin without reading a word.
   Unknown sources fall through to a neutral dashed circle rather than being
   forced into a wrong icon - a memory from a source this build has never heard
   of should look unfamiliar, not mislabelled. */
const SOURCE_MARKS: Record<
  string,
  { icon: typeof Robot; label: string; className: string }
> = {
  mcp: {
    icon: PlugsConnected,
    label: "Saved by a connected agent (MCP)",
    className: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
  },
  api: {
    icon: Code,
    label: "Saved through the public API",
    className: "bg-sky-500/10 text-sky-600 dark:text-sky-400",
  },
  agent: {
    icon: Robot,
    label: "Saved by an agent",
    className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  },
}

function SourceMark({ source }: { source: string }) {
  const mark = SOURCE_MARKS[source] ?? {
    icon: CircleDashed,
    label: `Saved by ${source}`,
    className: "bg-muted text-muted-foreground",
  }
  const Icon = mark.icon
  return (
    <span
      title={mark.label}
      className={cn(
        "mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-none border border-current/10 shadow-xs",
        mark.className
      )}
    >
      <Icon className="size-4.5" />
      {/* The title attribute is a hover affordance only - screen readers need
          the source named in the accessibility tree too. */}
      <span className="sr-only">{mark.label}</span>
    </span>
  )
}

function MemoryRow({
  memory,
  onDelete,
  onTogglePin,
  pinBusy,
}: {
  memory: Memory
  onDelete: (memory: Memory) => void
  onTogglePin: (memory: Memory) => void
  pinBusy: boolean
}) {
  return (
    <article
      className={cn(
        "group rounded-none border bg-card px-3 py-4 shadow-xs transition-[background-color,border-color,box-shadow] hover:border-foreground/15 hover:bg-accent/25 hover:shadow-sm sm:px-4 [contain-intrinsic-size:auto_9rem] [content-visibility:auto]",
        memory.pinned && "border-amber-500/25 bg-amber-500/[0.035]"
      )}
    >
      <div className="flex items-start gap-3 sm:gap-4">
        {/* Source as a single glyph in a tinted tile. It replaces the raw
            string ("mcp", "api", "agent"), which was jargon rendered at the
            most prominent point of the row - and doubles as the visual anchor
            that makes a long list scannable by origin at a glance. */}
        <SourceMark source={memory.source} />

        <div className="min-w-0 flex-1">
          <MemoryBody memory={memory} />

          {/* Metadata BELOW the content, not above it. The text is what the
              user is looking for; provenance is what they check afterwards. */}
          {/* No pin indicator here. The toggle on the right already shows the
              state - filled and amber when pinned - so a second amber pin on
              the same row was the SAME fact drawn twice, and the read-only one
              invited clicks that did nothing. State and its control belong in
              one place. Screen readers get it from aria-pressed on the button,
              which is why nothing was lost with the sr-only label. */}
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-border/60 pt-2.5 text-xs text-muted-foreground">
            <span
              className="inline-flex items-center gap-1"
              title={`Created ${new Date(memory.created_at).toLocaleString()}`}
            >
              <Clock className="size-3.5" />
              <time dateTime={memory.created_at}>
                {new Date(memory.created_at).toLocaleDateString(undefined, {
                  day: "numeric",
                  month: "short",
                })}
              </time>
            </span>

            {/* Tags keep their words - they are arbitrary user strings, so no
                icon can stand in for them. One Tag glyph labels the group
                instead, which is the honest use of an icon here. */}
            {memory.tags.length > 0 && (
              <span className="inline-flex min-w-0 flex-wrap items-center gap-1.5">
                <TagIcon className="size-3.5 shrink-0" aria-hidden="true" />
                {memory.tags.map((tag) => (
                  <Badge key={tag} variant="outline" className="font-normal">
                    {tag}
                  </Badge>
                ))}
              </span>
            )}
          </div>
        </div>

        {/* Pin toggle sits with delete, not in the metadata strip: both are
            actions on the row, and the strip is read-only information. Always
            rendered (not hover-only) so a pinned memory can be UNpinned on
            touch, where there is no hover. */}
        <div className="flex shrink-0 items-center gap-0.5 rounded-none border bg-background/70 p-0.5 shadow-xs">
          <Button
            variant="ghost"
            size="icon-sm"
            disabled={pinBusy}
            aria-pressed={memory.pinned}
            aria-label={memory.pinned ? "Unpin memory" : "Pin memory"}
            title={memory.pinned ? "Unpin" : "Pin to the top of the list"}
            onClick={() => onTogglePin(memory)}
            className={cn(
              "shrink-0",
              memory.pinned
                ? "bg-amber-500/10 text-amber-600 dark:text-amber-400"
                : "text-muted-foreground opacity-70 hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
            )}
          >
            {pinBusy ? (
              <Spin />
            ) : (
              <PushPin
                weight={memory.pinned ? "fill" : "regular"}
                className="size-4"
              />
            )}
          </Button>

          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Delete memory"
            title="Delete memory"
            onClick={() => onDelete(memory)}
            className="shrink-0 text-muted-foreground opacity-70 hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
          >
            <Trash className="size-4" />
          </Button>
        </div>
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
  const [pinning, setPinning] = useState<number | null>(null)

  async function togglePin(memory: Memory) {
    if (pinning !== null) return
    const next = !memory.pinned
    setPinning(memory.id)
    try {
      // Optimistic, and RE-SORTED locally: pinned rows sort to the top server
      // side, so flipping the flag without re-ordering would leave the row
      // sitting where it was until the next fetch - the pin would look applied
      // but the list would disagree with itself.
      const reorder = (list: Memory[] = []) =>
        list
          .map((m) => (m.id === memory.id ? { ...m, pinned: next } : m))
          .sort((a, b) =>
            a.pinned === b.pinned
              ? +new Date(b.created_at) - +new Date(a.created_at)
              : a.pinned
                ? -1
                : 1
          )
      await mutate(
        async () => {
          await api(`/api/projects/${project.id}/memory/${memory.id}`, {
            method: "PATCH",
            body: JSON.stringify({ pinned: next }),
          })
          return reorder(memories)
        },
        {
          optimisticData: reorder,
          rollbackOnError: true,
          populateCache: true,
          revalidate: false,
        }
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not update pin")
    } finally {
      setPinning(null)
    }
  }

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
    <Card className="flex max-h-full min-h-0 flex-col gap-0 overflow-hidden p-0">
      <CardHeader className="shrink-0 px-5 pb-3 pt-4">
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
      <CardContent className="shrink-0 border-b px-5 pb-4">
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
        {/* Signed out is not a load failure - see lib/api.ts isSessionExpired. */}
        {error && !isSessionExpired(error) ? (
          <p className="text-sm text-destructive">
            Could not load memories: {error.message}
          </p>
        ) : loading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-16 rounded-none" />
            ))}
          </div>
        ) : all.length === 0 ? (
          <div className="py-10 text-center">
            <div className="mx-auto mb-3 flex size-11 items-center justify-center rounded-none bg-muted text-muted-foreground">
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
          <div className="flex flex-col gap-2 bg-muted/20 p-2 sm:p-3">
            {shown.map((memory) => (
              <MemoryRow
                key={memory.id}
                memory={memory}
                onDelete={setDeleteTarget}
                onTogglePin={togglePin}
                pinBusy={pinning === memory.id}
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
