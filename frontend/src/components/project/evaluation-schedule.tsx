"use client"
import { useState } from "react"
import useSWR from "swr"
import { api, fetcher } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FilterSelect } from "@/components/filter-select"
import type { EvaluationRun } from "@/lib/evaluation"

type Schedule = { revision: number; enabled: boolean; interval_hours: number; reference_run_id: string | null; quality_limits: { quality_drop_pp: number; latency_increase_percent: number; cost_increase_percent: number }; next_run_at: string | null; last_run_at: string | null; last_error: string | null }
export function EvaluationSchedule({ base, history }: { base: string; history: EvaluationRun[] }) {
  const { data, error, mutate } = useSWR<Schedule>(`${base}/schedule`, fetcher, { refreshInterval: 30000 })
  const [draft, setDraft] = useState<Schedule | null>(null)
  const [message, setMessage] = useState("")
  const [busy, setBusy] = useState(false)
  const value = draft ?? data
  async function save() {
    if (!value) return
    setBusy(true); setMessage("")
    try {
      const { revision, enabled, interval_hours, reference_run_id, quality_limits } = value
      await mutate(await api<Schedule>(`${base}/schedule`, { method: "PUT", body: JSON.stringify({ revision, enabled, interval_hours, reference_run_id, quality_limits }) }), { revalidate: false })
      setDraft(null); setMessage("Schedule saved using the saved test set and configurations.")
    } catch (e) { setMessage(e instanceof Error ? e.message : "Could not save schedule.") }
    finally { setBusy(false) }
  }
  return <details className="rounded-xl border bg-card p-4"><summary className="cursor-pointer text-sm font-medium">Automatic checks <span className="ml-2 text-xs font-normal text-muted-foreground">{data?.enabled ? "Scheduled" : "Off"}</span></summary>
    <div className="mt-4 space-y-4 text-xs">
      <p className="leading-5 text-muted-foreground">Runs continue after you close the browser. Save your test set before scheduling. Each check uses its own knowledge snapshot and leaves live project settings unchanged. Provider usage is billed normally.</p>
      {error && <p role="alert">Could not load schedule. <button className="underline" onClick={() => void mutate()}>Retry</button></p>}
      {value && <fieldset disabled={busy} className="space-y-4">
        <label className="flex items-center gap-2"><input type="checkbox" checked={value.enabled} onChange={e => setDraft({ ...value, enabled: e.target.checked })} />Enable scheduled checks</label>
        <div className="grid min-w-0 gap-3 sm:grid-cols-2">
          <FilterSelect label="Check frequency" value={String(value.interval_hours)} onChange={v => setDraft({ ...value, interval_hours: Number(v) })} options={[6, 12, 24, 168].map(n => ({ value: String(n), label: n === 168 ? "Weekly" : `Every ${n} hours` }))} />
          <FilterSelect label="Reference run" value={value.reference_run_id ?? ""} onChange={v => setDraft({ ...value, reference_run_id: v || null })} options={[{ value: "", label: "No reference — record metrics only" }, ...history.filter(r => r.status === "completed").map(r => ({ value: r.id, label: new Date(r.created_at).toLocaleString() }))]} />
        </div>
        <div className="grid gap-3 sm:grid-cols-3">{([['quality_drop_pp', 'Pass rate drop (points)', 100], ['latency_increase_percent', 'Latency rise (%)', 1000], ['cost_increase_percent', 'Cost rise (%)', 1000]] as const).map(([key, label, max]) => <label key={key} className="space-y-1.5">{label}<Input type="number" min={0} max={max} step="any" value={value.quality_limits[key]} onChange={e => setDraft({ ...value, quality_limits: { ...value.quality_limits, [key]: Number(e.target.value) } })} /></label>)}</div>
        <p className="leading-5 text-muted-foreground">The reference must contain the same questions and configurations. Warnings appear in run history and can be delivered through the evaluation.regressed webhook. Unmeasured metrics are excluded. Run history holds 20 runs; delete old runs to keep schedules running.</p>
        <Button size="sm" variant="outline" onClick={() => void save()}>Save schedule</Button>
        {data?.next_run_at && <p>Next check: {new Date(data.next_run_at).toLocaleString()}</p>}
        {data?.last_error && <p role="alert" className="text-destructive">{data.last_error}</p>}
      </fieldset>}
      {message && <p role="status">{message}</p>}
    </div>
  </details>
}
