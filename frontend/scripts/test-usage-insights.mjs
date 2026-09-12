import assert from "node:assert/strict"
import { test } from "node:test"
import { getLargestSpender, getSpendingExplanation, getSpendingInsights, getUsageComparison, percentChange, usageDailyCsv } from "../src/lib/usage-insights.ts"

const now = new Date("2026-09-09T18:30:00Z")
const day = (date, overrides = {}) => ({
  date, requests: 10, prompt_tokens: 100, completion_tokens: 20, cost_usd: 1,
  embedding_tokens: 50, embedding_cost_usd: 0.1, saved_prompt_tokens: null,
  p50_latency_ms: null, p95_latency_ms: null, p99_latency_ms: null,
  cache_l1: 1, cache_l2: 1, cache_miss: 8, avg_retrieval_similarity: null,
  ...overrides,
})
const report = (overrides = {}) => ({
  window_days: 30, daily: [], by_model: [],
  caveats: { unmeasured_requests: 0, unpriced_models: [], vision_and_audio_excluded: false },
  ...overrides,
})

test("compares complete UTC weeks, excludes today and the older boundary", () => {
  const data = report({ daily: [
    day("2026-09-09", { requests: 900 }), day("2026-08-25", { requests: 900 }),
    day("2026-08-26"), day("2026-09-01"), day("2026-09-02"), day("2026-09-08", { requests: 30 }),
  ] })
  const result = getUsageComparison(data, now)
  assert.equal(result.previous.start, "2026-08-26")
  assert.equal(result.previous.end, "2026-09-01")
  assert.equal(result.current.start, "2026-09-02")
  assert.equal(result.current.end, "2026-09-08")
  assert.equal(result.previous.requests, 20)
  assert.equal(result.current.requests, 40)
  assert.equal(percentChange(result.current.requests, result.previous.requests), 100)
})

test("seven-day view compares three complete days against three, excluding partial boundaries", () => {
  const data = report({ window_days: 7, daily: [
    day("2026-09-02", { requests: 900 }), day("2026-09-09", { requests: 900 }),
    ...[3, 4, 5].map(date => day(`2026-09-0${date}`)),
    ...[6, 7, 8].map(date => day(`2026-09-0${date}`, { requests: 30 })),
  ] })
  const before = structuredClone(data)
  const result = getUsageComparison(data, now)
  assert.equal(result.periodDays, 3)
  assert.equal(result.previous.start, "2026-09-03")
  assert.equal(result.previous.end, "2026-09-05")
  assert.equal(result.current.start, "2026-09-06")
  assert.equal(result.current.end, "2026-09-08")
  assert.equal(result.previous.requests, 30)
  assert.equal(result.current.requests, 90)
  assert.equal(percentChange(result.current.requests, result.previous.requests), 200)
  assert.deepEqual(data, before)
})

test("seven-day view preserves missing cost and handles empty periods", () => {
  const result = getUsageComparison(report({ window_days: 7, daily: [
    day("2026-09-08", { cost_usd: null, embedding_cost_usd: null }),
  ] }), now)
  assert.equal(result.current.spend, null)
  assert.equal(result.previous.requests, 0)
  assert.equal(result.previous.cacheRate, null)
  assert.equal(percentChange(result.current.requests, result.previous.requests), null)
})

test("periods follow UTC across month/year boundaries and long windows retain weekly comparisons", () => {
  const result = getUsageComparison(report({ window_days: 7 }), new Date("2026-01-02T00:30:00+05:30"))
  assert.equal(result.previous.start, "2025-12-26")
  assert.equal(result.previous.end, "2025-12-28")
  assert.equal(result.current.start, "2025-12-29")
  assert.equal(result.current.end, "2025-12-31")
  assert.equal(getUsageComparison(report({ window_days: 90 }), now).periodDays, 7)
  assert.equal(getUsageComparison(report({ window_days: 1 }), now), null)
})

test("weights cache rate by cacheable queries, not requests or daily rates", () => {
  const result = getUsageComparison(report({ daily: [
    day("2026-09-02", { requests: 1000, cache_l1: 1, cache_l2: 0, cache_miss: 0 }),
    day("2026-09-03", { cache_l1: 0, cache_l2: 0, cache_miss: 9 }),
  ] }), now)
  assert.equal(result.current.cacheRate, 10)
  assert.equal(result.previous.cacheRate, null)
})

