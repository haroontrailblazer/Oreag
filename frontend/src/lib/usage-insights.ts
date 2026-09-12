import type { AccountUsage, UsageDaily } from "./types"

const DAY_MS = 86_400_000

function utcDate(time: number) {
  return new Date(time).toISOString().slice(0, 10)
}

function summarizePeriod(daily: UsageDaily[], start: string, end: string) {
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

export function getUsageComparison(data: AccountUsage, now = new Date()) {
  // Exclude both partial boundary days of the rolling window. Seven days
  // contains six complete UTC days: compare three against the previous three.
  // Longer windows retain the existing seven-day comparison, with no refetch.
  const periodDays = Math.min(7, Math.floor((data.window_days - 1) / 2))
  if (periodDays < 1) return null
  const today = Date.parse(`${now.toISOString().slice(0, 10)}T00:00:00Z`)
  return {
    periodDays,
    previous: summarizePeriod(data.daily, utcDate(today - 2 * periodDays * DAY_MS), utcDate(today - (periodDays + 1) * DAY_MS)),
    current: summarizePeriod(data.daily, utcDate(today - periodDays * DAY_MS), utcDate(today - DAY_MS)),
  }
}

export function percentChange(current: number, previous: number): number | null {
  return previous > 0 ? (current - previous) / previous * 100 : null
}

function costDifference(current: number, previous: number) {
  const difference = current - previous
  // Suppress only floating-point cancellation, never round tiny real costs
  // to cents (the provider can report costs as small as 1e-10 USD).
  return Math.abs(difference) <= Number.EPSILON * 4 * Math.max(Math.abs(current), Math.abs(previous))
    ? 0 : difference
}

export function getSpendingInsights(
  data: AccountUsage,
  comparison = getUsageComparison(data)
) {
  const reasons: string[] = []
  // Caveats are window-wide, not per day. Be conservative: they cannot prove
  // that measurement coverage stayed the same between the compared periods.
  if (data.caveats.unmeasured_requests > 0) {
    reasons.push(`${data.caveats.unmeasured_requests.toLocaleString("en-US")} requests have unreported usage in the selected window.`)
  }
  if (data.caveats.unpriced_models?.length) {
    reasons.push(`Missing prices for: ${data.caveats.unpriced_models.join(", ")}.`)
  }
  if (data.caveats.vision_and_audio_excluded) {
    reasons.push("Some vision or audio costs are excluded.")
  }
  const comparedRows = comparison ? data.daily.filter(row =>
    row.date >= comparison.previous.start && row.date <= comparison.current.end
  ) : []
  if (comparedRows.some(row =>
    (row.cost_usd == null && ((row.prompt_tokens ?? 0) > 0 || (row.completion_tokens ?? 0) > 0)) ||
    (row.embedding_cost_usd == null && (row.embedding_tokens ?? 0) > 0) ||
    (row.requests > 0 && row.cost_usd == null && row.embedding_cost_usd == null)
  )) {
    reasons.push("Some activity in the comparison has no recorded cost.")
  }
  const incomplete = reasons.length > 0
  const previous = comparison?.previous
  const current = comparison?.current
  const previousCostPerRequest = previous?.spend != null && previous.requests > 0
    ? previous.spend / previous.requests : null
  const currentCostPerRequest = current?.spend != null && current.requests > 0
    ? current.spend / current.requests : null
  const spendDelta = previous?.spend != null && current?.spend != null
    ? costDifference(current.spend, previous.spend) : null

  // A sequential arithmetic decomposition, not causal attribution. First
  // change volume at the old blended rate, then change the rate at new volume.
  // Using the residual preserves the total, including opposing effects and
  // a current period with no requests (whose rate is undefined, not zero).
  const volumeEffect = !incomplete && spendDelta != null && previousCostPerRequest != null && previous && current
    ? (current.requests - previous.requests) * previousCostPerRequest : null
  const rateEffect = volumeEffect != null && spendDelta != null ? costDifference(spendDelta, volumeEffect) : null
  const costPerRequestChange = previousCostPerRequest != null && currentCostPerRequest != null
    ? previousCostPerRequest === 0 ? null
      : costDifference(currentCostPerRequest, previousCostPerRequest) === 0 ? 0
      : percentChange(currentCostPerRequest, previousCostPerRequest)
    : null

  // A fixed 30-day run rate avoids pretending a rolling 7-day report contains
  // month-to-date spend. Never extrapolate partial or wholly unknown costs.
  const forecastReason = incomplete || (current && current.spend == null) ? "incomplete"
    : !comparison || comparison.periodDays < 3 ? "insufficient_history"
    : !current?.requests ? "no_activity" : null
  const forecast30Days = forecastReason == null && comparison && current?.spend != null
    ? current.spend / comparison.periodDays * 30 : null

  return {
    comparison, incomplete, reasons, spendDelta,
    previousCostPerRequest, currentCostPerRequest, costPerRequestChange,
    volumeEffect, rateEffect, forecast30Days, forecastReason,
  }
}

export function getSpendingExplanation(insights: ReturnType<typeof getSpendingInsights>) {
  const { comparison, incomplete, spendDelta, volumeEffect, rateEffect } = insights
  if (incomplete) return "Some costs are missing. Changes in measurement coverage could look like changes in spending."
  if (!comparison || spendDelta == null) return "Two equal periods of complete days with recorded costs are needed to explain a change."
  if (comparison.previous.requests === 0) {
    return comparison.current.requests === 0
      ? "Neither period has recorded requests to compare."
      : "Usage started in the recent period. There is no previous cost per request to use as a baseline."
  }
  if (comparison.current.requests === 0) return "There were no recorded requests in the recent period, so there is no recent cost per request to compare."
  if (volumeEffect == null || rateEffect == null) return "Recorded costs are needed to separate request volume from cost per request."
  if (spendDelta === 0) {
    return volumeEffect === 0 && rateEffect === 0
      ? "Recorded spend stayed the same across both periods."
      : "Request volume and cost per request moved in opposite directions, offsetting each other."
  }

  const volume = volumeEffect > 0 ? "More requests" : "Fewer requests"
  const rate = rateEffect > 0 ? "A higher cost per request" : "A lower cost per request"
  const direction = spendDelta > 0 ? "increase" : "decrease"
  if (rateEffect === 0) return `${volume} account for the recorded ${direction}; cost per request stayed the same.`
  if (volumeEffect === 0) return `${rate} accounts for the recorded ${direction}; the request-volume effect was zero.`

  const magnitudeDifference = costDifference(Math.abs(volumeEffect), Math.abs(rateEffect))
  if (magnitudeDifference === 0) return `${volume} and ${rate.toLowerCase()} contribute equally to the recorded ${direction}.`
  const opposing = Math.sign(volumeEffect) !== Math.sign(rateEffect)
  return magnitudeDifference > 0
    ? `${volume} account for most of the recorded ${direction}.${opposing ? ` ${rate} partly offsets that change.` : ""}`
    : `${rate} accounts for most of the recorded ${direction}.${opposing ? ` ${volume} partly offset that change.` : ""}`
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
