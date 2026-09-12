"use client"

import { FilesIcon, ThumbsUpIcon } from "@phosphor-icons/react/dist/ssr"
import { Area, AreaChart, Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart"
import { qualityChange, type QualityTrendsReport } from "@/lib/quality-trends"

const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 })
const percent = (value: number | null) => value == null ? "Not measured" : `${number.format(value)}%`
const day = (value: string) => new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
type DailyQuality = QualityTrendsReport["daily"][number]
type FeedbackPoint = { date: string; helpful: number; rated: number; value: number | null }

function PeriodChange({ value, days }: { value: number | null; days: string }) {
  if (value == null) return null
  return <p className="text-xs leading-5 text-muted-foreground">{value > 0 ? "+" : ""}{number.format(value)} percentage points vs previous {days} days</p>
}

function HelpfulFeedbackChart({ points }: { points: FeedbackPoint[] }) {
  const measured = points.filter(point => point.value != null).length
  if (!measured) return <div className="flex min-h-52 flex-col items-center justify-center gap-2 rounded-lg bg-muted/20 p-5 text-center">
    <ThumbsUpIcon className="size-6 text-muted-foreground" aria-hidden="true" />
    <p className="text-xs font-medium">No rated answers in this period</p>
    <p className="max-w-64 text-xs leading-5 text-muted-foreground">Rate an answer in Playground or send feedback from your app.</p>
  </div>
  return <div className="space-y-2">
    <p className="text-[11px] text-muted-foreground">Helpful answers (% of daily ratings)</p>
    <ChartContainer config={{ value: { label: "Helpful feedback", color: "var(--chart-1)" } }} className="h-48 w-full aspect-auto" aria-label="Helpful feedback by day">
      <AreaChart accessibilityLayer data={points} margin={{ top: 8, right: 14, bottom: 4, left: -14 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="date" tickFormatter={day} minTickGap={32} tickLine={false} axisLine={false} tickMargin={10} />
        <YAxis domain={[0, 100]} ticks={[0, 50, 100]} tickFormatter={value => `${value}%`} tickLine={false} axisLine={false} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={value => day(String(value))} formatter={(value, _name, item) => <div className="space-y-1"><p className="font-medium tabular-nums">{percent(Number(value))} helpful</p><p className="text-muted-foreground">{item.payload.helpful} of {item.payload.rated} rated answers</p></div>} />} />
        <Area type="linear" dataKey="value" stroke="var(--color-value)" fill="var(--color-value)" fillOpacity={0.08} strokeWidth={2} dot={{ r: 3, fill: "var(--color-value)" }} activeDot={{ r: 5 }} connectNulls={false} isAnimationActive={false} />
      </AreaChart>
    </ChartContainer>
    <p className="text-[11px] leading-5 text-muted-foreground">{measured === 1 ? "One day has ratings. More rated days will show a trend." : "Higher is better. Days without ratings leave a gap."}</p>
  </div>
}

function DocumentMatchChart({ daily }: { daily: DailyQuality[] }) {
  const points = daily.map(row => ({
    date: row.date,
    weak: row.complete && row.measured > 0 ? row.low_match : null,
    other: row.complete && row.measured > 0 ? row.measured - row.low_match : null,
    measured: row.measured,
  }))
  if (!points.some(point => point.weak != null)) return <div className="flex min-h-52 flex-col items-center justify-center gap-2 rounded-lg bg-muted/20 p-5 text-center"><FilesIcon className="size-6 text-muted-foreground" aria-hidden="true" /><p className="text-xs font-medium">No document-match measurements yet</p><p className="max-w-64 text-xs leading-5 text-muted-foreground">Measured document questions will appear here after the UTC day ends.</p></div>
  return <div className="space-y-2">
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
      <p>Questions per day</p>
      <div className="flex flex-wrap gap-x-3 gap-y-1"><span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-chart-4" />Weak matches</span><span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-muted-foreground/30" />Other matches</span></div>
    </div>
    <ChartContainer config={{ weak: { label: "Weak matches", color: "var(--chart-4)" }, other: { label: "Other matches", color: "var(--muted-foreground)" } }} className="h-48 w-full aspect-auto" aria-label="Daily document questions, split into weak matches and other matches">
      <BarChart accessibilityLayer data={points} maxBarSize={28} margin={{ top: 8, right: 14, bottom: 4, left: -14 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="date" tickFormatter={day} minTickGap={32} tickLine={false} axisLine={false} tickMargin={10} />
        <YAxis allowDecimals={false} tickLine={false} axisLine={false} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={value => day(String(value))} formatter={(value, name) => <div className="flex w-full items-center justify-between gap-4"><span className="text-muted-foreground">{name === "weak" ? "Weak matches" : "Other matches"}</span><span className="font-medium tabular-nums">{number.format(Number(value))}</span></div>} />} />
        <Bar dataKey="weak" stackId="queries" fill="var(--color-weak)" isAnimationActive={false} />
        <Bar dataKey="other" stackId="queries" fill="var(--color-other)" fillOpacity={0.25} radius={[3, 3, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ChartContainer>
    <p className="text-[11px] leading-5 text-muted-foreground">Each bar is one day. The amber part counts weak matches; fewer is better.</p>
  </div>
}

export function LiveQualityCharts({ data, days }: { data: QualityTrendsReport; days: string }) {
  const current = data.current
  const feedbackPoints = data.daily.map(row => ({ date: row.date, helpful: row.helpful, rated: row.rated, value: row.complete ? row.helpful_percent : null }))
  return <div className="grid gap-4 xl:grid-cols-2">
    <article className="flex min-w-0 flex-col gap-4 rounded-xl border p-4">
      <div className="flex h-7 items-center">
        <h3 className="flex items-center gap-2 text-xs font-medium"><ThumbsUpIcon className="size-4 text-muted-foreground" aria-hidden="true" />Helpful feedback</h3>
      </div>
      <div className="space-y-1.5">
        <p className="text-2xl font-semibold tracking-tight tabular-nums">{current.rated ? percent(current.helpful_percent) : "No ratings yet"}</p>
        <p className="text-xs leading-5 text-muted-foreground">{current.rated ? `${number.format(current.helpful)} of ${number.format(current.rated)} rated answers were helpful.` : "See how people rate your answers over time."}</p>
        {current.queries > current.rated && <p className="text-xs text-muted-foreground">{number.format(current.queries - current.rated)} answers haven’t been rated.</p>}
        <PeriodChange value={qualityChange(current, data.previous, "helpful_percent")} days={days} />
      </div>
      <div className="mt-auto">
        <HelpfulFeedbackChart points={feedbackPoints} />
      </div>
    </article>
    <article className="flex min-w-0 flex-col gap-4 rounded-xl border p-4">
      <div className="flex h-7 items-center"><h3 className="flex items-center gap-2 text-xs font-medium"><FilesIcon className="size-4 text-muted-foreground" aria-hidden="true" />Document matches</h3></div>
      <div className="space-y-1.5">
        <p className="text-2xl font-semibold tracking-tight tabular-nums">{current.measured ? <>{number.format(current.low_match)} <span className="text-sm font-medium text-muted-foreground">weak {current.low_match === 1 ? "match" : "matches"}</span></> : "No measurements yet"}</p>
        <p className="text-xs leading-5 text-muted-foreground">{current.measured ? `${percent(current.low_match_percent)} of ${number.format(current.measured)} measured questions had weak document matches.` : "Questions with weak document matches will appear here."}</p>
        <p className="text-xs leading-5 text-muted-foreground">A weak match means the documents may not cover the question. It doesn’t mean the answer was wrong.</p>
        <PeriodChange value={qualityChange(current, data.previous, "low_match_percent")} days={days} />
      </div>
      <div className="mt-auto"><DocumentMatchChart daily={data.daily} /></div>
    </article>
  </div>
}
