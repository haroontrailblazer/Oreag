"use client"

import type { ReactNode } from "react"
import {
  ArrowDownIcon, ArrowUpIcon, ChartBarIcon, ChartLineUpIcon, DownloadSimpleIcon,
  InfoIcon, LightningIcon, LightbulbIcon, ReceiptIcon, ScalesIcon, WarningCircleIcon,
} from "@phosphor-icons/react/dist/ssr"

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import type { AccountUsage } from "@/lib/types"
import { getLargestSpender, getSpendingExplanation, getSpendingInsights, percentChange, usageDailyCsv } from "@/lib/usage-insights"

const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 })
const currency = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 6,
})
const summaryCurrency = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2,
})

function money(value: number) {
  return Math.abs(value) > 0 && Math.abs(value) < 0.000001 ? `$${value.toPrecision(2)}` : currency.format(value)
}

function signedMoney(value: number) {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${summaryMoney(Math.abs(value))}`
}

function summaryMoney(value: number) {
  return Math.abs(value) >= 0.01 ? summaryCurrency.format(value) : money(value)
}

function Change({ value, unit = "%" }: { value: number; unit?: string }) {
  const Icon = value > 0 ? ArrowUpIcon : ArrowDownIcon
  return (
    <Badge variant="secondary" className="max-w-full whitespace-normal">
      {value !== 0 && <Icon aria-hidden="true" className="size-3" />}
      {value === 0 ? "No change" : `${Math.abs(value) < 0.1 ? "<0.1" : number.format(Math.abs(value))}${unit} ${value > 0 ? "increase" : "decrease"}`}
    </Badge>
  )
}

function Insight({ title, icon, value, children }: {
  title: string; icon: ReactNode; value: ReactNode; children: ReactNode
}) {
  return (
    <article className="usage-insight-card min-w-0 space-y-3 rounded-xl border border-border/70 bg-background/80 p-4 sm:p-5">
      <h3 className="flex min-h-8 items-start gap-2 text-xs font-medium leading-4 text-muted-foreground [&>svg]:shrink-0">{icon}{title}</h3>
      <div className="break-words text-xl font-semibold tracking-tight [overflow-wrap:anywhere]">{value}</div>
      <div className="space-y-2 text-xs leading-relaxed text-muted-foreground">{children}</div>
    </article>
  )
}

function SpendingChange({ insights }: { insights: ReturnType<typeof getSpendingInsights> }) {
  const {
    comparison, incomplete, reasons, spendDelta, previousCostPerRequest,
    currentCostPerRequest, volumeEffect, rateEffect,
    forecast30Days, forecastReason,
  } = insights
  const headline = incomplete ? "Spending comparison is incomplete"
    : spendDelta == null ? "Not enough cost data to compare"
    : spendDelta === 0 ? "Recorded spend is unchanged"
    : `${summaryMoney(Math.abs(spendDelta))} ${spendDelta > 0 ? "more" : "less"} recorded spend`
  const spendChange = !incomplete && spendDelta != null && comparison?.previous.spend != null && comparison.previous.spend > 0
    ? spendDelta / comparison.previous.spend * 100 : null

  return (
    <section aria-labelledby="spending-change-heading" className="min-w-0 overflow-hidden rounded-xl border border-border/70 bg-background/80">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-4 py-3 sm:px-5">
        <h3 id="spending-change-heading" className="flex min-w-0 items-center gap-2 text-sm font-semibold">
          <ScalesIcon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
          Why did spending change?
        </h3>
        <Badge variant="outline" className={`max-w-full whitespace-normal ${incomplete ? "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-400" : "text-muted-foreground"}`}>
          {incomplete && <WarningCircleIcon aria-hidden="true" className="shrink-0" />}
          {incomplete ? "Incomplete measurements" : "Recorded costs"}
        </Badge>
      </div>
      <div className="grid min-w-0 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.6fr)]">
        <div className="min-w-0 space-y-4 p-4 sm:p-5">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <p className="break-words text-lg font-semibold tracking-tight [overflow-wrap:anywhere]">{headline}</p>
              {spendChange != null && <Change value={spendChange} />}
            </div>
            <p className="text-xs leading-relaxed text-muted-foreground">
              {getSpendingExplanation(insights)}
            </p>
          </div>

          {comparison && <div className="space-y-2">
            <dl className="grid grid-cols-1 divide-y overflow-hidden rounded-lg border border-border/60 min-[400px]:grid-cols-2 min-[400px]:divide-x min-[400px]:divide-y-0">
              {([ ["Previous", comparison.previous], ["Recent", comparison.current] ] as const).map(([label, period]) => (
                <div key={label} className="min-w-0 space-y-1 p-3">
                  <dt className="text-xs font-medium text-muted-foreground">{label} {comparison.periodDays} days</dt>
                  <dd className="break-words text-lg font-semibold tabular-nums [overflow-wrap:anywhere]">{period.spend == null ? "Not measured" : summaryMoney(period.spend)}</dd>
                  <dd className="text-xs text-muted-foreground">{number.format(period.requests)} requests</dd>
                  <dd className="text-[11px] leading-relaxed text-muted-foreground">{period.start} – {period.end}</dd>
                </div>
              ))}
            </dl>
            <p className="text-[11px] leading-relaxed text-muted-foreground">Recorded LLM + embedding costs · complete UTC days · today excluded{incomplete ? " · partial amounts" : ""}</p>
          </div>}

          {incomplete ? (
            <div className="space-y-2 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs leading-relaxed">
              <ul className="list-disc space-y-1 pl-4 [overflow-wrap:anywhere]">{reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
              <p className="text-muted-foreground">Coverage may differ between periods. Spending effects and the forecast are unavailable until measurements are complete.</p>
            </div>
          ) : volumeEffect != null && rateEffect != null ? (
            <dl className="space-y-3">
              <div className="relative flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 pl-11">
                <dt className="text-xs font-medium">
                  <span className="absolute left-0 top-0 flex size-8 items-center justify-center rounded-lg bg-muted text-muted-foreground"><ChartBarIcon aria-hidden="true" className="size-4" /></span>
                  Request-volume effect
                </dt>
                <dd className="break-words text-sm font-semibold tabular-nums [overflow-wrap:anywhere]">{signedMoney(volumeEffect)}</dd>
                <dd className="basis-full text-xs leading-relaxed text-muted-foreground">Change in requests at the previous cost per request.</dd>
              </div>
              <div className="relative flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 pl-11">
                <dt className="text-xs font-medium">
                  <span className="absolute left-0 top-0 flex size-8 items-center justify-center rounded-lg bg-muted text-muted-foreground"><ReceiptIcon aria-hidden="true" className="size-4" /></span>
                  Cost-per-request effect
                </dt>
                <dd className="break-words text-sm font-semibold tabular-nums [overflow-wrap:anywhere]">{signedMoney(rateEffect)}</dd>
                <dd className="basis-full text-xs leading-relaxed text-muted-foreground">{previousCostPerRequest == null ? "Unavailable" : money(previousCostPerRequest)} → {currentCostPerRequest == null ? "Unavailable (no requests)" : money(currentCostPerRequest)} per request.</dd>
              </div>
              <div className="flex flex-wrap items-baseline justify-between gap-2 border-t border-border/60 pt-3 text-xs font-medium">
                <dt>Total recorded change</dt>
                <dd className="break-words text-sm font-semibold tabular-nums [overflow-wrap:anywhere]">{signedMoney(spendDelta!)}</dd>
              </div>
            </dl>
          ) : (
            <p className="rounded-lg bg-muted/50 p-3 text-xs leading-relaxed text-muted-foreground">
              {comparison?.previous.requests === 0 ? "No previous requests to establish a cost-per-request baseline. A breakdown will appear once both periods have comparable usage." : "Recorded costs are needed to calculate the spending breakdown."}
            </p>
          )}

          <p className="flex items-start gap-2 text-xs leading-relaxed text-muted-foreground">
            <InfoIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            This breakdown separates volume from the blended cost per request. These totals cannot identify which models, tokens, or cache changes caused the rate to change.
          </p>
          <details className="text-xs leading-relaxed text-muted-foreground">
            <summary className="w-fit cursor-pointer rounded-sm font-medium text-foreground focus-visible:outline-2 focus-visible:outline-offset-4">How to read this breakdown</summary>
            <div className="mt-2 space-y-2">
              <p>Request-volume effect = change in requests × previous recorded cost per request. The remaining spend change is the cost-per-request effect. Both effects add up to the recorded spend change before display rounding.</p>
              <p>Cost per request blends LLM and embedding costs across all recorded requests. Workload, tokens, model prices, and caching can all affect this rate. The cache comparison above is useful context; these totals cannot establish the cause of a change.</p>
              <p>Unknown costs remain unmeasured. With no requests, cost per request is unavailable.</p>
            </div>
          </details>
        </div>

        <div className="min-w-0 space-y-3 border-t border-border/60 bg-muted/20 p-4 sm:p-5 xl:border-l xl:border-t-0">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="flex items-center gap-2 text-sm font-medium"><ChartLineUpIcon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />Next 30 days</h4>
            <Badge variant="outline" className="bg-background text-muted-foreground">Estimate</Badge>
          </div>
          <p className="break-words text-2xl font-semibold tracking-tight tabular-nums [overflow-wrap:anywhere]">{forecast30Days == null ? "Unavailable" : summaryMoney(forecast30Days)}</p>
          {forecast30Days != null && comparison ? <>
            <p className="text-xs font-medium">Projected recorded spend</p>
            <p className="text-xs leading-relaxed text-muted-foreground">{summaryMoney(comparison.current.spend! / comparison.periodDays)} per day across {comparison.periodDays} complete UTC days ({comparison.current.start} – {comparison.current.end}).</p>
            <p className="text-xs leading-relaxed text-muted-foreground">Estimated daily spend × 30. Assumes the recent spending rate continues; actual costs can change with traffic, models, and caching.</p>
          </> : (
            <p className="text-xs leading-relaxed text-muted-foreground">
              {forecastReason === "incomplete" ? "Incomplete measurements prevent a reliable projection. Unreported and unpriced costs are never treated as zero."
                : forecastReason === "no_activity" ? "No requests in the recent complete days to establish a spending rate."
                : "At least three complete days are needed to estimate a spending rate."}
            </p>
          )}
        </div>
      </div>
    </section>
  )
}

export function UsageInsights({ data }: { data: AccountUsage }) {
  const spending = getSpendingInsights(data)
  const { comparison } = spending
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
      <SpendingChange insights={spending} />
      <p className="text-xs leading-relaxed text-muted-foreground">
        {partial ? "Spend figures are partial. " : ""}Recorded spend excludes unmeasured or unpriced usage.
        {" "}CSV includes daily measurements for the selected {data.window_days}-day window; unknown values stay “not measured”.
      </p>
    </section>
  )
}
