import assert from "node:assert/strict"
import { test } from "node:test"
import { DEFAULT_QUERY_FILTERS, queryExplorerKey, queryLatency, querySimilarity } from "../src/lib/query-explorer.ts"

test("prefetch and page share the default key; filter values are encoded", () => {
  assert.equal(queryExplorerKey(), "/api/account/queries?days=30&limit=25")
  const url = new URL(queryExplorerKey({ ...DEFAULT_QUERY_FILTERS, project: "a", search: "  a&b %_  ", cache: "l2", latency: "3000" }, "9007199254740993"), "https://test.local")
  assert.equal(url.searchParams.get("search"), "a&b %_")
  assert.equal(url.searchParams.get("before"), "9007199254740993")
  assert.equal(url.searchParams.get("project_id"), "a")
  assert.equal(url.searchParams.get("cache"), "l2")
  assert.equal(url.searchParams.get("min_latency_ms"), "3000")
})

test("missing measurements are distinct from measured zero", () => {
  assert.equal(queryLatency(null), "Not measured")
  assert.equal(queryLatency(0), "0 ms")
  assert.equal(queryLatency(3150), "3.15 s")
  assert.equal(querySimilarity(null), "Not measured")
  assert.equal(querySimilarity(0), "0.000")
})
