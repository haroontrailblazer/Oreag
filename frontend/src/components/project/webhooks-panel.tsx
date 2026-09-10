"use client"
import { useState } from "react"
import useSWR from "swr"
import { api, fetcher } from "@/lib/api"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { PlugsConnectedIcon } from "@phosphor-icons/react/dist/ssr"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"

const events = ["file.indexed", "file.failed", "evaluation.completed", "evaluation.failed", "evaluation.regressed", "budget.threshold_reached"]
type Endpoint = { id: string; url: string; enabled: boolean; events: string[] }
type Delivery = { id: string; event_id: string; event_type: string; status: string; attempts: number; response_status: number | null; last_error: string | null; created_at: string; history: { at: string; status: number | null; error: string | null }[] }

function Deliveries({ base, endpoint }: { base: string; endpoint: Endpoint }) {
  const { data, error, mutate } = useSWR<Delivery[]>(`${base}/${endpoint.id}/deliveries`, fetcher, { refreshInterval: 10000 })
  const [message, setMessage] = useState("")
  async function retry(id: string) { try { await api(`${base}/${endpoint.id}/deliveries/${id}/retry`, { method: "POST" }); await mutate() } catch (e) { setMessage(e instanceof Error ? e.message : "Retry failed") } }
  return <div className="space-y-3 text-xs">{(error || message) && <p role="alert">{message || "Could not load deliveries."}</p>}{data?.length === 0 && <p className="text-muted-foreground">No deliveries yet. New matching events will appear here.</p>}
    {data?.map(d => <details key={d.id} className="rounded-lg border p-3"><summary className="cursor-pointer break-words">{d.event_type} · {d.status} · {d.attempts} attempts</summary><div className="mt-3 space-y-2"><p className="break-all text-muted-foreground">Event {d.event_id}</p><p>{new Date(d.created_at).toLocaleString()}</p>{d.history.map((h, i) => <p key={i}>{new Date(h.at).toLocaleString()} · {h.status ? `HTTP ${h.status}` : "Connection failed"}{h.error && ` · ${h.error}`}</p>)}{d.status === "failed" && <Button size="sm" variant="outline" disabled={!endpoint.enabled} onClick={() => void retry(d.id)}>Retry delivery</Button>}</div></details>)}
  </div>
}

