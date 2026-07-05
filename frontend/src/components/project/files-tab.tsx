"use client"

import {
  WarningCircle as AlertCircle,
  CheckCircle as CheckCircle2,
  Clock as Clock3,
  FileText,
  CircleNotch as Loader2,
  DotsThree as MoreHorizontal,
  ArrowCounterClockwise as RotateCcw,
  Trash as Trash2,
} from "@phosphor-icons/react/dist/ssr"
import { useEffect, useRef, useState } from "react"
import { toast } from "@/lib/toast"
import useSWR from "swr"

import { AddFilesDialog } from "@/components/project/add-files-dialog"
import { BestPractices } from "@/components/ui/best-practices"
import { SquaresLoader } from "@/components/ui/squares-loader"
import { BoxLoader } from "@/components/ui/box-loader"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
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
import { api, fetcher } from "@/lib/api"
import type { FileRecord, Project } from "@/lib/types"
import { cn } from "@/lib/utils"

function formatSize(bytes: number | null): string {
  if (bytes == null) return "-"
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const FILE_STATUS = {
  pending: {
    label: "Queued",
    icon: Clock3,
    className:
      "border-transparent bg-transparent text-amber-700 dark:text-amber-400",
  },
  processing: {
    label: "Indexing",
    icon: Loader2,
    className:
      "border-transparent bg-transparent text-sky-600 dark:text-sky-400",
  },
  indexed: {
    label: "Indexed",
    icon: CheckCircle2,
    className: "border-transparent bg-transparent text-muted-foreground",
  },
  failed: {
    label: "Needs review",
    icon: AlertCircle,
    className:
      "border-transparent bg-transparent text-red-700 dark:text-red-400",
  },
} satisfies Record<
  FileRecord["status"],
  {
    label: string
    icon: React.ComponentType<{ className?: string }>
    className: string
  }
>

/* Skeleton text lines drawn inside each mini document card. */
const CARD_LINES = [
  { x2: 96, accent: false },
  { x2: 99, accent: true },
  { x2: 94, accent: false },
  { x2: 90, accent: false },
]

/** Loader matching the Lottielab "Data | Bundling" reference: document cards
 * slide in and stack into a deck while uploads are chunked and embedded.
 * Pure SVG/SMIL in the app palette - no animation runtime. */
function BundlingLoader() {
  return (
    // viewBox is cropped to the deck itself - no slide runway - so the
    // artwork's left edge sits exactly where the file icons below start; the
    // incoming card materialises through the left clip edge onto the stack.
    <svg viewBox="76 0 36 48" className="h-9 w-auto shrink-0" aria-hidden="true">
      {/* The deck: cards already bundled, peeking out behind. */}
      {[6, 3].map((offset, i) => (
        <rect
          key={i}
          x={78 + offset}
          y="7"
          width="26"
          height="34"
          rx="4"
          strokeWidth="1.2"
          className="fill-background stroke-border"
          opacity={0.55 + i * 0.25}
        />
      ))}
      {/* The incoming document: fades in sliding through the clip edge. */}
      <g>
        <animateTransform
          attributeName="transform"
          type="translate"
          values="-22 0; 0 0; 0 0"
          keyTimes="0; 0.55; 1"
          dur="1.8s"
          repeatCount="indefinite"
        />
        <animate
          attributeName="opacity"
          values="0; 1; 1; 1"
          keyTimes="0; 0.3; 0.9; 1"
          dur="1.8s"
          repeatCount="indefinite"
        />
        <rect
          x="78"
          y="7"
          width="26"
          height="34"
          rx="4"
          strokeWidth="1.4"
          className="fill-background stroke-border"
        />
        {CARD_LINES.map((line, i) => (
          <line
            key={i}
            x1="83"
            y1={15 + i * 6}
            x2={line.x2}
            y2={15 + i * 6}
            strokeWidth="2"
            strokeLinecap="round"
            className={
              line.accent
                ? "stroke-zinc-700 dark:stroke-zinc-100"
                : "stroke-muted-foreground/35"
            }
          />
        ))}
      </g>
    </svg>
  )
}

function FileStatus({ status }: { status: FileRecord["status"] }) {
  const config = FILE_STATUS[status]
  const Icon = config.icon

  return (
    <span
      aria-label={config.label}
      title={config.label}
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-full border",
        config.className
      )}
    >
      {status === "processing" ? (
        <SquaresLoader size={3} />
      ) : (
        <Icon className="size-3.5" />
      )}
    </span>
  )
}

