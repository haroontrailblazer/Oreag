"use client"

import type { ReactNode } from "react"
import {
  ArrowDownIcon, ArrowUpIcon, ChartBarIcon, DownloadSimpleIcon,
  LightningIcon, LightbulbIcon, ReceiptIcon,
} from "@phosphor-icons/react/dist/ssr"

import { Button } from "@/components/ui/button"
import type { AccountUsage } from "@/lib/types"
import { getLargestSpender, getUsageComparison, percentChange, usageDailyCsv } from "@/lib/usage-insights"

const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 })
const currency = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 6,
})

function money(value: number) {
  return value > 0 && value < 0.000001 ? `$${value.toPrecision(2)}` : currency.format(value)
}

function Change({ value, unit = "%" }: { value: number; unit?: string }) {
  const Icon = value > 0 ? ArrowUpIcon : ArrowDownIcon
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs font-medium text-foreground">
      {value !== 0 && <Icon aria-hidden="true" className="size-3" />}
      {value === 0 ? "No change" : `${Math.abs(value) < 0.1 ? "<0.1" : number.format(Math.abs(value))}${unit} ${value > 0 ? "increase" : "decrease"}`}
    </span>
  )
}

function Insight({ title, icon, value, children }: {
  title: string; icon: ReactNode; value: ReactNode; children: ReactNode
}) {
  return (
    <article className="usage-insight-card min-w-0 space-y-3 rounded-xl border border-border/70 bg-background/80 p-4 sm:p-5">
      <h3 className="flex items-center gap-2 text-xs font-medium text-muted-foreground">{icon}{title}</h3>
      <div className="break-words text-xl font-semibold tracking-tight [overflow-wrap:anywhere]">{value}</div>
      <div className="space-y-2 text-xs leading-relaxed text-muted-foreground">{children}</div>
    </article>
  )
}

export function UsageInsights({ data }: { data: AccountUsage }) {
  const comparison = getUsageComparison(data)
  const periodLabel = comparison ? comparison.periodDays === 7 ? "Weekly" : `${comparison.periodDays}-day` : "Period"
  const largest = getLargestSpender(data)
  const modelCostsUnknown = data.by_model.length > 0 && data.by_model.every((row) => row.cost_usd == null)
  const requestChange = comparison && percentChange(comparison.current.requests, comparison.previous.requests)
  const spendChange = comparison && comparison.current.spend != null && comparison.previous.spend != null
    ? percentChange(comparison.current.spend, comparison.previous.spend) : null
  const cacheChange = comparison && comparison.current.cacheRate != null && comparison.previous.cacheRate != null
    ? comparison.current.cacheRate - comparison.previous.cacheRate : null
  const partial = data.caveats.unmeasured_requests > 0 ||
    (data.caveats.unpriced_models?.length ?? 0) > 0 || data.caveats.vision_and_audio_excluded

  function downloadCsv() {
    const url = URL.createObjectURL(new Blob([usageDailyCsv(data)], { type: "text/csv;charset=utf-8;" }))
    const link = document.createElement("a")
    link.href = url
    link.download = `oreag-usage-daily-${data.window_days}d-${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return (
    <section aria-labelledby="usage-insights-heading" className="min-w-0 space-y-4 rounded-2xl border border-border/80 bg-muted/20 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1.5">
          <h2 id="usage-insights-heading" className="flex items-center gap-2 text-base font-semibold tracking-tight">
            <LightbulbIcon aria-hidden="true" className="size-5 text-primary" /> Usage insights
          </h2>
          <p className="text-xs leading-relaxed text-muted-foreground">
            {comparison
              ? `${comparison.periodDays}-day comparison: ${comparison.current.start} – ${comparison.current.end} vs ${comparison.previous.start} – ${comparison.previous.end} (UTC). Today is excluded.`
              : "Not enough complete days to compare. Model spend uses the selected window."}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={downloadCsv} disabled={data.daily.length === 0}>
          <DownloadSimpleIcon aria-hidden="true" className="size-4" /> Export daily CSV
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Insight title={`${periodLabel} requests`} icon={<ChartBarIcon aria-hidden="true" className="size-4" />}
          value={comparison ? number.format(comparison.current.requests) : "Not enough complete days"}>
          {comparison ? <>
            {requestChange != null ? <Change value={requestChange} /> : <p>No prior requests to calculate a percentage change.</p>}
            <p>{number.format(comparison.previous.requests)} requests in the previous period.</p>
          </> : <p>Two equal periods of complete days are needed for comparison.</p>}
        </Insight>
        <Insight title={`${periodLabel} recorded spend`} icon={<ReceiptIcon aria-hidden="true" className="size-4" />}
          value={comparison ? comparison.current.spend == null ? "Not measured" : money(comparison.current.spend) : "Not enough complete days"}>
          {comparison ? <>
            {spendChange != null && <Change value={spendChange} />}
            <p>{comparison.previous.spend == null ? "Previous period: not measured." : `${money(comparison.previous.spend)} recorded in the previous period.`}</p>
            {comparison.previous.spend === 0 && <p>No prior spend to calculate a percentage change.</p>}
          </> : <p>Compare reported LLM and embedding costs.</p>}
        </Insight>
        <Insight title={`${periodLabel} cache hit rate`} icon={<LightningIcon aria-hidden="true" className="size-4" />}
          value={comparison ? comparison.current.cacheRate == null ? "No cacheable queries" : `${number.format(comparison.current.cacheRate)}%` : "Not enough complete days"}>
          {comparison ? <>
            {cacheChange != null && <Change value={cacheChange} unit=" pp" />}
            <p>{number.format(comparison.current.hits)} hits / {number.format(comparison.current.cacheable)} cacheable queries.</p>
            <p>{comparison.previous.cacheRate == null ? "No cacheable queries in the previous period." : `Previous period: ${number.format(comparison.previous.cacheRate)}%. Changes are percentage points.`}</p>
          </> : <p>Compare L1 + L2 hits as a share of cacheable queries.</p>}
        </Insight>
        <Insight title={`Largest model spend · ${data.window_days} days`} icon={<ReceiptIcon aria-hidden="true" className="size-4" />}
          value={largest ? largest.model.model : modelCostsUnknown ? "Not measured" : "No recorded spend"}>
          {largest ? <>
            <p className="font-medium text-foreground">{money(largest.model.cost_usd!)} · {number.format(largest.share)}% of recorded model spend</p>
            <p>{largest.model.kind === "embedding" ? "Embedding" : "LLM"} model · {number.format(largest.model.requests)} requests.</p>
          </> : <p>{modelCostsUnknown ? "Model costs are unavailable for this window." : "No model has a positive reported cost in this window."}</p>}
        </Insight>
      </div>
      <p className="text-xs leading-relaxed text-muted-foreground">
        {partial ? "Spend figures are partial. " : ""}Recorded spend excludes unmeasured or unpriced usage.
        {" "}CSV includes daily measurements for the selected {data.window_days}-day window; unknown values stay “not measured”.
      </p>
    </section>
  )
}
