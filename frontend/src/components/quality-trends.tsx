"use client"

import { useState } from "react"
import Link from "next/link"
import useSWR from "swr"
import { ArrowRightIcon, ArrowsClockwiseIcon, ChartLineUpIcon, ChatCircleTextIcon, FlaskIcon } from "@phosphor-icons/react/dist/ssr"
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart"
import { FilterSelect } from "@/components/filter-select"
import { LiveQualityCharts } from "@/components/live-quality-charts"
import { fetcher, isSessionExpired } from "@/lib/api"
import { evaluationChange, qualityTrendsKey, type EvaluationTrendsReport, type QualityTrendsReport } from "@/lib/quality-trends"

const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 })
const percent = (value: number | null) => value == null ? "Not measured" : `${number.format(value)}%`
const day = (value: string) => new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
const stamp = (value: string) => new Date(value).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "UTC" })
const change = (value: number | null, suffix: string) => value == null ? "More comparable measurements needed" : `${value > 0 ? "+" : ""}${number.format(value)} percentage points ${suffix}`

function Loading() {
  return <div role="status" aria-label="Loading quality trends" className="space-y-4"><div className="grid grid-cols-2 gap-3"><Skeleton className="h-28 rounded-xl" /><Skeleton className="h-28 rounded-xl" /></div><Skeleton className="h-52 rounded-xl" /></div>
}
function Retry({ onRetry, stale }: { onRetry: () => void; stale: boolean }) {
  return <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-xs"><p>Could not refresh trends.{stale ? " Showing the last available snapshot." : " Please try again."}</p><Button size="sm" variant="outline" onClick={onRetry}>Retry</Button></div>
}
function TrendChart({ values, label, color }: { values: { date: string; value: number | null }[]; label: string; color: string }) {
  const measured = values.filter(point => point.value != null).length
  if (measured < 2) return <div className="flex min-h-40 items-center justify-center rounded-lg bg-muted/20 p-6 text-center text-xs leading-5 text-muted-foreground">{measured ? "One measurement available. The trend appears after another measurement." : "No measurements in this period yet."}</div>
  return <ChartContainer config={{ value: { label, color } }} className="h-48 w-full aspect-auto" aria-label={`${label} trend`}>
    <LineChart accessibilityLayer data={values} margin={{ top: 10, right: 12, bottom: 4, left: -18 }}>
      <CartesianGrid vertical={false} /><XAxis dataKey="date" tickFormatter={day} minTickGap={36} tickLine={false} axisLine={false} tickMargin={10} />
      <YAxis domain={[0, 100]} ticks={[0, 50, 100]} tickFormatter={value => `${value}%`} tickLine={false} axisLine={false} />
      <ChartTooltip content={<ChartTooltipContent labelFormatter={value => stamp(String(value))} formatter={value => <span className="font-medium tabular-nums">{percent(Number(value))}</span>} />} />
      <Line type="linear" dataKey="value" stroke="var(--color-value)" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} connectNulls={false} isAnimationActive={false} />
    </LineChart>
  </ChartContainer>
}

function LiveTrends({ days, project }: { days: string; project: string }) {
  const { data, error, mutate, isValidating } = useSWR<QualityTrendsReport>(qualityTrendsKey(days, project), fetcher, { refreshInterval: 60_000 })
  const current = data?.current
  return <div className="space-y-4">
    {error && !isSessionExpired(error) && <Retry stale={!!data} onRetry={() => void mutate()} />}
    {!data && !error && <Loading />}
    {data && current && <>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground"><p>{day(current.start)} – {day(new Date(new Date(current.end).getTime() - 86400000).toISOString())} · Complete UTC days · {number.format(current.queries)} {current.complete ? "queries" : "sampled queries"}</p><Button size="icon-sm" variant="ghost" aria-label="Refresh live quality trends" disabled={isValidating} onClick={() => void mutate()}><ArrowsClockwiseIcon className="size-4" /></Button></div>
      {data.limited && <p className="rounded-lg border bg-muted/20 p-3 text-xs leading-5 text-muted-foreground">Showing the latest {data.scan_limit.toLocaleString()} retained queries. Comparisons are hidden where history is incomplete. Choose a project or shorter period for more coverage.</p>}
      {current.queries === 0 && !data.limited && <p className="rounded-lg bg-muted/20 p-3 text-xs leading-5 text-muted-foreground">No recorded queries in these {days} complete days. Today’s activity appears tomorrow. Preview chart shows an example of helpful feedback.</p>}
      <LiveQualityCharts key={`${project}:${days}`} data={data} days={days} />
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs text-muted-foreground">Document matches are a review signal, not an answer-accuracy score.</p><Button asChild variant="outline" size="sm"><Link href={`/knowledge-gaps${project ? `?project=${encodeURIComponent(project)}` : ""}`}>Review gaps<ArrowRightIcon /></Link></Button></div>
      <details className="text-xs leading-5 text-muted-foreground"><summary className="w-fit cursor-pointer rounded-sm font-medium text-foreground focus-visible:outline-2">Daily measurements</summary><div className="mt-3 max-h-72 overflow-auto rounded-lg border"><table className="w-full text-left text-xs"><caption className="sr-only">Daily quality measurements in UTC</caption><thead><tr className="border-b bg-muted/30"><th className="p-3">Day</th><th className="p-3">Helpful / rated</th><th className="p-3">Low / measured</th></tr></thead><tbody>{data.daily.map(row => <tr key={row.date} className="border-b last:border-0"><td className="whitespace-nowrap p-3">{day(row.date)}</td><td className="p-3">{row.complete ? `${row.helpful} / ${row.rated}` : "Incomplete"}</td><td className="p-3">{row.complete ? `${row.low_match} / ${row.measured}` : "Incomplete"}</td></tr>)}</tbody></table></div></details>
      <details className="text-xs leading-5 text-muted-foreground"><summary className="w-fit cursor-pointer rounded-sm font-medium text-foreground focus-visible:outline-2">How live trends work</summary><div className="mt-2 space-y-2"><p>Feedback uses current ratings on queries created in each period. Unrated answers are excluded from the helpful percentage. Comparisons need at least five relevant measurements in each equal period. Today is excluded; values reflect retained query history.</p><p>Low document matches are uncached queries with similarity below {data.weak_similarity_threshold.toFixed(2)}. Recognized casual conversation and obvious keyboard noise are excluded. {current.document_queries - current.measured} document queries have no similarity measurement. Missing measurements leave gaps in the chart.</p><p>These are observed changes, not proof of improvement or regression. Traffic, models, documents, and who submits feedback can change the results.</p></div></details>
    </>}
  </div>
}

