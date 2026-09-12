"use client"

import { useState } from "react"
import useSWR from "swr"
import { BookmarkSimpleIcon, FloppyDiskIcon, PencilSimpleIcon, TrashIcon } from "@phosphor-icons/react/dist/ssr"
import { api, fetcher, isSessionExpired } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Spinner } from "@/components/ui/spinner"

type SavedView<T> = { id: string; name: string; kind: string; filters: T }

export function SavedQueryViews<T extends Record<string, string>>({ kind, filters, onApply }: {
  kind: "queries" | "failures"; filters: T; onApply: (filters: T) => void
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [editing, setEditing] = useState<SavedView<T> | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState("")
  const key = `/api/account/query-views?kind=${kind}`
  const { data, error, mutate } = useSWR<SavedView<T>[]>(open ? key : null, fetcher)
  async function save() {
    setBusy(true); setFailure("")
    try {
      const id = editing?.id ?? crypto.randomUUID()
      await api(`/api/account/query-views/${id}`, { method: "PUT", body: JSON.stringify({ id, name: name.trim(), kind, filters: editing?.filters ?? filters }) })
      setEditing(null); setName(""); await mutate()
    } catch (error) { if (!isSessionExpired(error)) setFailure(error instanceof Error ? error.message : "Could not save view") }
    finally { setBusy(false) }
  }
  async function remove(id: string) {
    setBusy(true); setFailure("")
    try {
      await api(`/api/account/query-views/${id}`, { method: "DELETE" })
      if (editing?.id === id) { setEditing(null); setName("") }
      await mutate()
    } catch (error) { if (!isSessionExpired(error)) setFailure(error instanceof Error ? error.message : "Could not remove view") }
    finally { setBusy(false) }
  }
  return <>
    <Button variant="outline" size="sm" onClick={() => { setOpen(true); setFailure("") }}><BookmarkSimpleIcon aria-hidden="true" />Saved views</Button>
    <Dialog open={open} onOpenChange={value => { if (!busy) setOpen(value) }}>
      <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader><DialogTitle>Saved views</DialogTitle><DialogDescription>Save your {kind === "queries" ? "query" : "failed request"} filters and search. Views are private to your account and available across devices.</DialogDescription></DialogHeader>
        <form className="space-y-3 rounded-xl border p-4" onSubmit={event => { event.preventDefault(); void save() }}>
          <label className="block space-y-2 text-xs font-medium">{editing ? "Rename view" : "Save current filters"}<Input autoComplete="off" value={name} onChange={event => setName(event.target.value)} maxLength={60} placeholder="e.g. Slow requests in Testing" disabled={busy} /></label>
          <div className="flex flex-wrap gap-2"><Button size="sm" type="submit" disabled={busy || !name.trim()}>{busy ? <Spinner size={14} /> : <FloppyDiskIcon aria-hidden="true" />}{editing ? "Save name" : "Save view"}</Button>{editing && <Button type="button" size="sm" variant="ghost" onClick={() => { setEditing(null); setName("") }}>Cancel rename</Button>}</div>
        </form>
        {failure && <p role="alert" className="text-xs text-destructive">{failure}</p>}
        {error && !isSessionExpired(error) ? <div role="alert" className="space-y-2 text-xs"><p>Could not load saved views.</p><Button variant="outline" size="sm" onClick={() => void mutate()}>Retry</Button></div>
          : !data ? <p role="status" className="py-5 text-center text-xs text-muted-foreground">Loading saved views…</p>
          : !data.length ? <p className="py-5 text-center text-xs text-muted-foreground">No saved views yet. Save the filters you use most.</p>
          : <ul className="divide-y rounded-xl border">{data.map(view => <li key={view.id} className="flex min-w-0 items-center gap-1 p-2">
            <Button variant="ghost" className="h-auto min-w-0 flex-1 justify-start whitespace-normal py-2 text-left text-xs [overflow-wrap:anywhere]" disabled={busy} onClick={() => { onApply(view.filters); setOpen(false) }}><BookmarkSimpleIcon className="shrink-0" aria-hidden="true" />{view.name}</Button>
            <Button size="icon-sm" variant="ghost" aria-label={`Rename ${view.name}`} disabled={busy} onClick={() => { setEditing(view); setName(view.name) }}><PencilSimpleIcon aria-hidden="true" /></Button>
            <Button size="icon-sm" variant="ghost" aria-label={`Delete ${view.name}`} disabled={busy} onClick={() => void remove(view.id)}><TrashIcon aria-hidden="true" /></Button>
          </li>)}</ul>}
      </DialogContent>
    </Dialog>
  </>
}
