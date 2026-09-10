"use client"
import useSWR from "swr"
import { fetcher, isSessionExpired } from "@/lib/api"
import { queryLatency } from "@/lib/query-explorer"
type Report = { requests: number; errors: number; rejected: number; error_percent: number | null; p95_latency_ms: number | null; p95_first_token_ms: number | null; limited: boolean; checked_at: string; workers_available: boolean; warnings: { kind: string; message: string }[]; queues: Record<string, { count: number; oldest_seconds: number | null }> }
export function OperationsPanel({ compact = false }: { compact?: boolean }) {
  const { data, error, mutate } = useSWR<Report>("/api/account/operations", fetcher, { refreshInterval: 30000, revalidateOnFocus: false })
  if (compact) return data?.warnings.length ? <div role="alert" className="rounded-xl border border-amber-500/30 bg-card p-3 text-xs"><p className="font-medium">Operations need attention</p><p className="mt-1 leading-5 text-muted-foreground">{data.warnings[0].message} <a className="underline" href="/settings/usage#operations">View in Usage</a></p></div> : null
  return <details id="operations" className="mb-4 rounded-xl border bg-card p-4"><summary className="cursor-pointer text-sm font-medium">Operations <span className="ml-2 text-xs font-normal text-muted-foreground">{data ? data.warnings.length ? `${data.warnings.length} ${data.warnings.length === 1 ? "needs" : "need"} attention` : "Healthy" : "Measurements"}</span></summary>
    <div className="mt-4 space-y-4">
      {error && !isSessionExpired(error) && <p role="alert" className="text-xs">Could not load operations. <button className="underline" onClick={() => void mutate()}>Retry</button></p>}
      {data && <><p className="text-xs leading-5 text-muted-foreground">Latest {data.requests.toLocaleString()} authenticated API and project requests in 24 hours{data.limited ? " (limited to 5,000)" : ""}. Measurements arrive asynchronously. Alerts use the latest 15 minutes; latency and failure alerts require 20 requests.</p>
        <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[["Failed / disconnected", `${data.errors} (${data.error_percent == null ? "not measured" : `${data.error_percent}%`})`], ["Rejected requests (4xx)", String(data.rejected)], ["p95 latency", queryLatency(data.p95_latency_ms)], ["p95 first token", queryLatency(data.p95_first_token_ms)]].map(([label, value]) => <div key={label} className="min-w-0 rounded-lg border p-3"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-2 break-words text-sm font-medium tabular-nums">{value}</dd></div>)}</dl>
        <div className="divide-y rounded-lg border">{Object.entries(data.queues).map(([name, q]) => <div key={name} className="flex flex-wrap justify-between gap-2 p-3 text-xs"><span className="capitalize">{name}</span><span className="text-muted-foreground">{q.count} active / queued{q.oldest_seconds != null ? ` · oldest ${Math.ceil(q.oldest_seconds / 60)} min` : ""}</span></div>)}</div>
        {data.warnings.length > 0 && <ul role="alert" className="space-y-2 rounded-lg border border-amber-500/30 p-3 text-xs leading-5">{data.warnings.map(w => <li key={w.kind}>{w.message}</li>)}</ul>}
        <p className="text-xs text-muted-foreground">Workers: {data.workers_available ? "available" : "not confirmed"} · Checked <time dateTime={data.checked_at} suppressHydrationWarning>{new Date(data.checked_at).toLocaleTimeString()}</time>. Missing measurements remain unreported.</p>
      </>}
    </div>
  </details>
}