test("preserves unknown costs, while absent event buckets are zero recorded activity", () => {
  const result = getUsageComparison(report({ daily: [
    day("2026-09-02", { cost_usd: null, embedding_cost_usd: null }), day("2026-09-03"),
  ] }), now)
  assert.equal(result.current.spend, null)
  assert.equal(result.previous.spend, 0)
  assert.equal(result.previous.requests, 0)
})

test("recorded spend includes embedding-only activity and tiny real costs", () => {
  const result = getUsageComparison(report({ daily: [
    day("2026-09-02", { cost_usd: null, embedding_cost_usd: 0.00000001 }),
  ] }), now)
  assert.equal(result.current.spend, 0.00000001)
  assert.equal(percentChange(10, 0), null)
  assert.equal(percentChange(0, 0), null)
  assert.equal(percentChange(0, 10), -100)
})

test("largest spender uses measured model costs, including embedders, without sorting input", () => {
  const data = report({ by_model: [
    { model: "unknown", cost_usd: null }, { model: "llm", cost_usd: 2 },
    { model: "embedder", cost_usd: 8, kind: "embedding" },
  ] })
  const before = structuredClone(data)
  assert.equal(getLargestSpender(data).model.model, "embedder")
  assert.equal(getLargestSpender(data).share, 80)
  assert.deepEqual(data, before)
  assert.equal(getLargestSpender(report({ by_model: [{ cost_usd: null }, { cost_usd: 0 }] })), null)
})

test("CSV preserves null vs zero, precision, quoted caveats, and chronological order", () => {
  const data = report({ daily: [day("2026-09-08"), day("2026-09-02", { cost_usd: 0, embedding_cost_usd: 1e-10 })],
    caveats: { unmeasured_requests: 3, unpriced_models: ['vendor,"model"'], vision_and_audio_excluded: true } })
  const csv = usageDailyCsv(data)
  assert.ok(csv.startsWith('\uFEFF"window_days","date"'))
  assert.ok(csv.includes('"not measured"'))
  assert.ok(csv.includes('"0"'))
  assert.ok(csv.includes('"1e-10"'))
  assert.ok(csv.includes('vendor,""model""'))
  assert.ok(csv.indexOf("2026-09-02") < csv.indexOf("2026-09-08"))
  assert.equal(data.daily[0].date, "2026-09-08")
  assert.equal(csv.trim().split("\r\n").length, 3)
})

test("CSV escapes formula-like string values and supports empty reports", () => {
  assert.ok(usageDailyCsv(report({ daily: [day("=1+1")] })).includes('"\'=1+1"'))
  assert.equal(usageDailyCsv(report()).trim().split("\r\n").length, 1)
})

const spending = data => getSpendingInsights(data, getUsageComparison(data, now))
const closeTo = (actual, expected) => assert.ok(
  Math.abs(actual - expected) <= Math.max(Math.abs(actual), Math.abs(expected)) * Number.EPSILON * 16,
  `${actual} ≈ ${expected}`,
)

test("spending explanations follow the larger effect in both directions, including offsets", () => {
  const cases = [
    [200, 20, /More requests account for the recorded increase; cost per request stayed the same/],
    [50, 5, /Fewer requests account for the recorded decrease/],
    [100, 20, /A higher cost per request accounts for the recorded increase/],
    [100, 5, /A lower cost per request accounts for the recorded decrease/],
    [200, 30, /contribute equally to the recorded increase/],
    [200, 15, /More requests account for most.*A lower cost per request partly offsets/],
    [200, 5, /A lower cost per request accounts for most.*More requests partly offset/],
    [50, 7, /Fewer requests account for most.*A higher cost per request partly offsets/],
    [50, 15, /A higher cost per request accounts for most.*Fewer requests partly offset/],
    [200, 10, /opposite directions, offsetting each other/],
    [100, 10, /Recorded spend stayed the same/],
  ]
  for (const [requests, cost, expected] of cases) {
    const result = spending(report({ daily: [
      day("2026-09-01", { requests: 100, cost_usd: 10, embedding_cost_usd: 0 }),
      day("2026-09-08", { requests, cost_usd: cost, embedding_cost_usd: 0 }),
    ] }))
    assert.match(getSpendingExplanation(result), expected, `requests=${requests}, cost=${cost}`)
  }
})

