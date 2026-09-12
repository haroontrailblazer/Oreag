"use client"

import { useState } from "react"
import useSWR, { useSWRConfig } from "swr"
import { BellIcon, PlusIcon, PencilSimpleIcon, TrashIcon, WalletIcon } from "@phosphor-icons/react/dist/ssr"
import { BudgetForecast, BudgetForecastMethod, BudgetForecastSkeleton } from "@/components/settings/budget-forecast"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { FilterSelect } from "@/components/filter-select"
import { api, fetcher, isSessionExpired } from "@/lib/api"
import { BUDGETS_KEY, BUDGET_ALERTS_KEY, BUDGET_REFRESH_MS, budgetMoney, type BudgetsReport, type UsageBudget } from "@/lib/budgets"
import type { Project } from "@/lib/types"
import { cn } from "@/lib/utils"

type Draft = {project_id: string; amount: string; warning: string; enabled: boolean; revision: number}
const empty: Draft = {project_id:"",amount:"",warning:"80",enabled:true,revision:0}

export function UsageBudgets() {
  // Capture receipt time alongside refreshed month-to-date totals. A later
  // UI-only render must not extrapolate an old total over a longer interval.
  const [asOf, setAsOf] = useState(() => new Date())
  const {data, error, mutate: refresh} = useSWR<BudgetsReport>(BUDGETS_KEY, fetcher, {
    refreshInterval:BUDGET_REFRESH_MS,
    onSuccess: () => setAsOf(new Date()),
  })
  const {data: projects} = useSWR<Project[]>("/api/projects", fetcher)
  const {mutate} = useSWRConfig()
  const [draft, setDraft] = useState<Draft | null>(null)
  const [editing, setEditing] = useState<UsageBudget | null>(null)
  const [removing, setRemoving] = useState<UsageBudget | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  const [failure, setFailure] = useState("")
  const [showAlerts, setShowAlerts] = useState(false)
  function edit(budget?: UsageBudget) {
    setEditing(budget ?? null); setFailure(""); setMessage("")
    setDraft(budget ? {project_id:budget.project_id ?? "",amount:String(budget.amount_usd),warning:String(budget.warning_percent),enabled:budget.enabled,revision:budget.revision} : {...empty,project_id:scopes[0]?.value ?? ""})
  }
  async function sync(result?: BudgetsReport) {
    if (result) await refresh(result, {revalidate:false}); else await refresh()
    setAsOf(new Date())
    void mutate(BUDGET_ALERTS_KEY)
  }
  function failed(err: unknown) { if (!isSessionExpired(err)) setFailure(err instanceof Error ? err.message : "Could not update this budget.") }
  async function save(event: React.FormEvent) {
    event.preventDefault(); if (!draft || busy) return
    setBusy(true); setFailure("")
    try {
      const result = await api<BudgetsReport>(BUDGETS_KEY, {method:"PUT",body:JSON.stringify({project_id:draft.project_id || null,amount_usd:draft.amount,warning_percent:Number(draft.warning),enabled:draft.enabled,revision:draft.revision})})
      await sync(result); setDraft(null); setMessage("Budget saved. Requests will continue at every threshold.")
    } catch(err) { failed(err) } finally { setBusy(false) }
  }
  async function remove() {
    if (!removing || busy) return
    setBusy(true); setFailure("")
    try { await api(`${BUDGETS_KEY}/${removing.id}`, {method:"DELETE"}); await sync(); setRemoving(null); setMessage("Budget and its alerts removed.") } catch(err) {failed(err)} finally {setBusy(false)}
  }
  async function read(id?: string) {
    if (busy) return
    setBusy(true); setFailure("")
    try {await api(id ? `${BUDGET_ALERTS_KEY}/${id}/read` : `${BUDGET_ALERTS_KEY}/read-all`, {method:"POST"}); await sync()} catch(err) {failed(err)} finally {setBusy(false)}
  }
  const scopes = [{value:"",label:"Entire account"},...(projects ?? []).map(p=>({value:p.id,label:p.name}))]
    .filter(option=>!data?.budgets.some(b=>(b.project_id ?? "")===option.value))
  const month = data ? new Intl.DateTimeFormat("en", {month:"long",year:"numeric",timeZone:"UTC"}).format(new Date(data.period_start)) : "Monthly"
  return <section aria-label="Budgets and alerts" className="relative mb-6 min-w-0 space-y-4 rounded-xl border bg-card p-4 sm:p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="flex items-center gap-2 text-sm font-semibold"><WalletIcon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />Budgets &amp; alerts</h2><p className="mt-1 text-xs text-muted-foreground">{month} · USD · Warning only</p></div>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" aria-expanded={showAlerts} aria-controls="budget-alert-list" onClick={()=>setShowAlerts(!showAlerts)}><BellIcon/>Alerts{data && data.unread_count > 0 && <span className="rounded-full bg-amber-500/15 px-1.5 text-amber-700 dark:text-amber-400">{data.unread_count}</span>}</Button>
        <Button variant="outline" size="sm" disabled={!data || data.budgets.length >= 26 || !scopes.length} onClick={()=>edit()}><PlusIcon/>Add budget</Button>
      </div>
    </div>
    {error && !isSessionExpired(error) && <div role="alert" className="flex flex-wrap items-center gap-2 text-xs text-destructive">Could not load budgets.<Button size="sm" variant="ghost" onClick={()=>void refresh()}>Retry</Button></div>}
    {failure && !draft && !removing && <p role="alert" className="text-xs text-destructive">{failure}</p>}
    {message && <p role="status" className="text-xs text-muted-foreground">{message}</p>}
    {!data && !error && <BudgetForecastSkeleton />}
    {data && !data.budgets.length && <p className="text-sm leading-relaxed text-muted-foreground">Set a monthly budget for your account or a project to see a month-end forecast. Get an early warning and an alert at 100% of recorded spend.</p>}
    {!!data?.budgets.length && <div className="grid gap-3 xl:grid-cols-2">{data.budgets.map(budget=><article key={budget.id} className="min-w-0 space-y-3 rounded-lg border p-3">
      <div className="flex items-center justify-between gap-2"><h3 className="truncate text-sm font-medium" title={budget.project_name ?? "Entire account"}>{budget.project_name ?? "Entire account"}</h3><div className="flex shrink-0"><Button variant="ghost" size="icon-sm" aria-label={`Edit ${budget.project_name ?? "account"} budget`} onClick={()=>edit(budget)}><PencilSimpleIcon/></Button><Button variant="ghost" size="icon-sm" aria-label={`Remove ${budget.project_name ?? "account"} budget`} onClick={()=>{setRemoving(budget);setFailure("")}}><TrashIcon/></Button></div></div>
      <div className="flex flex-wrap items-baseline justify-between gap-2"><p className="min-w-0 break-words text-lg font-semibold tabular-nums [overflow-wrap:anywhere]">{budgetMoney(budget.spent_usd)} <span className="text-xs font-normal text-muted-foreground">/ {budgetMoney(budget.amount_usd)}</span></p><span className={cn("text-xs",budget.state==="exceeded"?"text-red-600 dark:text-red-400":budget.state==="warning"?"text-amber-700 dark:text-amber-400":"text-muted-foreground")}>{budget.state==="paused"?"Alerts paused":budget.state==="unmeasured"?"Cost unavailable":budget.state==="exceeded"?"Budget reached":budget.state==="warning"?"Near budget":"Within recorded budget"}</span></div>
      <div role="progressbar" aria-label={`${budget.project_name ?? "Account"} recorded budget usage`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={budget.percent_used===null?undefined:Math.min(100,Number(budget.percent_used.toFixed(1)))} aria-valuetext={budget.percent_used===null?"Not measured":`${budget.percent_used.toFixed(1)}% of budget`} className="h-1.5 overflow-hidden rounded-full bg-muted"><div className={cn("h-full rounded-full",budget.state==="paused"?"bg-muted-foreground":budget.state==="exceeded"?"bg-red-500":budget.state==="warning"?"bg-amber-500":"bg-foreground/70")} style={{width:`${Math.min(100,Math.max(0,budget.percent_used ?? 0))}%`}}/></div>
      <p className="text-xs text-muted-foreground">Warn at {budget.warning_percent}% and 100%. {budget.unpriced_requests>0?`${budget.unpriced_requests} ${budget.unpriced_requests === 1 ? "event has" : "events have"} incomplete cost data; alerts use recorded spend only.`:"Based on recorded model and embedding costs."}</p>
      <BudgetForecast budget={budget} period={data} asOf={asOf} refreshFailed={!!error} />
    </article>)}</div>}
    {!!data?.budgets.length && <div className="space-y-2">
      <p className="text-xs leading-relaxed text-muted-foreground">Month-end estimates assume this month’s average spending pace continues. Account and project budgets overlap; their forecasts should not be added together.</p>
      <BudgetForecastMethod />
    </div>}
    <p className="text-xs leading-5 text-muted-foreground">Resets on the first of each month (UTC), independently of the date range above. API, Playground, ingestion and evaluation spend count. Alerts appear here and on Usage in the sidebar; requests keep running.</p>
    {showAlerts && <div id="budget-alert-list" className="space-y-3 border-t pt-4"><div className="flex items-center justify-between gap-2"><h3 className="text-sm font-medium">Recent alerts</h3><Button size="sm" variant="ghost" disabled={busy || !data?.unread_count} onClick={()=>void read()}>Mark all read</Button></div>{data?.alerts.length ? <ul className="max-h-80 space-y-2 overflow-y-auto overscroll-contain">{data.alerts.map(alert=><li key={alert.id} className={cn("flex flex-wrap items-start justify-between gap-2 rounded-lg border p-3",!alert.read_at && "border-amber-500/40")}><div className="min-w-0 space-y-1 text-xs"><p className="break-words font-medium">{alert.project_name ?? "Entire account"} reached {alert.threshold_percent}%</p><p className="text-muted-foreground">{budgetMoney(alert.spent_usd)} recorded against {budgetMoney(alert.amount_usd)} · {alert.period_start.slice(0,7)}</p></div>{!alert.read_at ? <Button size="sm" variant="ghost" disabled={busy} onClick={()=>void read(alert.id)}>Mark read</Button>:<span className="text-xs text-muted-foreground">Read</span>}</li>)}</ul>:<p className="text-xs text-muted-foreground">No alerts yet. Budget checks run in the background about once a minute.</p>}</div>}
    <Dialog open={draft!==null} onOpenChange={open=>{if(!open && !busy)setDraft(null)}}><DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto"><DialogHeader><DialogTitle>{editing?"Edit budget":"Add budget"}</DialogTitle><DialogDescription>Monthly USD budget. Alerts warn you without stopping requests.</DialogDescription></DialogHeader>{draft && <form onSubmit={save} className="space-y-4"><fieldset disabled={busy} className="space-y-4">{editing ? <p className="text-sm">{editing.project_name ?? "Entire account"}</p> : <FilterSelect label="Budget scope" value={draft.project_id} options={scopes} onChange={project_id=>setDraft({...draft,project_id})}/>}<label className="block space-y-1.5 text-xs">Monthly budget (USD)<Input aria-label="Monthly budget (USD)" type="number" inputMode="decimal" min="0.01" max="1000000" step="0.01" required placeholder="100.00" value={draft.amount} onChange={e=>setDraft({...draft,amount:e.target.value})}/></label><label className="block space-y-1.5 text-xs">Early warning (%)<Input aria-label="Early warning (%)" type="number" inputMode="numeric" min="1" max="99" step="1" required value={draft.warning} onChange={e=>setDraft({...draft,warning:e.target.value})}/></label><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.enabled} onChange={e=>setDraft({...draft,enabled:e.target.checked})}/>Enable alerts</label></fieldset>{failure && <p role="alert" className="text-xs text-destructive">{failure}</p>}<div className="flex justify-end gap-2"><Button variant="outline" type="button" disabled={busy} onClick={()=>setDraft(null)}>Cancel</Button><Button type="submit" disabled={busy}>{busy?"Saving…":"Save budget"}</Button></div></form>}</DialogContent></Dialog>
    <Dialog open={removing!==null} onOpenChange={open=>{if(!open && !busy)setRemoving(null)}}><DialogContent><DialogHeader><DialogTitle>Remove budget?</DialogTitle><DialogDescription>This removes the {removing?.project_name ?? "account"} budget and its saved alerts. Usage records remain available.</DialogDescription></DialogHeader>{failure && <p role="alert" className="text-xs text-destructive">{failure}</p>}<div className="flex justify-end gap-2"><Button variant="outline" disabled={busy} onClick={()=>setRemoving(null)}>Cancel</Button><Button variant="destructive" disabled={busy} onClick={()=>void remove()}>Remove budget</Button></div></DialogContent></Dialog>
  </section>
}
