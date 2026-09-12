import { CalendarBlankIcon, ChartLineUpIcon, InfoIcon, WarningCircleIcon } from "@phosphor-icons/react/dist/ssr"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { forecastMoney, getBudgetForecast } from "@/lib/budget-forecast"
import type { BudgetsReport, UsageBudget } from "@/lib/budgets"

const date = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
const percent = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 })

export function BudgetForecast({ budget, period, asOf, refreshFailed = false }: {
  budget: UsageBudget
  period: Pick<BudgetsReport, "period_start" | "period_end">
  asOf: Date
  refreshFailed?: boolean
}) {
  const forecast = getBudgetForecast(budget, period, asOf)
  const incomplete = !forecast.available && forecast.reason === "incomplete"
  const unavailable = refreshFailed || !forecast.available
  const partial = !refreshFailed && forecast.available && forecast.partial
  const missingCosts = `${budget.unpriced_requests.toLocaleString("en-US")} ${budget.unpriced_requests === 1 ? "event has" : "events have"} incomplete cost data.`
  const reason = refreshFailed ? "Refresh the budget measurements to see an updated forecast."
    : !forecast.available ? {
      incomplete: budget.unpriced_requests > 0
        ? `${missingCosts} No positive recorded spend is available to estimate yet. Your budget alerts still use recorded spend.`
        : "Recorded costs are not measured. Unknown costs are never treated as zero.",
      invalid_period: "Waiting for measurements from the current UTC budget month.",
      too_early: "Available after three days of this UTC month have elapsed. Early-month activity is too limited to project.",
      no_activity: "No recorded activity this month to establish a spending rate.",
      invalid_budget: "A positive monthly budget is needed to calculate a forecast.",
    }[forecast.reason] : null

  return <section aria-label={`${budget.project_name ?? "Account"} budget forecast`} className="min-w-0 space-y-3 rounded-lg border border-border/60 bg-muted/20 p-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h4 className="flex items-center gap-2 text-xs font-medium"><ChartLineUpIcon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />Budget forecast</h4>
      <Badge variant="outline" className={partial ? "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-400" : "bg-background text-muted-foreground"}>{partial ? "Partial estimate" : "Estimate"}</Badge>
    </div>
    {unavailable ? <div className="space-y-2">
      <p className="flex items-center gap-2 text-sm font-medium">
        {incomplete && !refreshFailed && <WarningCircleIcon aria-hidden="true" className="size-4 shrink-0 text-amber-600 dark:text-amber-400" />}
        {incomplete && !refreshFailed ? "Incomplete measurements" : "Forecast unavailable"}
      </p>
      <p className="text-xs leading-relaxed text-muted-foreground">{reason}</p>
    </div> : forecast.available && <>
      <dl className="grid grid-cols-2 gap-3">
        <div className="min-w-0 space-y-1">
          <dt className="min-h-10 text-xs leading-5 text-muted-foreground sm:min-h-5">{partial ? "Recorded projection" : "Month-end spend"}</dt>
          <dd className="break-words text-lg font-semibold tracking-tight tabular-nums [overflow-wrap:anywhere]">{forecastMoney(forecast.projectedSpend)}</dd>
        </div>
        <div className="min-w-0 space-y-1">
          <dt className="min-h-10 text-xs leading-5 text-muted-foreground sm:min-h-5">{partial ? "Recorded daily avg." : "Daily average"}</dt>
          <dd className="break-words text-lg font-semibold tracking-tight tabular-nums [overflow-wrap:anywhere]">{forecastMoney(forecast.dailyAverage)}</dd>
        </div>
      </dl>
      {partial ? <div className="space-y-2 text-xs leading-relaxed">
        <p className="font-medium">{percent.format(forecast.projectedPercent)}% of budget projected from recorded costs</p>
        <p className="flex items-start gap-2 text-muted-foreground"><WarningCircleIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" /><span>{missingCosts} This month-end estimate covers recorded costs only; actual spending may be higher.</span></p>
      </div> : <p className={`text-xs font-medium leading-relaxed [overflow-wrap:anywhere] ${forecast.difference > 0 ? "text-amber-700 dark:text-amber-400" : "text-foreground"}`}>
        {forecast.difference > 0 ? `${forecastMoney(forecast.difference)} over budget at this pace`
          : forecast.difference < 0 ? `${forecastMoney(-forecast.difference)} below budget at this pace`
          : "On pace to use the full budget"}
        <span className="mt-0.5 block font-normal text-muted-foreground">{percent.format(forecast.projectedPercent)}% of monthly budget projected</span>
      </p>}
      <p className="flex items-start gap-2 border-t border-border/60 pt-3 text-xs leading-relaxed text-muted-foreground">
        <CalendarBlankIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        {forecast.alreadyReached ? "The recorded budget has already been reached."
          : partial ? "A budget-reach date is unavailable while some costs are missing."
          : forecast.reachesBudgetAt ? `Budget likely reached around ${date.format(new Date(forecast.reachesBudgetAt))} (UTC).`
          : "Budget is not projected to be reached before the next monthly reset."}
      </p>
    </>}
  </section>
}

export function BudgetForecastMethod() {
  return <details className="text-xs leading-relaxed text-muted-foreground">
    <summary className="w-fit cursor-pointer rounded-sm font-medium text-foreground focus-visible:outline-2 focus-visible:outline-offset-4">How budget forecasts work</summary>
    <div className="mt-2 flex items-start gap-2">
      <InfoIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <div className="space-y-2">
        <p>Month-end estimate = this budget’s recorded month-to-date spend ÷ elapsed UTC days × days in the month. Elapsed days include the fraction of today. Quiet days count, and account and project budgets are calculated separately.</p>
        <p>The estimated reach date assumes that average daily spend continues. Traffic, model prices, and missing or delayed measurements can change the result. These are recorded-cost estimates; your provider invoice may differ.</p>
        <p>Forecasts need at least three elapsed days and measured activity. When some spend is recorded but costs are missing, a partial estimate projects only the recorded portion. It does not predict total headroom or a budget-reach date. With no positive recorded spend and missing costs, the forecast stays unavailable. Estimates do not trigger alerts; alert thresholds continue to use recorded spend. Pausing alerts does not pause the forecast.</p>
      </div>
    </div>
  </details>
}

export function BudgetForecastSkeleton() {
  return <div role="status" aria-label="Loading budgets and forecasts" className="grid gap-3 xl:grid-cols-2">
    {[0, 1].map(index => <div key={index} className="min-w-0 space-y-3 rounded-lg border p-3" aria-hidden="true">
      <Skeleton className="h-5 w-36 max-w-full" /><Skeleton className="h-7 w-44 max-w-full" /><Skeleton className="h-1.5 w-full" />
      <div className="space-y-3 rounded-lg border border-border/60 bg-muted/20 p-3"><Skeleton className="h-4 w-32 max-w-full" /><Skeleton className="h-8 w-full" /><Skeleton className="h-10 w-full" /></div>
    </div>)}
  </div>
}