test("explanations do not invent a cause for missing measurements or absent baselines", () => {
  assert.match(getSpendingExplanation(spending(report({ window_days: 1 }))), /Two equal periods/)
  assert.match(getSpendingExplanation(spending(report())), /Neither period has recorded requests/)
  assert.match(getSpendingExplanation(spending(report({ daily: [day("2026-09-08")] }))), /Usage started.*no previous cost per request/)
  assert.match(getSpendingExplanation(spending(report({ daily: [day("2026-09-01")] }))), /no recorded requests in the recent period/)
  assert.match(getSpendingExplanation(spending(report({ daily: [day("2026-09-08", { cost_usd: null })] }))), /Some costs are missing/)
})

test("zero-cost traffic changes and tiny measured costs retain honest explanations", () => {
  const compare = (previousCost, currentCost) => spending(report({ daily: [
    day("2026-09-01", { requests: 100, cost_usd: previousCost, embedding_cost_usd: 0 }),
    day("2026-09-08", { requests: 200, cost_usd: currentCost, embedding_cost_usd: 0 }),
  ] }))
  assert.match(getSpendingExplanation(compare(0, 0)), /Recorded spend stayed the same/)
  assert.match(getSpendingExplanation(compare(1e-10, 2e-10)), /More requests account for the recorded increase/)
  assert.match(getSpendingExplanation(compare(0, 1e-10)), /request-volume effect was zero/)
})

test("spending breakdown separates volume from the blended rate and reconciles the change", () => {
  const data = report({ daily: [
    day("2026-09-01", { requests: 100, cost_usd: 8, embedding_cost_usd: 2 }),
    day("2026-09-08", { requests: 200, cost_usd: 24, embedding_cost_usd: 6 }),
    day("2026-09-09", { requests: 999, cost_usd: 999 }),
  ] })
  const before = structuredClone(data)
  const result = spending(data)
  assert.equal(result.incomplete, false)
  assert.equal(result.spendDelta, 20)
  assert.equal(result.volumeEffect, 10)
  assert.equal(result.rateEffect, 10)
  closeTo(result.costPerRequestChange, 50)
  closeTo(result.forecast30Days, 30 / 7 * 30)
  assert.equal(result.forecastReason, null)
  assert.deepEqual(data, before)
})

test("opposing effects can cancel even when total spend is unchanged", () => {
  const result = spending(report({ daily: [
    day("2026-09-01", { requests: 100, cost_usd: 10, embedding_cost_usd: 0 }),
    day("2026-09-08", { requests: 200, cost_usd: 10, embedding_cost_usd: 0 }),
  ] }))
  assert.equal(result.spendDelta, 0)
  assert.equal(result.volumeEffect, 10)
  assert.equal(result.rateEffect, -10)
  assert.equal(result.costPerRequestChange, -50)
})

test("cost per request is weighted by requests and includes both types of spend", () => {
  const result = spending(report({ daily: [
    day("2026-09-02", { requests: 1, cost_usd: 8, embedding_cost_usd: 2 }),
    day("2026-09-08", { requests: 99, cost_usd: 4, embedding_cost_usd: 6 }),
  ] }))
  assert.equal(result.currentCostPerRequest, 0.2)
  assert.equal(result.previousCostPerRequest, null)
  assert.equal(result.volumeEffect, null)
  assert.equal(result.rateEffect, null)
  assert.equal(result.costPerRequestChange, null)
  assert.ok(result.forecast30Days > 0)
})

test("no recent requests has an undefined rate and no forecast, not a zero rate", () => {
  const result = spending(report({ daily: [day("2026-09-01")] }))
  assert.equal(result.currentCostPerRequest, null)
  assert.equal(result.costPerRequestChange, null)
  assert.equal(result.spendDelta, -1.1)
  assert.equal(result.volumeEffect, -1.1)
  closeTo(result.rateEffect, 0)
  assert.equal(result.forecast30Days, null)
  assert.equal(result.forecastReason, "no_activity")
})

