import assert from "node:assert/strict"
import { test } from "node:test"
import { DEFAULT_GAP_FILTERS, knowledgeGapsKey, gapDetailKey, gapStatus } from "../src/lib/knowledge-gaps.ts"

test("default inbox and project/time filters have separate cache keys", () => {
  const original = structuredClone(DEFAULT_GAP_FILTERS)
  const url = new URL(knowledgeGapsKey({ ...original, project: "project", days: "7", status: "resolved", recurring: true, search: "refund & return?" }, 25), "http://localhost")
  assert.equal(url.searchParams.get("project_id"), "project")
  assert.equal(url.searchParams.get("search"), "refund & return?")
  assert.equal(url.searchParams.get("status"), "resolved")
  assert.equal(url.searchParams.get("days"), "7")
  assert.equal(url.searchParams.get("recurring"), "true")
  assert.equal(url.searchParams.get("offset"), "25")
  assert.deepEqual(DEFAULT_GAP_FILTERS, original)
  assert.notEqual(knowledgeGapsKey(), knowledgeGapsKey({ ...original, project: "project" }))
})

test("detail keys isolate groups and evidence pages and encode path segments", () => {
  assert.equal(gapDetailKey("p/1", "a?b", "30", 25), "/api/account/knowledge-gaps/p%2F1/a%3Fb?days=30&limit=25&offset=25")
  assert.notEqual(gapDetailKey("p", "key", "7"), gapDetailKey("p", "key", "30"))
})

test("new evidence is distinct from an explicitly open or resolved review", () => {
  assert.equal(gapStatus({ status: "open", reopened: true }), "New evidence")
  assert.equal(gapStatus({ status: "open", reopened: false }), "Needs review")
  assert.equal(gapStatus({ status: "resolved", reopened: false }), "Closed review")
  assert.equal(gapStatus({ status: "resolved", reopened: false, verification_run_id: "test" }), "Resolved with checks")
  assert.equal(gapStatus({ status: "open", reopened: true, verification_run_id: "older-test" }), "New evidence")
})
