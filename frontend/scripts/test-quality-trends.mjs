import assert from "node:assert/strict"
import test from "node:test"
import { evaluationChange, qualityChange, qualityTrendsKey } from "../src/lib/quality-trends.ts"

test("comparisons require complete periods and enough measurements on both sides", () => {
  const current = { complete: true, rated: 10, helpful_percent: 80, measured: 8, low_match_percent: 25 }
  const previous = { ...current, helpful_percent: 60, low_match_percent: 50 }
  assert.equal(qualityChange(current, previous, "helpful_percent"), 20)
  assert.equal(qualityChange(current, previous, "low_match_percent"), -25)
  for (const patch of [{ complete: false }, { rated: 4 }, { helpful_percent: null }]) {
    assert.equal(qualityChange({ ...current, ...patch }, previous, "helpful_percent"), null)
    assert.equal(qualityChange(current, { ...previous, ...patch }, "helpful_percent"), null)
  }
})
test("evaluation comparisons do not turn partial checks into quality improvements", () => {
  const current = { expected: 2, checked: 2, pass_percent: 100 }
  const previous = { ...current, pass_percent: 0 }
  assert.equal(evaluationChange(current, previous), 100)
  assert.equal(evaluationChange(current), null)
  assert.equal(evaluationChange(current, { ...previous, checked: 1 }), null)
  assert.equal(evaluationChange({ ...current, expected: 0 }, previous), null)
})
test("cache keys distinguish scope, period and source", () => {
  assert.equal(qualityTrendsKey("30", ""), "/api/account/knowledge-health/trends?days=30")
  assert.notEqual(qualityTrendsKey("30", "a"), qualityTrendsKey("7", "a"))
  assert.notEqual(qualityTrendsKey("30", "a"), qualityTrendsKey("30", "b"))
  assert.match(qualityTrendsKey("30", "a", true), /evaluation-trends/)
})
