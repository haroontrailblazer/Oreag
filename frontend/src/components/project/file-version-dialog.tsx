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

// The four roles that refer to another document rather than replacing it.
// Mirrors ingestion.NON_SUPERSEDING_ROLES; the endpoint enforces it too, so
// this only decides what the form lets you try.
const NON_SUPERSEDING = new Set(["amending", "correction", "translation", "supplement"])

const INSTRUMENT_ROLES = [
  { value: "principal", label: "A document in its own right" },
  { value: "consolidated", label: "Consolidated / later edition of one" },
  { value: "amending", label: "Amends another document" },
  { value: "correction", label: "Corrects another (erratum, retraction)" },
  { value: "translation", label: "Translation of another" },
  { value: "supplement", label: "Part of another (appendix, annex)" },
  { value: "unknown", label: "Not sure" },
] as const

// What this document does to the one it replaces. The second line is the
// consequence, because that is the part a reviewer is actually deciding: does
// the document they matched keep answering questions or not.
const RELATIONS = [
  { value: "supersedes", label: "Replaces it", effect: "The earlier one stops answering questions." },
  { value: "restates", label: "Restates it in full", effect: "The earlier one stops answering questions." },
  { value: "succeeds", label: "Comes after it, both still valid", effect: "Both keep answering — a yearly series, or a version whose predecessor is still supported." },
  { value: "amends", label: "Amends it", effect: "The earlier one keeps answering and is marked amended. This document is stored but not searchable, so its diff text cannot be quoted as if it were the rule." },
  { value: "corrects", label: "Corrects it", effect: "The earlier one keeps answering. The notice is stored but not searchable." },
  { value: "retracts", label: "Retracts it", effect: "The earlier one stops answering and is marked retracted. It stays downloadable rather than disappearing." },
  { value: "translates", label: "Translates it", effect: "Both keep answering. The original is not retired." },
  { value: "supplements", label: "Is part of it", effect: "Both keep answering." },
] as const

const RETIRING = new Set(["supersedes", "restates", "retracts"])

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
 * Newest first, walking `supersedes_file_id` back from the current edition.
 *
 * Dates are the fallback, not the source of truth: `in_force_from` is
 * user-supplied and nullable, so a lineage of editions uploaded before the
 * chain existed - or whose effective date the extractor could not read - had
 * no defined order at all. Anything the chain does not reach (pre-0036
 * editions, a link whose predecessor was deleted) is appended in date order,
 * so an older corpus degrades to exactly its previous behaviour.
 */