export function FilesTab({
  project,
  onChanged,
  selectedFileId,
  focusToken = 0,
}: {
  project: Project
  onChanged: () => void
  selectedFileId?: string | null
  // Bumped by the page when "View file" targets the SAME file again, so the
  // scroll + highlight re-run even though selectedFileId didn't change.
  focusToken?: number
}) {
  const [highlightId, setHighlightId] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<FileRecord | null>(null)
  const [deleting, setDeleting] = useState(false)
  const deleteDone = useRef(false)

  const { data: files, mutate } = useSWR<FileRecord[]>(
    `/api/projects/${project.id}/files`,
    fetcher,
    {
      refreshInterval: (latest) =>
        latest?.some((f) => f.status === "pending" || f.status === "processing")
          ? 3000
          : 0,
      onSuccess: () => onChanged(),
    }
  )

  // Scroll to and briefly highlight the file targeted by a ?file=<id> link or
  // the Visualize tab's "View file" button (focusToken re-arms same-file hits).
  useEffect(() => {
    if (!selectedFileId || !files) return
    const el = document.getElementById(`file-${selectedFileId}`)
    if (!el) return
    el.scrollIntoView({ behavior: "smooth", block: "center" })
    // Defer the highlight to the next frame so the effect body doesn't set
    // state synchronously (react-hooks/set-state-in-effect).
    const raf = requestAnimationFrame(() => setHighlightId(selectedFileId))
    const timer = setTimeout(() => setHighlightId(null), 2200)
    return () => {
      cancelAnimationFrame(raf)
      clearTimeout(timer)
    }
  }, [selectedFileId, files, focusToken])

  async function confirmDelete() {
    if (!deleteTarget) return
    deleteDone.current = false
    setDeleting(true)
    try {
      await api(`/api/projects/${project.id}/files/${deleteTarget.id}`, {
        method: "DELETE",
      })
      // Don't close yet - let the loader finish its current animation cycle.
      deleteDone.current = true
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed")
      setDeleting(false)
    }
  }

  // Called at each loader animation cycle; closes once the delete has finished.
  function handleDeleteCycle() {
    if (!deleteDone.current) return
    deleteDone.current = false
    toast.success(`${deleteTarget?.filename} deleted`)
    setDeleteTarget(null)
    setDeleting(false)
    mutate()
    onChanged()
  }

  async function handleRetry(file: FileRecord) {
    try {
      await api(`/api/projects/${project.id}/files/${file.id}/retry`, {
        method: "POST",
      })
      mutate()
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Retry failed")
    }
  }

  async function handleReindexAll() {
    try {
      await api(`/api/projects/${project.id}/reindex`, {
        method: "POST",
        body: JSON.stringify({}),
      })
      toast.success("Re-indexing started")
      mutate()
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Re-index failed")
    }
  }

  async function handleRetryFailed() {
    const failed = files?.filter((file) => file.status === "failed") ?? []
    if (failed.length === 0) {
      toast.info("No failed files to retry")
      return
    }
    try {
      await Promise.all(
        failed.map((file) =>
          api(`/api/projects/${project.id}/files/${file.id}/retry`, {
            method: "POST",
          })
        )
      )
      toast.success(`Retrying ${failed.length} failed file${failed.length === 1 ? "" : "s"}`)
      mutate()
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Retry failed")
    }
  }

  const fileCount = files?.length ?? 0
  const totalChunks = files?.reduce((sum, file) => sum + file.chunk_count, 0) ?? 0
  // Files still being chunked/embedded - drives the bundling banner that shows
  // from the moment the upload dialog closes until indexing settles.
  const inFlight =
    files?.filter(
      (file) => file.status === "pending" || file.status === "processing"
    ).length ?? 0

  return (
    <Card className="gap-0 overflow-hidden p-0">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4">
        <div className="space-y-0.5">
          <h3 className="text-sm font-semibold">Files</h3>
          <p className="text-xs text-muted-foreground">
            {fileCount === 0
              ? "No documents yet"
              : `${fileCount} document${fileCount === 1 ? "" : "s"} · ${totalChunks} chunk${
                  totalChunks === 1 ? "" : "s"
                }`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <BestPractices
            tips={[
              {
                title: "Mind the 50 MB limit",
                detail:
                  "About 30 file types are supported (PDF, DOCX, PPTX, XLSX, HTML, images, audio...). Everything is converted to Markdown before chunking, so clean source documents index best.",
              },
              {
                title: "Chunk size: start at 1000 / 200",
                detail:
                  "The defaults suit most documents. Use smaller chunks (300-500) for FAQs and short facts, larger (1500-2000) for narrative or legal text where context matters. Overlap of ~20% protects facts that straddle a cut.",
              },
              {
                title: "Per-file overrides are free",
                detail:
                  "Chunking set in the upload dialog applies only to those files - no need to reindex the whole project to experiment.",
              },
              {
                title: "Retry beats re-upload",
                detail:
                  "A failed file keeps its stored original - fix the cause (usually a provider key) and hit Retry instead of uploading again.",
              },
              {
                title: "Re-indexing costs embeddings",
                detail:
                  "Changing the project's chunking or embedding model re-embeds every chunk. Exception: shrinking the same Matryoshka model's dimensions is instant and free.",
              },
            ]}
          />
          <AddFilesDialog
            project={project}
            onUploaded={() => {
              mutate()
              onChanged()
            }}
          />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="icon" aria-label="File actions">
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={handleRetryFailed}>
                <RotateCcw className="size-4" />
                Retry failed files
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={handleReindexAll}>
                <RotateCcw className="size-4" />
                Re-index all files
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {inFlight > 0 && (
        <div className="flex items-center gap-4 border-b bg-muted/30 px-6 py-2.5">
          {/* size-9 slot mirrors the rows' icon box, so the artwork's left
              edge AND the text column line up with the file rows below. */}
          <span className="flex size-9 shrink-0 items-center">
            <BundlingLoader />
          </span>
          <div className="min-w-0">
            <p className="font-mono text-xs font-medium text-zinc-700 dark:text-zinc-100">
              Bundling...
            </p>
            <p className="text-[11px] text-muted-foreground">
              {fileCount - inFlight} of {fileCount} processed - chunking &
              embedding into the knowledge base
            </p>
          </div>
        </div>
      )}

      {fileCount === 0 ? (
        <div className="px-6 py-16 text-center">
          <div className="mx-auto mb-3 flex size-11 items-center justify-center rounded-xl bg-muted text-muted-foreground">
            <FileText className="size-5" />
          </div>
          <p className="text-sm font-medium">No files yet</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Add documents to build this knowledge base.
          </p>
        </div>
      ) : (
        // Desktop: cap the list to the viewport so the page itself never
        // scrolls - only the rows do, under the pinned "Files" header bar
        // above. No min-height: the card shrinks to fit when files are
        // deleted. Phones keep natural page flow.
        <div className="md:max-h-[calc(100dvh-16.5rem)] md:overflow-y-auto">
        <ul className="divide-y">
          {(files ?? []).map((file) => {
            const meta = [
              (file.source_extension ?? "").replace(".", "").toUpperCase() || null,
              formatSize(file.size_bytes),
              file.page_count != null
                ? `${file.page_count} page${file.page_count === 1 ? "" : "s"}`
                : null,
              `${file.chunk_count} chunk${file.chunk_count === 1 ? "" : "s"}`,
            ]
              .filter(Boolean)
              .join(" · ")
            return (
              <li
                key={file.id}
                id={`file-${file.id}`}
                className={cn(
                  "flex scroll-mt-24 items-center gap-4 px-6 py-3.5 transition-colors hover:bg-muted/40",
                  highlightId === file.id &&
                    "bg-primary/10 ring-1 ring-inset ring-primary/30"
                )}
              >
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                  <FileText className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">
                    {file.filename}
                  </div>
                  <div className="truncate text-xs text-muted-foreground">
                    {meta}
                  </div>
                  {file.error && (
                    <p className="mt-0.5 truncate text-xs text-destructive">
                      {file.error}
                    </p>
                  )}
                  {file.conversion_error &&
                    file.conversion_error !== file.error && (
                      <p className="mt-0.5 truncate text-xs text-destructive">
                        {file.conversion_error}
                      </p>
                    )}
                </div>
                <FileStatus status={file.status} />
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`${file.filename} actions`}
                    >
                      <MoreHorizontal className="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      disabled={file.status === "processing"}
                      onSelect={() => handleRetry(file)}
                    >
                      <RotateCcw className="size-4" />
                      {file.status === "failed" ? "Retry indexing" : "Re-index file"}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      variant="destructive"
                      onSelect={() => setDeleteTarget(file)}
                    >
                      <Trash2 className="size-4" />
                      Delete file
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </li>
            )
          })}
        </ul>
        </div>
      )}

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open && !deleting) setDeleteTarget(null)
        }}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete this file?</DialogTitle>
            {!deleting && (
              <DialogDescription>
                <span className="font-medium text-foreground">
                  {deleteTarget?.filename}
                </span>{" "}
                and its indexed chunks will be permanently deleted from this
                project. This can&apos;t be undone.
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
    </Card>
  )
}
