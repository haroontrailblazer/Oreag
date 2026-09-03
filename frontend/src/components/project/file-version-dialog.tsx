"use client"

import {
  DownloadSimpleIcon as Download,
  FileTextIcon as FileText,
  GitBranchIcon as GitBranch,
} from "@phosphor-icons/react/dist/ssr"
import { useMemo, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { api, downloadFile } from "@/lib/api"
import { toast } from "@/lib/toast"
import type { FileRecord, Project } from "@/lib/types"

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

const LEGAL_STATUSES = [
  { value: "in_force", label: "In force" },
  { value: "amended", label: "Amended" },
  { value: "repealed", label: "Repealed" },
  { value: "draft", label: "Draft" },
  { value: "unknown", label: "Unknown" },
] as const

/** The lineage key. A null document_id means the file is its own document. */
export function lineageOf(file: FileRecord): string {
  return file.document_id ?? file.id
}

/** Newest edition first, undated last - `in_force_from` is optional. */
function byRecency(a: FileRecord, b: FileRecord): number {
  if (a.in_force_from === b.in_force_from) return 0
  if (!a.in_force_from) return 1
  if (!b.in_force_from) return -1
  return a.in_force_from < b.in_force_from ? 1 : -1
}

/**
 * Confirm what an uploaded file replaces, or browse and repair a lineage.
 *
 * Everything is derived from the file list the Files tab has already fetched -
 * there is no lineage endpoint, because `GET /files` already returns every
 * file with its `document_id`.
 */
export function FileVersionDialog({
  project,
  file,
  files,
  open,
  onOpenChange,
  onDone,
}: {
  project: Project
  file: FileRecord
  files: FileRecord[]
  open: boolean
  onOpenChange: (open: boolean) => void
  onDone: (updated: FileRecord[]) => void
}) {
  const reviewing = file.status === "review"

  const { editions, current } = useMemo(() => {
    const lineage = lineageOf(file)
    // The WHOLE lineage, this file included. `current` must be searched over
    // all of it, not just the siblings: opening history from the in-force
    // edition would otherwise find no current edition and offer to reinstate
    // over nothing.
    const editions = files
      .filter((f) => lineageOf(f) === lineage)
      .sort(byRecency)
    return {
      editions,
      // The one edition in force, if any. `file` itself qualifies in history
      // mode; in review mode it cannot, because its status IS "review".
      current: editions.find(
        (f) => f.in_force_to === null && f.status !== "review"
      ),
    }
  }, [file, files])

  // Seeded from the extractor's proposal, in useState initialisers rather than
  // an effect. The Files tab mounts this component only while a file is
  // targeted and unmounts it on close, so every open is a fresh mount and
  // these run exactly once with the proposal already in hand - no cascading
  // render, and no stale edit surviving a cancel.
  //
  // `true` = a new edition of `current`; `false` = a separate document.
  const [isVersion, setIsVersion] = useState(() => Boolean(current))
  const [label, setLabel] = useState(() => file.version_label ?? "")
  const [from, setFrom] = useState(() => file.in_force_from ?? "")
  const [status, setStatus] = useState<string>(
    () => file.legal_status ?? "in_force"
  )
  const [saving, setSaving] = useState(false)

  const supersedes = isVersion && current ? current : null
  const dateValid = !supersedes || ISO_DATE.test(from.trim())

  /**
   * One version decision.
   *
   * `documentId` is passed explicitly rather than derived from `predecessor`:
   * the two differ for the repair actions. Reinstating keeps the lineage with
   * no predecessor (`documentId` set, `predecessor` null); detaching clears it
   * (both null).
   *
   * `meta` is passed explicitly too, because history-mode actions act on an
   * edition that is NOT the one the dialog was opened on - sending the form
   * state would stamp this file's label and dates onto that one.
   */
  async function submit(
    target: FileRecord,
    predecessor: FileRecord | null,
    documentId: string | null,
    meta: {
      version_label: string | null
      in_force_from: string | null
      legal_status: string | null
    },
    message: string
  ) {
    setSaving(true)
    try {
      const updated = await api<FileRecord[]>(
        `/api/projects/${project.id}/files/${target.id}/version`,
        {
          method: "POST",
          body: JSON.stringify({
            document_id: documentId,
            supersede_file_id: predecessor?.id ?? null,
            ...meta,
          }),
        }
      )
      onDone(updated)
      onOpenChange(false)
      toast.success(message)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the version")
    } finally {
      setSaving(false)
    }
  }

  /** An edition's own metadata, for an action that must not rewrite it. */
  const metaOf = (edition: FileRecord) => ({
    version_label: edition.version_label,
    in_force_from: edition.in_force_from,
    legal_status: edition.legal_status,
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100vh-2rem)] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0 sm:max-w-2xl">
        <DialogHeader className="border-b bg-linear-to-b from-muted/50 to-background px-5 py-5 pr-12 sm:px-6 sm:py-6 sm:pr-14">
          <div className="flex min-w-0 items-start gap-3 text-left">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl border bg-background shadow-xs">
              <GitBranch className="size-5 text-muted-foreground" />
            </div>
            <div className="min-w-0 space-y-1.5">
              <DialogTitle>
                {reviewing ? "Confirm version" : "Version history"}
              </DialogTitle>
              <DialogDescription className="[overflow-wrap:anywhere] leading-relaxed">
                {reviewing
                  ? `${file.filename} looks like a new version of a document already in this project. Nothing changes until you confirm.`
                  : `Review every edition of this document in ${project.name}.`}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="min-h-0 overflow-y-auto px-4 py-5 sm:px-6">
          {reviewing ? (
            <div className="space-y-4">
              <div className="space-y-2">
                {current && (
                  <button
                    type="button"
                    onClick={() => setIsVersion(true)}
                    aria-pressed={isVersion}
                    className={`flex w-full min-w-0 items-start gap-3 rounded-xl border p-3.5 text-left text-sm transition-colors ${
                      isVersion
                        ? "border-foreground/30 bg-muted/60 shadow-xs"
                        : "border-border hover:bg-muted/30"
                    }`}
                  >
                    <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-background">
                      <GitBranch className="size-4" />
                    </span>
                    <span className="min-w-0">
                      <span className="block font-medium [overflow-wrap:anywhere]">
                        A new version of {current.filename}
                      </span>
                      <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">
                        That version is kept and stays downloadable, but stops
                        being searchable.
                      </span>
                    </span>
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setIsVersion(false)}
                  aria-pressed={!isVersion}
                  className={`flex w-full min-w-0 items-start gap-3 rounded-xl border p-3.5 text-left text-sm transition-colors ${
                    !isVersion
                      ? "border-foreground/30 bg-muted/60 shadow-xs"
                      : "border-border hover:bg-muted/30"
                  }`}
                >
                  <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-background">
                    <FileText className="size-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="block font-medium">
                      A separate document
                    </span>
                    <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">
                      Index it on its own. Nothing else is affected.
                    </span>
                  </span>
                </button>
              </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="version-label">Version label</Label>
                <Input
                  id="version-label"
                  value={label}
                  maxLength={200}
                  placeholder="Act 18 of 2013"
                  onChange={(e) => setLabel(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="in-force-from">
                  In force from{supersedes ? " *" : ""}
                </Label>
                {/* A plain text input, not type="date": the app owns no date
                    primitive, the extractor prefills this in the common case,
                    and the value is an ISO string at every hop, so there is
                    nothing to convert. Pydantic rejects 2019-02-30 server-side. */}
                <Input
                  id="in-force-from"
                  value={from}
                  placeholder="YYYY-MM-DD"
                  inputMode="numeric"
                  aria-invalid={!dateValid}
                  onChange={(e) => setFrom(e.target.value)}
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="legal-status">Status</Label>
              <Select value={status} onValueChange={setStatus}>
                <SelectTrigger id="legal-status">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LEGAL_STATUSES.map((s) => (
                    <SelectItem key={s.value} value={s.value}>
                      {s.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {supersedes && (
              <div className="space-y-1.5 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-muted-foreground">
                <p>
                  While the new version is indexing, this document is briefly
                  not searchable.
                </p>
                <p>
                  Saved memories are not versioned. Any memory quoting the
                  previous version stays in this project and can still be cited
                  in answers.
                </p>
              </div>
            )}
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex min-w-0 items-center justify-between gap-3 rounded-xl border bg-muted/30 px-4 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-background shadow-xs">
                    <FileText className="size-4 text-muted-foreground" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium">
                      {editions.length} edition{editions.length === 1 ? "" : "s"}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      Newest edition first
                    </p>
                  </div>
                </div>
                {current && (
                  <span className="hidden max-w-[50%] truncate text-xs text-muted-foreground sm:block">
                    Current: {current.version_label || current.filename}
                  </span>
                )}
              </div>

              <ol>
                {editions.map((edition, index) => {
                  const superseded = Boolean(edition.in_force_to)
                  const legalStatus = LEGAL_STATUSES.find(
                    (item) => item.value === edition.legal_status
                  )?.label

                  return (
                    <li
                      key={edition.id}
                      className="relative grid min-w-0 grid-cols-[1.25rem_minmax(0,1fr)] gap-3 pb-4 last:pb-0"
                    >
                      {index < editions.length - 1 && (
                        <span
                          aria-hidden="true"
                          className="absolute top-5 bottom-0 left-[0.59375rem] w-px bg-border"
                        />
                      )}
                      <span
                        aria-hidden="true"
                        className={`relative z-10 mt-4 size-5 rounded-full border-4 border-background ring-1 ${
                          superseded
                            ? "bg-muted-foreground/40 ring-border"
                            : "bg-emerald-500 ring-emerald-500/30"
                        }`}
                      />

                      <article
                        className={`min-w-0 overflow-hidden rounded-xl border bg-card p-4 shadow-xs ${
                          superseded ? "text-foreground/80" : "border-emerald-500/25"
                        }`}
                      >
                        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                          <div className="min-w-0">
                            <p
                              className="font-medium leading-snug [overflow-wrap:anywhere]"
                              title={edition.filename}
                            >
                              {edition.filename}
                            </p>
                            <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                              {edition.version_label && (
                                <span className="max-w-full rounded-md bg-muted px-2 py-1 font-medium text-foreground/80 [overflow-wrap:anywhere]">
                                  {edition.version_label}
                                </span>
                              )}
                              <span className="[overflow-wrap:anywhere]">
                                {edition.in_force_from ?? "Start date unknown"}
                                {" – "}
                                {edition.in_force_to ?? "Present"}
                              </span>
                              {legalStatus && (
                                <span>Legal status: {legalStatus}</span>
                              )}
                            </div>
                          </div>
                          {superseded ? (
                            <Badge variant="secondary" className="w-fit shrink-0">
                              Superseded
                            </Badge>
                          ) : (
                            <Badge className="w-fit shrink-0 border-transparent bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400">
                              Current
                            </Badge>
                          )}
                        </div>

                        <div className="mt-4 flex flex-col gap-2 border-t pt-3 sm:flex-row sm:flex-wrap">
                          <Button
                            size="sm"
                            variant="outline"
                            className="w-full sm:w-auto"
                            onClick={() =>
                              downloadFile(
                                `/api/projects/${project.id}/files/${edition.id}/content`,
                                edition.filename
                              ).catch(() =>
                                toast.error("Could not download the file")
                              )
                            }
                          >
                            <Download className="size-3.5" />
                            Original
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="w-full sm:w-auto"
                            onClick={() =>
                              downloadFile(
                                `/api/projects/${project.id}/files/${edition.id}/content?format=markdown`,
                                `${edition.filename}.md`
                              ).catch(() =>
                                toast.error("Could not download the text")
                              )
                            }
                          >
                            Text
                          </Button>
                          {/* Reinstating is offered only when the lineage has NO
                              edition in force. The endpoint clears in_force_to on its
                              target, so this needs no predecessor and no new date -
                              the edition keeps its own. With a current edition present
                              it would clash, and superseding forward instead would
                              demand a date later than that edition's, silently
                              rewriting this one's history. Detach the wrong edition
                              first; the copy below says so. */}
                          {superseded && !current && (
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-auto min-h-8 w-full whitespace-normal sm:w-auto"
                              disabled={saving}
                              onClick={() =>
                                submit(
                                  edition,
                                  null,
                                  lineageOf(edition),
                                  metaOf(edition),
                                  `${edition.filename} is the current version again`
                                )
                              }
                            >
                              Make this the current version
                            </Button>
                          )}
                          {editions.length > 1 && (
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-auto min-h-8 w-full whitespace-normal sm:ml-auto sm:w-auto"
                              disabled={saving}
                              onClick={() =>
                                submit(
                                  edition,
                                  null,
                                  null,
                                  metaOf(edition),
                                  `${edition.filename} is now its own document`
                                )
                              }
                            >
                              Not a version of this
                            </Button>
                          )}
                        </div>
                      </article>
                    </li>
                  )
                })}
              </ol>

              {editions.length > 1 && (
                <div className="rounded-xl border border-dashed bg-muted/20 p-3.5 text-xs leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">
                  {current
                    ? `${current.filename} is the version in force, so it is the only one answering questions. To bring an earlier one back, first use "Not a version of this" on ${current.filename} — then this list will offer to make one current again.`
                    : "No version of this document is in force, so none of it is searchable. Make one current to index it again — its text is already stored, so this costs an embedding run and nothing else."}
                </div>
              )}
            </div>
          )}
        </div>

        <DialogFooter className="border-t bg-muted/20 px-4 py-4 sm:px-6">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {reviewing ? "Cancel" : "Close"}
          </Button>
          {reviewing && (
            <Button
              disabled={saving || !dateValid}
              onClick={() =>
                submit(
                  file,
                  supersedes,
                  supersedes ? lineageOf(supersedes) : null,
                  {
                    version_label: label.trim() || null,
                    in_force_from: from.trim() || null,
                    legal_status: status || null,
                  },
                  supersedes
                    ? `${supersedes.filename} is now a superseded version`
                    : "Saved as a separate document"
                )
              }
            >
              {supersedes ? "Confirm and replace" : "Index as its own document"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