function inChainOrder(editions: FileRecord[]): FileRecord[] {
  const byId = new Map(editions.map((f) => [f.id, f]))
  const current = editions.find(
    (f) => f.in_force_to === null && f.status !== "review"
  )
  const chain: FileRecord[] = []
  const seen = new Set<string>()
  let cursor = current
  // `seen` is the loop guard. The database forbids an edition superseding
  // itself, but not a longer cycle across a repaired lineage.
  while (cursor && !seen.has(cursor.id)) {
    seen.add(cursor.id)
    chain.push(cursor)
    cursor = cursor.supersedes_file_id
      ? byId.get(cursor.supersedes_file_id)
      : undefined
  }
  const rest = editions.filter((f) => !seen.has(f.id)).sort(byRecency)
  return [...chain, ...rest]
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
    const editions = inChainOrder(
      files.filter((f) => lineageOf(f) === lineage)
    )
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
  // DELIBERATELY UNDECIDED. This used to default to "a new version of X" -
  // the extractor's guess, pre-selected. Measured over 105 realistic
  // documents, that guess was wrong for 28 of the 37 documents that should not
  // have matched at all: errata, translations, supplements, editorials. A
  // default answer that is wrong more often than right, on the one action that
  // RETIRES content, is not a convenience. The reviewer chooses.
  const [isVersion, setIsVersion] = useState<boolean | null>(null)
  const [label, setLabel] = useState(() => file.version_label ?? "")
  const [from, setFrom] = useState(() => file.in_force_from ?? "")
  const [status, setStatus] = useState<string>(
    () => file.legal_status ?? "in_force"
  )
  const [role, setRole] = useState<string>(() => file.instrument_role ?? "unknown")
  const [relation, setRelation] = useState<string>(
    () => file.relation_kind ?? "supersedes"
  )
  const [saving, setSaving] = useState(false)

  const supersedes = isVersion === true && current ? current : null
  const retires = supersedes !== null && RETIRING.has(relation)
  // Only a retiring relation needs a date: it becomes the predecessor's
  // in_force_to. An amendment or a translation retires nothing.
  const dateValid = !retires || ISO_DATE.test(from.trim())
  const roleBlocks = retires && NON_SUPERSEDING.has(role)
  const canSubmit = isVersion !== null && dateValid && !roleBlocks

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
      instrument_role: string | null
      relation_kind: string | null
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
    instrument_role: edition.instrument_role,
    relation_kind: edition.relation_kind,
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100vh-2rem)] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0 sm:max-w-2xl">
        <DialogHeader className="border-b px-5 py-5 pr-12 sm:px-6 sm:pr-14">
          <div className="min-w-0 space-y-1.5 text-left">
            <div className="flex items-center gap-2">
              <GitBranch className="size-4 shrink-0 text-muted-foreground" />
              <DialogTitle className="text-base">
                {reviewing ? "Confirm version" : "Version history"}
              </DialogTitle>
            </div>
            <DialogDescription className="[overflow-wrap:anywhere] leading-relaxed">
              {reviewing
                ? `${file.filename} looks like a new version of a document already in this project. Nothing changes until you confirm.`
                : `Review every edition of this document in ${project.name}.`}
            </DialogDescription>
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
                    aria-pressed={isVersion === true}
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
                        You choose what this does to it next &mdash; replacing
                        it is one option, not the only one.
                      </span>
                    </span>
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setIsVersion(false)}
                  aria-pressed={isVersion === false}
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
                  In force from{retires ? " *" : ""}
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

            {isVersion === true && current && (
              <div className="space-y-1.5">
                <Label htmlFor="relation-kind">
                  What does it do to that version?
                </Label>
                <Select value={relation} onValueChange={setRelation}>
                  <SelectTrigger id="relation-kind">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {RELATIONS.map((r) => (
                      <SelectItem key={r.value} value={r.value}>
                        {r.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {/* The consequence, not the definition: what a reviewer is
                    actually deciding is whether the document they matched
                    keeps answering questions. */}
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {RELATIONS.find((r) => r.value === relation)?.effect}
                </p>
              </div>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="instrument-role">What kind of document is this?</Label>
              <Select value={role} onValueChange={setRole}>
                <SelectTrigger id="instrument-role">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {INSTRUMENT_ROLES.map((r) => (
                    <SelectItem key={r.value} value={r.value}>
                      {r.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {roleBlocks && (
                <p className="text-xs text-amber-700 dark:text-amber-400">
                  A document of this kind refers to another rather than
                  replacing it, so it cannot retire{" "}
                  <span className="font-medium">{current?.filename}</span>.
                  Choose a relation above that leaves it answering &mdash;
                  amends, corrects or is part of.
                </p>
              )}
            </div>

            {isVersion === null && (
              <p className="text-xs text-muted-foreground">
                Choose one above. Nothing is pre-selected because some of
                these choices retire the document they point at.
              </p>
            )}

            {retires && (
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
            <div className="space-y-5">
              <div className="flex min-w-0 items-center justify-between gap-3">
                <p className="text-xs text-muted-foreground">
                  {editions.length} version{editions.length === 1 ? "" : "s"}
                  <span aria-hidden="true"> · </span>
                  Newest first
                </p>
                {current && (
                  <span className="hidden max-w-[55%] truncate text-xs text-muted-foreground sm:block">
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
                      className="relative grid min-w-0 grid-cols-[0.75rem_minmax(0,1fr)] gap-4 pb-6 last:pb-0"
                    >
                      {index < editions.length - 1 && (
                        <span
                          aria-hidden="true"
                          className="absolute top-3 bottom-0 left-[0.34375rem] w-px bg-border"
                        />
                      )}
                      <span
                        aria-hidden="true"
                        className={`relative z-10 mt-1.5 size-3 rounded-full ring-4 ring-background ${
                          superseded
                            ? "border border-muted-foreground/30 bg-background"
                            : "bg-emerald-500"
                        }`}
                      />

                      <article
                        className={`min-w-0 ${
                          index < editions.length - 1 ? "border-b pb-6" : ""
                        }`}
                      >
                        <div className="flex min-w-0 flex-col items-start gap-2 sm:flex-row sm:justify-between sm:gap-3">
                          <div className="min-w-0">
                            <p
                              className={`text-sm font-medium leading-snug [overflow-wrap:anywhere] ${
                                superseded ? "text-foreground/80" : "text-foreground"
                              }`}
                              title={edition.filename}
                            >
                              {edition.filename}
                            </p>
                            <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
                              {edition.version_label && (
                                <span className="max-w-full font-medium text-foreground/70 [overflow-wrap:anywhere]">
                                  {edition.version_label}
                                </span>
                              )}
                              {edition.version_label && (
                                <span aria-hidden="true">·</span>
                              )}
                              <span className="[overflow-wrap:anywhere]">
                                {edition.in_force_from ?? "Start date unknown"}
                                {" – "}
                                {edition.in_force_to ?? "Present"}
                              </span>
                              {legalStatus && (
                                <>
                                  <span aria-hidden="true">·</span>
                                  <span>{legalStatus}</span>
                                </>
                              )}
                            </div>
                          </div>
                          {superseded ? (
                            <Badge
                              variant="outline"
                              className="h-5 w-fit shrink-0 px-1.5 text-[10px] font-normal text-muted-foreground"
                            >
                              Superseded
                            </Badge>
                          ) : (
                            <Badge
                              variant="outline"
                              className="h-5 w-fit shrink-0 border-emerald-500/30 px-1.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-400"
                            >
                              Current
                            </Badge>
                          )}
                        </div>

                        <div className="mt-3 flex flex-wrap items-center gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-8 px-2 text-muted-foreground"
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
                            variant="ghost"
                            className="h-8 px-2 text-muted-foreground"
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
                              className="h-auto min-h-8 whitespace-normal"
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
                              className="h-auto min-h-8 whitespace-normal text-muted-foreground sm:ml-auto"
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
                <div className="border-l-2 pl-3 text-xs leading-relaxed text-muted-foreground">
                  {current
                    ? 'Only the current version is used to answer questions. To restore an earlier edition, first choose "Not a version of this" on the current one.'
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
              disabled={saving || !canSubmit}
              onClick={() =>
                submit(
                  file,
                  supersedes,
                  supersedes ? lineageOf(supersedes) : null,
                  {
                    version_label: label.trim() || null,
                    in_force_from: from.trim() || null,
                    legal_status: status || null,
                    instrument_role: role || null,
                    relation_kind: supersedes ? relation : null,
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
