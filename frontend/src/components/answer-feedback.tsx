"use client"

import { useId, useState } from "react"
import { useSWRConfig } from "swr"
import { ThumbsDownIcon, ThumbsUpIcon } from "@phosphor-icons/react/dist/ssr"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { api } from "@/lib/api"
import type { QueryRecord } from "@/lib/query-explorer"
import { KNOWLEDGE_HEALTH_KEY } from "@/lib/knowledge-health"

type Rating = "helpful" | "not_helpful"

/** A rating belongs to this invocation, not the cached answer shared by others. */
export function AnswerFeedback({ queryId, initialRating = null, initialNote = "" }: {
  queryId: string
  initialRating?: Rating | null
  initialNote?: string | null
}) {
  const noteId = useId()
  const { mutate } = useSWRConfig()
  const [rating, setRating] = useState(initialRating)
  const [savedNote, setSavedNote] = useState(initialNote ?? "")
  const [note, setNote] = useState(initialNote ?? "")
  const [expanded, setExpanded] = useState(Boolean(initialNote) || initialRating === "not_helpful")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [message, setMessage] = useState("")

  async function save(next: Rating | null) {
    if (busy) return
    setBusy(true)
    setError("")
    setMessage("")
    try {
      if (next === null) {
        await api(`/api/account/queries/${queryId}/feedback`, { method: "DELETE" })
        setRating(null)
        setNote("")
        setSavedNote("")
        setExpanded(false)
        setMessage("Feedback removed")
      } else {
        const result = await api<QueryRecord>(`/api/account/queries/${queryId}/feedback`, {
          method: "PUT", body: JSON.stringify({ rating: next, note: note.trim() }),
        })
        setRating(result.feedback_rating ?? next)
        setNote(result.feedback_note ?? "")
        setSavedNote(result.feedback_note ?? "")
        if (next === "not_helpful") setExpanded(true)
        setMessage("Feedback saved")
      }
      // Keep owner reports in sync with the same feedback the public API writes.
      void mutate(key => typeof key === "string" &&
        (key.startsWith("/api/account/queries?") || key === `/api/account/queries/${queryId}` || key === KNOWLEDGE_HEALTH_KEY)).catch(() => {})
    } catch {
      setError("Could not save feedback. Please try again.")
    } finally {
      setBusy(false)
    }
  }

  return <div className="min-w-0 space-y-2" role="group" aria-label="Answer feedback">
    <div className="flex flex-wrap items-center gap-1">
      <span className="mr-1 text-xs text-muted-foreground">Helpful?</span>
      {(["helpful", "not_helpful"] as const).map(value => {
        const Icon = value === "helpful" ? ThumbsUpIcon : ThumbsDownIcon
        const label = value === "helpful" ? "Helpful answer" : "Not helpful answer"
        return <Button key={value} size="icon-sm" variant={rating === value ? "secondary" : "ghost"}
          aria-label={label} title={label} aria-pressed={rating === value} disabled={busy}
          onClick={() => void save(value)}><Icon className="size-4" weight={rating === value ? "fill" : "regular"} /></Button>
      })}
      {rating && <>
        <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" aria-expanded={expanded} aria-controls={noteId + "-editor"} onClick={() => setExpanded(value => !value)}>
          {expanded ? "Hide note" : savedNote ? "Edit note" : "Add note"}
        </Button>
        <Button size="sm" variant="ghost" className="h-7 px-2 text-xs text-muted-foreground" disabled={busy} onClick={() => void save(null)}>Remove</Button>
      </>}
    </div>
    {expanded && rating && <div id={noteId + "-editor"} className="space-y-2 rounded-lg border bg-background p-3">
      <label htmlFor={noteId} className="text-xs font-medium">What should we know? <span className="font-normal text-muted-foreground">(optional)</span></label>
      <Textarea id={noteId} value={note} onChange={event => setNote(event.target.value)} maxLength={1000} disabled={busy}
        placeholder="Tell us what worked or what needs improving…" className="min-h-20 resize-y text-sm" />
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">{note.length}/1000</span>
        <Button size="sm" disabled={busy || note.trim() === savedNote} onClick={() => void save(rating)}>{busy ? "Saving…" : "Save note"}</Button>
      </div>
    </div>}
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    <p role="status" className="text-xs text-muted-foreground">{busy ? "Saving feedback…" : message}</p>
  </div>
}