export function WebhooksPanel({ projectId }: { projectId: string }) {
  const base = `/api/projects/${projectId}/webhooks`
  const { data, error, mutate } = useSWR<Endpoint[]>(base, fetcher)
  const [open, setOpen] = useState(false), [url, setUrl] = useState(""), [selected, setSelected] = useState(events)
  const [secret, setSecret] = useState(""), [message, setMessage] = useState(""), [busy, setBusy] = useState(false)
  const [remove, setRemove] = useState<Endpoint | null>(null), [rotate, setRotate] = useState<Endpoint | null>(null)
  async function action(path: string, method: string, body?: unknown) {
    setBusy(true); setMessage("")
    try {
      const result = await api<{ secret?: string }>(path, { method, ...(body ? { body: JSON.stringify(body) } : {}) })
      if (result?.secret) setSecret(result.secret)
      await mutate(); setOpen(false); setRemove(null); setRotate(null)
    } catch (e) { setMessage(e instanceof Error ? e.message : "Webhook update failed") }
    finally { setBusy(false) }
  }
  return <Card id="project-api-webhooks">
    <CardHeader>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <CardTitle><PlugsConnectedIcon aria-hidden="true" />Webhooks</CardTitle>
        <Button size="sm" variant="outline" disabled={!data || data.length >= 5} onClick={() => { setMessage(""); setOpen(true) }}>Add webhook</Button>
      </div>
      <CardDescription>Send indexing, evaluation and budget events to your application.</CardDescription>
    </CardHeader>
    <CardContent className="space-y-4">
    {error && <p role="alert" className="text-xs">Could not load webhooks. <button className="underline" onClick={() => void mutate()}>Retry</button></p>}
    {!open && !remove && !rotate && message && <p role="alert" className="text-xs">{message}</p>}
    {data?.length === 0 && <div className="rounded-xl border border-dashed bg-muted/20 px-4 py-5"><p className="text-sm font-medium">No webhooks yet</p><p className="mt-1 text-xs leading-5 text-muted-foreground">Add an HTTPS endpoint to receive project events automatically.</p></div>}
    {data?.map(e => <div key={e.id} className="space-y-3 rounded-lg border p-3"><p className="break-all text-sm font-medium">{e.url}</p><p className="break-words text-xs leading-5 text-muted-foreground">{e.events.join(" · ")}</p><div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void action(`${base}/${e.id}`, "PATCH", { enabled: !e.enabled })}>{e.enabled ? "Pause" : "Enable"}</Button><Button size="sm" variant="ghost" onClick={() => { setMessage(""); setRotate(e) }}>Rotate secret</Button><Button size="sm" variant="ghost" onClick={() => { setMessage(""); setRemove(e) }}>Remove</Button></div><details><summary className="cursor-pointer text-xs">Delivery history</summary><div className="mt-3"><Deliveries base={base} endpoint={e} /></div></details></div>)}
    <p className="text-xs leading-5 text-muted-foreground">Verify the signature against the raw request body. Deliveries retry up to eight times; deduplicate by event ID. Pausing stops new events and holds pending deliveries. Account-wide budget alerts stay in Usage. <a className="underline" href="/docs#reference-webhooks">Integration guide</a></p>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent className="max-h-[85dvh] overflow-y-auto"><DialogHeader><DialogTitle>Add webhook</DialogTitle><DialogDescription>Use a public HTTPS receiver. Only selected future events are sent.</DialogDescription></DialogHeader><label className="space-y-2 text-xs">Receiver URL<Input type="url" maxLength={2048} value={url} placeholder="https://your-app.com/webhooks/oreag" onChange={e => setUrl(e.target.value)} /></label><fieldset className="space-y-3"><legend className="mb-3 text-xs font-medium">Events</legend>{events.map(event => <label key={event} className="flex gap-2 text-xs"><input type="checkbox" checked={selected.includes(event)} onChange={e => setSelected(e.target.checked ? [...selected, event] : selected.filter(v => v !== event))} />{event}</label>)}</fieldset>{message && <p role="alert" className="text-xs">{message}</p>}<Button disabled={busy || !selected.length || !url} onClick={() => void action(base, "POST", { url, events: selected })}>Create webhook</Button></DialogContent></Dialog>
    <Dialog open={!!secret} onOpenChange={v => { if (!v) setSecret("") }}><DialogContent><DialogHeader><DialogTitle>Save your signing secret</DialogTitle><DialogDescription>This secret is shown once. Store it in your receiver’s environment.</DialogDescription></DialogHeader><Input aria-label="Webhook signing secret" readOnly value={secret} onFocus={e => e.target.select()} /><Button onClick={() => { void navigator.clipboard.writeText(secret).catch(() => setMessage("Select and copy the secret manually.")) }}>Copy secret</Button><Button variant="outline" onClick={() => setSecret("")}>Done</Button></DialogContent></Dialog>
    <Dialog open={!!remove || !!rotate} onOpenChange={v => { if (!v) { setRemove(null); setRotate(null) } }}><DialogContent><DialogHeader><DialogTitle>{remove ? "Remove webhook?" : "Rotate signing secret?"}</DialogTitle><DialogDescription>{remove ? "This removes the endpoint, pending deliveries, and its delivery history." : "Update your receiver with the new secret immediately. An already running attempt can still use the previous secret."}</DialogDescription></DialogHeader>{message && <p role="alert">{message}</p>}<Button disabled={busy} onClick={() => void (remove ? action(`${base}/${remove.id}`, "DELETE") : rotate && action(`${base}/${rotate.id}/rotate-secret`, "POST"))}>{remove ? "Remove webhook" : "Rotate secret"}</Button></DialogContent></Dialog>
    </CardContent>
  </Card>
}
