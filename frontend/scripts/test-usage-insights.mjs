import assert from "node:assert/strict"
import { test } from "node:test"
import { getLargestSpender, getWeeklyComparison, percentChange, usageDailyCsv } from "../src/lib/usage-insights.ts"

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
  const result = getWeeklyComparison(data, now)
  assert.equal(result.previous.start, "2026-08-26")
  assert.equal(result.previous.end, "2026-09-01")
  assert.equal(result.current.start, "2026-09-02")
  assert.equal(result.current.end, "2026-09-08")
  assert.equal(result.previous.requests, 20)
  assert.equal(result.current.requests, 40)
  assert.equal(percentChange(result.current.requests, result.previous.requests), 100)
})

test("does not compare a seven-day payload or mutate its rows", () => {
  const data = report({ window_days: 7, daily: [day("2026-09-08")] })
  const before = structuredClone(data)
  assert.equal(getWeeklyComparison(data, now), null)
  assert.deepEqual(data, before)
})

test("weights cache rate by cacheable queries, not requests or daily rates", () => {
  const result = getWeeklyComparison(report({ daily: [
    day("2026-09-02", { requests: 1000, cache_l1: 1, cache_l2: 0, cache_miss: 0 }),
    day("2026-09-03", { cache_l1: 0, cache_l2: 0, cache_miss: 9 }),
  ] }), now)
  assert.equal(result.current.cacheRate, 10)
  assert.equal(result.previous.cacheRate, null)
})

test("preserves unknown costs, while absent event buckets are zero recorded activity", () => {
  const result = getWeeklyComparison(report({ daily: [
    day("2026-09-02", { cost_usd: null, embedding_cost_usd: null }), day("2026-09-03"),
  ] }), now)
  assert.equal(result.current.spend, null)
  assert.equal(result.previous.spend, 0)
  assert.equal(result.previous.requests, 0)
})

test("recorded spend includes embedding-only activity and tiny real costs", () => {
  const result = getWeeklyComparison(report({ daily: [
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
