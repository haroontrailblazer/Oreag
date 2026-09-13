"use client"
import { useState } from "react"
import Link from "next/link"
import { ArrowsClockwiseIcon, ClockIcon, FloppyDiskIcon } from "@phosphor-icons/react/dist/ssr"
import useSWR from "swr"
import { api, fetcher } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { ChangeChecks } from "@/components/change-checks"
import { FilterSelect } from "@/components/filter-select"
import type { EvaluationRun } from "@/lib/evaluation"
import styles from "./evaluation-schedule.module.css"

type Schedule = { revision: number; enabled: boolean; on_changes: boolean; change_due_at: string | null; interval_hours: number; reference_run_id: string | null; quality_limits: { quality_drop_pp: number; latency_increase_percent: number; cost_increase_percent: number }; next_run_at: string | null; last_run_at: string | null; last_error: string | null }
export function EvaluationSchedule({ base, history, showChangeChecks = true }: { base: string; history: EvaluationRun[]; showChangeChecks?: boolean }) {
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
  return <>
    <Card role="region" aria-label="Automatic checks" className="min-w-0 gap-5">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <CardTitle role="heading" aria-level={3} className="flex items-center gap-2 text-sm"><ClockIcon className="size-4 text-muted-foreground" aria-hidden="true" />Automatic checks</CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="outline">{!data ? error ? "Unavailable" : "Loading" : data.enabled && data.on_changes ? "Scheduled + after changes" : data.on_changes ? "After changes" : data.enabled ? "Scheduled" : "Off"}</Badge>
            <Button size="icon-sm" variant="ghost" title="Reload settings" aria-label="Reload automatic checks" disabled={busy} onClick={() => { setDraft(null); setMessage(""); void mutate() }}><ArrowsClockwiseIcon aria-hidden="true" /></Button>
          </div>
        </div>
        <CardDescription className="text-xs leading-5">Choose when to run your saved tests and when to flag a regression.</CardDescription>
      </CardHeader>
      <CardContent className={styles.content}>
        {error && <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-xs"><p>Could not load schedule.</p><Button size="sm" variant="outline" onClick={() => void mutate()}>Retry</Button></div>}
        {!value && !error && <div role="status" aria-label="Loading automatic checks" className="space-y-3"><Skeleton className="h-24 rounded-lg" /><Skeleton className="h-24 rounded-lg" /></div>}
        {value && <fieldset disabled={busy} className="min-w-0 space-y-5">
          <legend className="sr-only">Automatic check settings</legend>
          <div className={styles.triggers}>
            <label className={styles.trigger}><span className="min-w-0 space-y-1"><span className="block text-sm font-medium">Run on a schedule</span><span className="block text-xs leading-5 text-muted-foreground">Run at a regular interval, even when the project has not changed.</span></span><Switch aria-label="Run on a schedule" checked={value.enabled} onCheckedChange={enabled => setDraft({ ...value, enabled })} /></label>
            <label className={styles.trigger}><span className="min-w-0 space-y-1"><span className="block text-sm font-medium">Run after changes</span><span className="block text-xs leading-5 text-muted-foreground">Check document, memory, and answer-setting changes. Waits for indexing and combines rapid edits.</span></span><Switch aria-label="Run after changes" checked={value.on_changes ?? false} onCheckedChange={on_changes => setDraft({ ...value, on_changes })} /></label>
          </div>
          {value.enabled && <div className={styles.options}>
            <FilterSelect label="Check frequency" value={String(value.interval_hours)} onChange={v => setDraft({ ...value, interval_hours: Number(v) })} options={[6, 12, 24, 168].map(n => ({ value: String(n), label: n === 168 ? "Weekly" : `Every ${n} hours` }))} />
            <FilterSelect label="Reference run" value={value.reference_run_id ?? ""} onChange={v => setDraft({ ...value, reference_run_id: v || null })} options={[{ value: "", label: "No reference — record metrics only" }, ...(retained ?? history).filter(r => r.status === "completed").map(r => ({ value: r.id, label: new Date(r.created_at).toLocaleString() }))]} />
          </div>}
          <div className="space-y-3 border-t pt-5">
            <div className="space-y-1"><h4 className="text-sm font-medium">Warning thresholds</h4><p className="text-xs leading-5 text-muted-foreground">Flag changes above these limits. Scheduled checks use your reference run; change checks use the latest completed run with the same questions.</p></div>
            <div className={styles.thresholds}>{([['quality_drop_pp', 'Pass rate drop (points)', 100], ['latency_increase_percent', 'Latency rise (%)', 1000], ['cost_increase_percent', 'Cost rise (%)', 1000]] as const).map(([key, label, max]) => <label key={key} className="flex min-w-0 flex-col gap-2 text-xs text-muted-foreground"><span>{label}</span><Input type="number" min={0} max={max} step="any" value={value.quality_limits[key]} onChange={e => setDraft({ ...value, quality_limits: { ...value.quality_limits, [key]: Number(e.target.value) } })} /></label>)}</div>
            <p className="text-xs leading-5 text-muted-foreground">Warnings appear in run history. Missing measurements are excluded from comparisons.</p>
          </div>
          <div className="space-y-2 rounded-lg bg-muted/40 p-3 text-xs leading-5 text-muted-foreground">
            <p>Save your test set before enabling checks. Runs continue after you close the browser, use an isolated knowledge snapshot, and incur normal provider charges.</p>
            {value.on_changes && <p>Change checks use the current project configuration and the questions saved with these settings. Save Automatic checks again after editing your test set.</p>}
          </div>
          <div className={styles.footer}>
            <p className="text-xs text-muted-foreground">{draft ? "You have unsaved check settings." : "Changes apply when you save."}</p>
            <div className={styles.actions}><Button size="sm" variant="outline" asChild><Link href={`/projects/${base.split("/")[3]}?tab=playground`}>Edit saved tests</Link></Button><Button size="sm" onClick={() => void save()}><FloppyDiskIcon aria-hidden="true" />{busy ? "Saving…" : "Save automatic checks"}</Button></div>
          </div>
          {(data?.next_run_at || data?.change_due_at || data?.last_error) && <div className="space-y-2 text-xs leading-5 text-muted-foreground">
            {data?.next_run_at && <p>Next scheduled check: {new Date(data.next_run_at).toLocaleString()}</p>}
            {data?.change_due_at && <p>Change detected. A check will start after indexing and any active run finish.</p>}
            {data?.last_error && <p role="alert" className="text-destructive">{data.last_error}</p>}
          </div>}
        </fieldset>}
        {message && <p role="status" className="text-xs leading-5">{message}</p>}
      </CardContent>
    </Card>
    {showChangeChecks && <ChangeChecks base={base} />}
  </>
}
