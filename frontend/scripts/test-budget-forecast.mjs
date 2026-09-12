import assert from "node:assert/strict"
import { test } from "node:test"
import { forecastMoney, getBudgetForecast } from "../src/lib/budget-forecast.ts"

const period = { period_start: "2026-09-01", period_end: "2026-10-01" }
const now = new Date("2026-09-11T00:00:00Z")
const budget = (overrides = {}) => ({ id: "account", project_id: null, project_name: null,
  amount_usd: 100, spent_usd: 50, requests: 100, unpriced_requests: 0,
  enabled: true, state: "on_track", last_checked_at: "2026-09-01T00:00:00Z", ...overrides })
const calculate = (overrides = {}, at = now, dates = period) => getBudgetForecast(budget(overrides), dates, at)

test("projects month-to-date spend and the remaining time to reach a budget", () => {
  const result = calculate()
  assert.equal(result.available, true)
  assert.equal(result.partial, false)
  assert.equal(result.elapsedDays, 10)
  assert.equal(result.dailyAverage, 5)
  assert.equal(result.projectedSpend, 150)
  assert.equal(result.difference, 50)
  assert.equal(result.projectedPercent, 150)
  assert.equal(result.reachesBudgetAt, "2026-09-21T00:00:00.000Z")
  assert.equal(result.alreadyReached, false)
})

test("includes today's fraction when the source total includes today's spend", () => {
  const result = calculate({ spent_usd: 52.5 }, new Date("2026-09-11T12:00:00Z"))
  assert.equal(result.elapsedDays, 10.5)
  assert.equal(result.dailyAverage, 5)
  assert.equal(result.projectedSpend, 150)
  assert.equal(result.reachesBudgetAt, "2026-09-21T00:00:00.000Z")
})

test("respects actual UTC month lengths, leap years, and the year boundary", () => {
  for (const [start, end, days] of [
    ["2026-02-01", "2026-03-01", 28], ["2028-02-01", "2028-03-01", 29],
    ["2026-09-01", "2026-10-01", 30], ["2026-12-01", "2027-01-01", 31],
  ]) {
    const result = calculate({}, new Date(`${start.slice(0,8)}11T00:00:00Z`), {period_start:start, period_end:end})
    assert.equal(result.monthDays, days)
    assert.equal(result.projectedSpend, 5 * days)
  }
})

test("under-budget and exact-budget projections do not invent a crossing before reset", () => {
  const under = calculate({ spent_usd: 20 })
  assert.equal(under.projectedSpend, 60)
  assert.equal(under.difference, -40)
  assert.equal(under.reachesBudgetAt, null)
  const exact = calculate({ amount_usd: 150 })
  assert.equal(exact.difference, 0)
  assert.equal(exact.reachesBudgetAt, null)
})

test("already-reached budgets do not show a fictional historical reach date", () => {
  for (const spent_usd of [100, 120]) {
    const result = calculate({ spent_usd })
    assert.equal(result.alreadyReached, true)
    assert.equal(result.reachesBudgetAt, null)
  }
})

test("unknown totals and zero with missing costs cannot become a zero forecast", () => {
  for (const overrides of [{spent_usd:null}, {spent_usd:0,unpriced_requests:2}, {spent_usd:NaN}, {spent_usd:-1}]) {
    assert.deepEqual(calculate(overrides), {available:false,reason:"incomplete"})
  }
})

test("partly measured spend produces a partial recorded-cost projection without a reach date", () => {
  for (const spent_usd of [0.10439135, 50, 120]) {
    const source = budget({spent_usd, unpriced_requests:1, amount_usd:2, requests:7})
    const before = structuredClone(source)
    const result = getBudgetForecast(source, period, now)
    assert.equal(result.available, true)
    assert.equal(result.partial, true)
    assert.equal(result.projectedSpend, spent_usd / 10 * 30)
    assert.equal(result.reachesBudgetAt, null)
    assert.equal(result.alreadyReached, spent_usd >= 2)
    assert.deepEqual(source, before)
  }
  assert.deepEqual(calculate({unpriced_requests:1}, new Date("2026-09-02T00:00:00Z")), {available:false,reason:"too_early"})
})

test("requires three elapsed days and measured activity; true zero stays zero", () => {
  assert.deepEqual(calculate({}, new Date("2026-09-03T23:59:59Z")), {available:false,reason:"too_early"})
  assert.equal(calculate({}, new Date("2026-09-04T00:00:00Z")).available, true)
  assert.deepEqual(calculate({requests:0,spent_usd:0}), {available:false,reason:"no_activity"})
  const zero = calculate({spent_usd:0})
  assert.equal(zero.projectedSpend, 0)
  assert.equal(zero.difference, -100)
  assert.equal(zero.reachesBudgetAt, null)
})

test("expired, future, malformed periods and clocks cannot produce forecasts", () => {
  for (const at of [new Date("2026-08-31T23:59:59Z"), new Date("2026-10-01T00:00:00Z"), new Date("bad")]) {
    assert.deepEqual(calculate({}, at), {available:false,reason:"invalid_period"})
  }
  assert.deepEqual(calculate({}, now, {period_start:"bad",period_end:"2026-10-01"}), {available:false,reason:"invalid_period"})
  assert.deepEqual(calculate({}, now, {period_start:"2026-10-01",period_end:"2026-09-01"}), {available:false,reason:"invalid_period"})
})

test("each scope uses its own spend, paused alerts still forecast, worker timestamps are irrelevant", () => {
  const account = budget()
  const before = structuredClone(account)
  assert.equal(getBudgetForecast(account, period, now).projectedSpend, 150)
  assert.deepEqual(account, before)
  const project = calculate({project_id:"project",spent_usd:10,amount_usd:40,enabled:false,state:"paused",last_checked_at:null})
  assert.equal(project.projectedSpend, 30)
  assert.equal(project.difference, -10)
  assert.equal(calculate({last_checked_at:"2026-09-10T23:59:00Z"}).projectedSpend, 150)
})

test("guards invalid limits and keeps tiny measured costs visible", () => {
  for (const amount_usd of [0, -1, Infinity, NaN]) assert.deepEqual(calculate({amount_usd}), {available:false,reason:"invalid_budget"})
  const result = calculate({spent_usd:1e-10})
  assert.ok(result.projectedSpend > 0)
  assert.notEqual(forecastMoney(result.projectedSpend), "$0.00")
  assert.notEqual(forecastMoney(0.000001), "$0.00")
  assert.equal(forecastMoney(0), "$0.00")
})