function EvaluationTrends({ days, project }: { days: string; project: string }) {
  const { data, error, mutate, isValidating } = useSWR<EvaluationTrendsReport>(project ? qualityTrendsKey(days, project, true) : null, fetcher, { refreshInterval: 60_000 })
  const [selection, setSelection] = useState("")
  const [variant, setVariant] = useState("0")
  const series = data?.series.find(row => row.key === selection) ?? data?.series[0]
  const chosenVariant = Number(variant) < (series?.models.length ?? 0) ? Number(variant) : 0
  const points = series?.points.filter(point => point.variant === chosenVariant) ?? []
  const latest = points.at(-1)
  if (!project) return <p className="py-8 text-center text-sm text-muted-foreground">Create a project to start tracking evaluation runs.</p>
  return <div className="space-y-4">
    {error && !isSessionExpired(error) && <Retry stale={!!data} onRetry={() => void mutate()} />}
    {!data && !error && <Loading />}
    {data && <>
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs text-muted-foreground">Completed runs · Last {days} days · Includes archived results</p><Button size="icon-sm" variant="ghost" aria-label="Refresh evaluation trends" disabled={isValidating} onClick={() => void mutate()}><ArrowsClockwiseIcon className="size-4" /></Button></div>
      {data.limited && <p className="rounded-lg border p-3 text-xs text-muted-foreground">Showing the latest {data.run_limit} completed runs in this period.</p>}
      {!series || !latest ? <div className="space-y-3 rounded-xl border p-8 text-center"><FlaskIcon className="mx-auto size-7 text-muted-foreground" aria-hidden="true" /><p className="text-sm font-medium">No completed evaluations in this period</p><p className="text-xs leading-5 text-muted-foreground">Run a saved test set in Playground’s Evaluator to start a quality history.</p></div> : <>
        <div className="grid min-w-0 gap-3 sm:grid-cols-2"><FilterSelect label="Comparable test set" value={series.key} onChange={setSelection} options={data.series.map(row => ({ value: row.key, label: `${row.cases} ${row.cases === 1 ? "question" : "questions"} · ${row.points.length / row.models.length} ${row.points.length === row.models.length ? "run" : "runs"} · ${day(row.points.at(-1)!.created_at)}` }))} /><FilterSelect label="Configuration" value={String(chosenVariant)} onChange={setVariant} options={series.models.map((model, index) => ({ value: String(index), label: `${index === 0 ? "A" : "B"} · ${model}` }))} /></div>
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="min-w-0 space-y-2 rounded-xl border p-4"><h3 className="text-xs text-muted-foreground">Latest check pass rate</h3><p className="text-2xl font-semibold tabular-nums">{percent(latest.pass_percent)}</p><p className="text-xs leading-5 text-muted-foreground">{latest.passed} / {latest.checked} checked · {latest.unscored} unscored · {latest.errors} errors</p></div>
          <div className="min-w-0 space-y-2 rounded-xl border p-4"><h3 className="text-xs text-muted-foreground">Average response time</h3><p className="break-words text-2xl font-semibold tabular-nums">{latest.latency_ms == null ? "Not measured" : `${number.format(latest.latency_ms / 1000)} s`}</p><p className="text-xs text-muted-foreground">Per case in the latest run</p></div>
          <div className="min-w-0 space-y-2 rounded-xl border p-4"><h3 className="text-xs text-muted-foreground">Average recorded cost</h3><p className="break-words text-2xl font-semibold tabular-nums">{latest.cost_usd == null ? "Not measured" : latest.cost_usd > 0 && latest.cost_usd < 0.000001 ? "< $0.000001" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 6 }).format(latest.cost_usd)}</p><p className="text-xs text-muted-foreground">Per case in the latest run</p></div>
        </div>
        <div className="space-y-3 rounded-xl border p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-medium">Check pass rate over time</h3><span className="text-xs text-muted-foreground">{points.length} comparable {points.length === 1 ? "run" : "runs"}</span></div><p className="text-xs text-muted-foreground">{change(evaluationChange(latest, points.at(-2)), "vs previous comparable run")}</p>{points.every(point => point.checked === 0) ? <p className="rounded-lg bg-muted/20 p-6 text-center text-xs leading-5 text-muted-foreground">Add expected answer or source checks in Evaluator, then rerun the test set to measure pass rate.</p> : <TrendChart label="Evaluation check pass rate" color="var(--chart-1)" values={points.map(point => ({ date: point.created_at, value: point.checked === point.expected && point.errors === 0 ? point.pass_percent : null }))} />}</div>
        <details className="text-xs leading-5 text-muted-foreground"><summary className="w-fit cursor-pointer rounded-sm font-medium text-foreground focus-visible:outline-2">Run measurements</summary><div className="mt-3 max-h-72 overflow-auto rounded-lg border"><table className="w-full text-left text-xs"><caption className="sr-only">Comparable evaluation runs</caption><thead><tr className="border-b"><th className="p-3">Run (UTC)</th><th className="p-3">Passed / checked</th><th className="p-3">Unscored / errors</th></tr></thead><tbody>{[...points].reverse().map(point => <tr key={point.id} className="border-b last:border-0"><td className="p-3">{stamp(point.created_at)}<span className="block text-[10px]">{point.id.slice(0, 8)}{point.archived ? " · Archived" : ""}</span></td><td className="p-3">{point.passed} / {point.checked}</td><td className="p-3">{point.unscored} / {point.errors}</td></tr>)}</tbody></table></div></details>
      </>}
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="max-w-xl text-xs leading-5 text-muted-foreground">Only identical saved questions, checks, and configurations share a trend. Charts and changes require all cases to be checked. Changes in indexed documents can affect results.</p><Button asChild size="sm" variant="outline"><Link href={`/projects/${encodeURIComponent(project)}?tab=playground`}>Open Playground<ArrowRightIcon /></Link></Button></div>
    </>}
  </div>
}

