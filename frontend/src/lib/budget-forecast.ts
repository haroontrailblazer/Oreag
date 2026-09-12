import type { BudgetsReport, UsageBudget } from "./budgets"

const DAY_MS = 86_400_000
const MIN_ELAPSED_DAYS = 3

type UnavailableReason = "incomplete" | "invalid_period" | "too_early" | "no_activity" | "invalid_budget"
type BudgetForecast = {
  available: false
  reason: UnavailableReason
} | {
  available: true
  partial: boolean
  elapsedDays: number
  monthDays: number
  dailyAverage: number
  projectedSpend: number
  projectedPercent: number
  difference: number
  reachesBudgetAt: string | null
  alreadyReached: boolean
}

/** The report totals include today's activity, so use elapsed time, including
 * the fraction of today, rather than dividing by completed days. Worker
 * last_checked_at timestamps describe alert checks, not these fresh totals. */
export function getBudgetForecast(
  budget: UsageBudget,
  period: Pick<BudgetsReport, "period_start" | "period_end">,
  asOf: Date,
): BudgetForecast {
  const partial = budget.unpriced_requests > 0
  // Known spend can support a recorded-cost-only projection. Never turn a
  // wholly unknown total (or zero with missing costs) into a zero forecast.
  if (budget.spent_usd == null || !Number.isFinite(budget.spent_usd) || budget.spent_usd < 0 || (partial && budget.spent_usd === 0)) {
    return { available: false, reason: "incomplete" }
  }
  if (!Number.isFinite(budget.amount_usd) || budget.amount_usd <= 0) return { available: false, reason: "invalid_budget" }
  const start = Date.parse(`${period.period_start}T00:00:00Z`)
  const end = Date.parse(`${period.period_end}T00:00:00Z`)
  const now = asOf.getTime()
  if (!Number.isFinite(start) || !Number.isFinite(end) || !Number.isFinite(now) || end <= start || now < start || now >= end) {
    return { available: false, reason: "invalid_period" }
  }
  const elapsedDays = (now - start) / DAY_MS
  const monthDays = (end - start) / DAY_MS
  if (elapsedDays < MIN_ELAPSED_DAYS) return { available: false, reason: "too_early" }
  if (budget.requests <= 0) return { available: false, reason: "no_activity" }

  const dailyAverage = budget.spent_usd / elapsedDays
  const projectedSpend = dailyAverage * monthDays
  const rawDifference = projectedSpend - budget.amount_usd
  const difference = Math.abs(rawDifference) <= Number.EPSILON * 4 * Math.max(projectedSpend, budget.amount_usd) ? 0 : rawDifference
  const alreadyReached = budget.spent_usd >= budget.amount_usd
  const reachTime = dailyAverage > 0 ? now + (budget.amount_usd - budget.spent_usd) / dailyAverage * DAY_MS : null
  // The period end is exclusive. Reaching the limit at next month's reset
  // does not mean reaching it during this budget period.
  const reachesBudgetAt = !partial && !alreadyReached && difference > 0 && reachTime != null && reachTime >= now && reachTime < end
    ? new Date(reachTime).toISOString() : null
  return { available: true, partial, elapsedDays, monthDays, dailyAverage, projectedSpend,
    projectedPercent: projectedSpend / budget.amount_usd * 100, difference, reachesBudgetAt, alreadyReached }
}

/** Keep small, genuinely measured costs visible instead of rounding to $0. */
export function forecastMoney(value: number) {
  if (value !== 0 && Math.abs(value) < 0.000001) return `$${value.toPrecision(2)}`
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD",
    minimumFractionDigits: 2, maximumFractionDigits: Math.abs(value) < 0.01 ? 6 : 2 }).format(value)
}
