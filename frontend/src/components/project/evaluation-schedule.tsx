"use client"
import { useState } from "react"
import Link from "next/link"
import { ArrowsClockwiseIcon, ClockIcon, FloppyDiskIcon } from "@phosphor-icons/react/dist/ssr"
import useSWR from "swr"
import { api, fetcher } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { ChangeChecks } from "@/components/change-checks"
import { FilterSelect } from "@/components/filter-select"
import type { EvaluationRun } from "@/lib/evaluation"

type Schedule = { revision: number; enabled: boolean; on_changes: boolean; change_due_at: string | null; interval_hours: number; reference_run_id: string | null; quality_limits: { quality_drop_pp: number; latency_increase_percent: number; cost_increase_percent: number }; next_run_at: string | null; last_run_at: string | null; last_error: string | null }
export function EvaluationSchedule({ base, history }: { base: string; history: EvaluationRun[] }) {
  const { data: retained } = useSWR<EvaluationRun[]>(`${base}/runs`, fetcher)
  const { data, error, mutate } = useSWR<Schedule>(`${base}/schedule`, fetcher, { refreshInterval: 30000 })
  const [draft, setDraft] = useState<Schedule | null>(null)
  const [message, setMessage] = useState("")
  const [busy, setBusy] = useState(false)
  const value = draft ?? data
  async function save() {
    if (!value) return
    setBusy(true); setMessage("")
    try {
      const { revision, enabled, on_changes, interval_hours, reference_run_id, quality_limits } = value
      await mutate(await api<Schedule>(`${base}/schedule`, { method: "PUT", body: JSON.stringify({ revision, enabled, on_changes, interval_hours, reference_run_id, quality_limits }) }), { revalidate: false })
      setDraft(null); setMessage("Automatic checks saved.")
    } catch (e) { setMessage(e instanceof Error ? e.message : "Could not save schedule.") }
    finally { setBusy(false) }
  }
  return <details className="rounded-xl border bg-card p-4"><summary className="cursor-pointer rounded-sm text-sm font-medium focus-visible:outline-2"><span className="inline-flex items-center gap-2"><ClockIcon className="size-4 text-muted-foreground" aria-hidden="true" />Automatic checks</span><span className="ml-2 text-xs font-normal text-muted-foreground">{data?.enabled && data?.on_changes ? "Scheduled + after changes" : data?.on_changes ? "After changes" : data?.enabled ? "Scheduled" : "Off"}</span></summary>
    <div className="mt-4 space-y-4 text-xs">
      <p className="leading-5 text-muted-foreground">Runs continue after you close the browser. Save your test set before scheduling. Each check uses its own knowledge snapshot and leaves live project settings unchanged. Provider usage is billed normally.</p>
      {error && <p role="alert">Could not load schedule. <button className="underline" onClick={() => void mutate()}>Retry</button></p>}
      {value && <fieldset disabled={busy} className="space-y-4">
        <label className="flex items-center justify-between gap-3 rounded-lg border p-3"><span className="font-medium">Run on a schedule</span><Switch checked={value.enabled} onCheckedChange={enabled => setDraft({ ...value, enabled })} /></label>
        <label className="flex items-start justify-between gap-3 rounded-lg border p-3"><span className="space-y-1"><span className="block font-medium">Run after changes</span><span className="block leading-5 text-muted-foreground">Check the saved questions after documents, memories, or answer settings change. Waits for indexing and combines rapid edits into one run.</span></span><Switch className="shrink-0" checked={value.on_changes ?? false} onCheckedChange={on_changes => setDraft({ ...value, on_changes })} /></label>
        {value.on_changes && <p className="leading-5 text-muted-foreground">Change checks use the project’s current configuration. The questions come from the test set saved when you save these settings. Save Automatic checks again after changing that test set.</p>}
        {value.enabled && <div className="grid min-w-0 gap-3 sm:grid-cols-2">
          <FilterSelect label="Check frequency" value={String(value.interval_hours)} onChange={v => setDraft({ ...value, interval_hours: Number(v) })} options={[6, 12, 24, 168].map(n => ({ value: String(n), label: n === 168 ? "Weekly" : `Every ${n} hours` }))} />
          <FilterSelect label="Reference run" value={value.reference_run_id ?? ""} onChange={v => setDraft({ ...value, reference_run_id: v || null })} options={[{ value: "", label: "No reference — record metrics only" }, ...(retained ?? history).filter(r => r.status === "completed").map(r => ({ value: r.id, label: new Date(r.created_at).toLocaleString() }))]} />
        </div>}
        <div className="grid gap-3 sm:grid-cols-3">{([['quality_drop_pp', 'Pass rate drop (points)', 100], ['latency_increase_percent', 'Latency rise (%)', 1000], ['cost_increase_percent', 'Cost rise (%)', 1000]] as const).map(([key, label, max]) => <label key={key} className="space-y-1.5">{label}<Input type="number" min={0} max={max} step="any" value={value.quality_limits[key]} onChange={e => setDraft({ ...value, quality_limits: { ...value.quality_limits, [key]: Number(e.target.value) } })} /></label>)}</div>
        <p className="leading-5 text-muted-foreground">Scheduled checks use your selected reference. Change checks use the latest completed run with the same questions. Warnings appear in run history; missing measurements are excluded from comparisons.</p>
        <div className="flex flex-wrap gap-2"><Button size="sm" onClick={() => void save()}><FloppyDiskIcon aria-hidden="true" />{busy ? "Saving…" : "Save automatic checks"}</Button><Button size="sm" variant="outline" asChild><Link href={`/projects/${base.split("/")[3]}?tab=playground`}>Edit saved tests</Link></Button><Button size="sm" variant="ghost" onClick={() => { setDraft(null); setMessage(""); void mutate() }}><ArrowsClockwiseIcon aria-hidden="true" />Reload settings</Button></div>
        {data?.next_run_at && <p>Next check: {new Date(data.next_run_at).toLocaleString()}</p>}
        {data?.change_due_at && <p>Change detected. A check will start after indexing and any active run finish.</p>}
        {data?.last_error && <p role="alert" className="text-destructive">{data.last_error}</p>}
      </fieldset>}
      {message && <p role="status">{message}</p>}
      <ChangeChecks base={base} />
    </div>
  </details>
}