export function QualityTrends({ projects }: { projects: { id: string; name: string }[] }) {
  const [view, setView] = useState("live")
  const [days, setDays] = useState("30")
  const [project, setProject] = useState("")
  const selected = view === "evaluations" ? project || projects[0]?.id || "" : project
  return <section aria-label="Quality trends" className="min-w-0 space-y-4 rounded-xl border bg-card p-4 sm:p-5">
    <div className="space-y-1"><h2 className="flex items-center gap-2 text-sm font-semibold"><ChartLineUpIcon className="size-4 text-muted-foreground" aria-hidden="true" />Quality trends</h2><p className="text-xs leading-5 text-muted-foreground">Follow answer feedback, document matches, and test results over time.</p></div>
    <Tabs value={view} onValueChange={setView} className="min-w-0 gap-4">
      <div className="flex min-w-0 flex-wrap items-end justify-between gap-3"><TabsList aria-label="Quality trend source" className="max-w-full"><TabsTrigger value="live" className="gap-1.5"><ChatCircleTextIcon className="size-4" />Live answers</TabsTrigger><TabsTrigger value="evaluations" className="gap-1.5"><FlaskIcon className="size-4" />Evaluations</TabsTrigger></TabsList><div className="grid w-full min-w-0 grid-cols-[minmax(0,1fr)_7rem] gap-2 sm:w-80"><FilterSelect label="Trend project" value={selected} onChange={setProject} options={[...(view === "live" ? [{ value: "", label: "All projects" }] : []), ...projects.map(row => ({ value: row.id, label: row.name }))]} /><FilterSelect label="Trend period" value={days} onChange={setDays} options={[7, 30, 90].map(value => ({ value: String(value), label: `${value} days` }))} /></div></div>
      <TabsContent value="live" className="min-w-0"><LiveTrends days={days} project={project} /></TabsContent>
      <TabsContent value="evaluations" className="min-w-0"><EvaluationTrends key={`${selected}:${days}`} days={days} project={selected} /></TabsContent>
    </Tabs>
  </section>
}