test("actual zero-cost requests keep a measured zero forecast and handle a zero baseline", () => {
  const result = spending(report({ daily: [
    day("2026-09-01", { cost_usd: 0, embedding_cost_usd: 0 }),
    day("2026-09-08", { cost_usd: 0, embedding_cost_usd: 0 }),
  ] }))
  assert.equal(result.currentCostPerRequest, 0)
  assert.equal(result.forecast30Days, 0)
  assert.equal(result.volumeEffect, 0)
  assert.equal(result.rateEffect, 0)
  assert.equal(result.costPerRequestChange, null)
})

test("each window-wide measurement caveat suppresses effects and forecasts", () => {
  for (const caveat of [
    { unmeasured_requests: 2 },
    { unpriced_models: ["unpriced-model"] },
    { vision_and_audio_excluded: true },
  ]) {
    const data = report({ daily: [day("2026-09-01"), day("2026-09-08")] })
    Object.assign(data.caveats, caveat)
    const result = spending(data)
    assert.equal(result.incomplete, true)
    assert.ok(result.reasons.length > 0)
    assert.equal(result.volumeEffect, null)
    assert.equal(result.rateEffect, null)
    assert.equal(result.forecast30Days, null)
    assert.equal(result.forecastReason, "incomplete")
    closeTo(result.currentCostPerRequest, 0.11)
  }
})

test("missing cost for measured LLM or embedding tokens is incomplete even without caveats", () => {
  for (const missing of [
    { cost_usd: null }, { embedding_cost_usd: null },
    { cost_usd: null, embedding_cost_usd: null },
  ]) {
    const result = spending(report({ daily: [day("2026-09-08", missing)] }))
    assert.equal(result.incomplete, true)
    assert.equal(result.forecast30Days, null)
    assert.equal(result.volumeEffect, null)
  }
})

test("embedding-only and LLM-only days can be measured without inventing missing activity", () => {
  for (const row of [
    { cost_usd: null, prompt_tokens: null, completion_tokens: null, embedding_cost_usd: 1e-10 },
    { embedding_cost_usd: null, embedding_tokens: null, cost_usd: 1e-10 },
  ]) {
    const result = spending(report({ daily: [day("2026-09-08", row)] }))
    assert.equal(result.incomplete, false)
    closeTo(result.currentCostPerRequest, 1e-11)
    assert.ok(result.forecast30Days > 0)
    closeTo(result.forecast30Days, 1e-10 / 7 * 30)
  }
})

test("projection uses complete calendar days, including absent buckets, in every range", () => {
  for (const window_days of [7, 30, 90]) {
    const result = spending(report({ window_days, daily: [
      day("2026-09-08", { cost_usd: 2, embedding_cost_usd: 1 }),
      day("2026-09-09", { cost_usd: 999 }),
      day("2026-08-01", { cost_usd: null, embedding_cost_usd: null }),
    ] }))
    assert.equal(result.incomplete, false)
    closeTo(result.forecast30Days, window_days === 7 ? 30 : 3 / 7 * 30)
  }
  assert.equal(spending(report({ window_days: 1 })).forecastReason, "insufficient_history")
  assert.equal(spending(report({ window_days: 3, daily: [day("2026-09-08")] })).forecastReason, "insufficient_history")
})

test("floating-point cancellation is unchanged spend, while tiny real increases survive", () => {
  const result = spending(report({ daily: [
    day("2026-09-01", { cost_usd: 0.3, embedding_cost_usd: 0 }),
    day("2026-09-08", { cost_usd: 0.1, embedding_cost_usd: 0.2 }),
  ] }))
  assert.equal(result.spendDelta, 0)
  assert.equal(result.rateEffect, 0)
  assert.equal(result.costPerRequestChange, 0)
  const tiny = spending(report({ daily: [
    day("2026-09-01", { cost_usd: 1e-10, embedding_cost_usd: 0 }),
    day("2026-09-08", { cost_usd: 2e-10, embedding_cost_usd: 0 }),
  ] }))
  assert.equal(tiny.spendDelta, 1e-10)
  assert.equal(tiny.rateEffect, 1e-10)
})
