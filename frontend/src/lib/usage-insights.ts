import type { AccountUsage, UsageDaily } from "./types"

const DAY_MS = 86_400_000

function utcDate(time: number) {
  return new Date(time).toISOString().slice(0, 10)
}

function summarizeWeek(daily: UsageDaily[], start: string, end: string) {
  const rows = daily.filter((row) => row.date >= start && row.date <= end)
  const requests = rows.reduce((sum, row) => sum + row.requests, 0)
  const hits = rows.reduce((sum, row) => sum + row.cache_l1 + row.cache_l2, 0)
  const cacheable = hits + rows.reduce((sum, row) => sum + row.cache_miss, 0)
  // The API returns sparse day buckets. An absent day has no recorded events;
  // an active day with no reported cost is unknown, never a zero-cost day.
  const unknownCost = rows.some((row) =>
    row.requests > 0 && row.cost_usd == null && row.embedding_cost_usd == null
  )
  const spend = unknownCost ? null : rows.reduce(
    (sum, row) => sum + (row.cost_usd ?? 0) + (row.embedding_cost_usd ?? 0), 0
  )
  return { start, end, requests, spend, hits, cacheable,
    cacheRate: cacheable > 0 ? hits / cacheable * 100 : null }
}

export function getWeeklyComparison(data: AccountUsage, now = new Date()) {
  // The rolling cutoff and today are partial days. A 7-day payload cannot
  // supply two complete weeks; never refetch or compare unequal periods.
  if (data.window_days < 15) return null
  const today = Date.parse(`${now.toISOString().slice(0, 10)}T00:00:00Z`)
  return {
    previous: summarizeWeek(data.daily, utcDate(today - 14 * DAY_MS), utcDate(today - 8 * DAY_MS)),
    current: summarizeWeek(data.daily, utcDate(today - 7 * DAY_MS), utcDate(today - DAY_MS)),
  }
}

export function percentChange(current: number, previous: number): number | null {
  return previous > 0 ? (current - previous) / previous * 100 : null
}

export function getLargestSpender(data: AccountUsage) {
  const measured = data.by_model.filter((row) => row.cost_usd != null && row.cost_usd > 0)
  const total = measured.reduce((sum, row) => sum + row.cost_usd!, 0)
  const model = measured.reduce<(typeof measured)[number] | null>(
    (largest, row) => !largest || row.cost_usd! > largest.cost_usd! ? row : largest, null
  )
  return model ? { model, share: model.cost_usd! / total * 100 } : null
}

const DAILY_COLUMNS = [
  "date", "requests", "prompt_tokens", "completion_tokens", "cost_usd",
  "embedding_tokens", "embedding_cost_usd", "saved_prompt_tokens",
  "p50_latency_ms", "p95_latency_ms", "p99_latency_ms", "cache_l1", "cache_l2",
  "cache_miss", "avg_retrieval_similarity",
] as const satisfies readonly (keyof UsageDaily)[]

function csvCell(value: string | number | null) {
  let text = value == null ? "not measured" : String(value)
  if (typeof value === "string" && /^[\s]*[=+@-]/.test(text)) text = `'${text}`
  return `"${text.replaceAll('"', '""')}"`
}

export function usageDailyCsv(data: AccountUsage) {
  const caveats = [
    `${data.caveats.unmeasured_requests} requests without reported token usage`,
    `Unpriced models: ${data.caveats.unpriced_models?.join("; ") || "none"}`,
    data.caveats.vision_and_audio_excluded ? "Some vision/audio usage excluded" : "",
  ].filter(Boolean).join(". ")
  const rows: (string | number | null)[][] = [
    ["window_days", ...DAILY_COLUMNS, "measurement_caveats"],
    ...[...data.daily].sort((a, b) => a.date.localeCompare(b.date)).map((row) =>
      [data.window_days, ...DAILY_COLUMNS.map((key) => row[key]), caveats]
    ),
  ]
  return "\uFEFF" + rows.map((row) => row.map(csvCell).join(",")).join("\r\n") + "\r\n"
}
