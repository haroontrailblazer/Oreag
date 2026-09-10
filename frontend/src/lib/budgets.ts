export const BUDGETS_KEY = "/api/account/budgets"
export const BUDGET_ALERTS_KEY = `${BUDGETS_KEY}/alerts`
export const BUDGET_REFRESH_MS = 60_000

export type UsageBudget = {
  id: string; project_id: string | null; project_name: string | null
  amount_usd: number; warning_percent: number; enabled: boolean; revision: number
  spent_usd: number | null; percent_used: number | null; requests: number; unpriced_requests: number
  state: "paused" | "unmeasured" | "exceeded" | "warning" | "on_track"
  last_checked_at: string | null
}
export type BudgetAlert = {
  id: string; budget_id: string; project_name: string | null; period_start: string
  threshold_percent: number; amount_usd: number; spent_usd: number; created_at: string; read_at: string | null
}
export type BudgetAlerts = { alerts: BudgetAlert[]; unread_count: number }
export type BudgetsReport = BudgetAlerts & {period_start: string; period_end: string; budgets: UsageBudget[]; mode: "warn_only"}
export const budgetMoney = (value: number | null) => value === null ? "Not measured" : new Intl.NumberFormat("en-US", {style:"currency",currency:"USD",maximumFractionDigits:value > 0 && value < .01 ? 4 : 2}).format(value)
