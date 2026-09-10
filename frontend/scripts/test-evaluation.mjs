import assert from "node:assert/strict"
import { test } from "node:test"
import { evaluateAnswer, importEvaluation, parseSuite, runEvaluation } from "../src/lib/evaluation.ts"

const item = { id: "one", question: "What is the policy?", expected: "30 days", match: "contains", source: "policy.pdf" }
const response = { answer: "Returns within 30 DAYS.", sources: [{ filename: "policy.pdf" }], latency_ms: 100, model: "test" }
const suite = { version: 1, cases: [item], topK: [5, 10], compare: true }

test("database configuration import upgrades old sets and keeps variants independent", () => {
  const config = { llm_provider: "openai", llm_model: "gpt-4o-mini", embedding_provider: "openai", embedding_model: "text-embedding-3-small", embedding_dimensions: 1536, top_k: 5, min_similarity: .2, min_strong: 0, hybrid_search: true, include_memories: true }
  const imported = importEvaluation(suite, config)
  assert.equal(imported.version, 2)
  assert.deepEqual(imported.variants.map(v => v.top_k), [5, 10])
  imported.variants[1].embedding_dimensions = 512
  assert.equal(imported.variants[0].embedding_dimensions, 1536)
  assert.equal(config.embedding_dimensions, 1536)
  assert.equal(importEvaluation(imported, config).variants[1].embedding_dimensions, 512)
  assert.throws(() => importEvaluation({ ...imported, variants: [] }, config))
  assert.throws(() => importEvaluation({ ...imported, variants: [{ ...config, embedding_dimensions: 0 }] }, config))
})

test("text and source rules must both match; missing expectations require review", () => {
  assert.equal(evaluateAnswer(item, response), "passed")
  assert.equal(evaluateAnswer(item, { ...response, sources: [] }), "failed")
  assert.equal(evaluateAnswer({ ...item, match: "exact" }, response), "failed")
  assert.equal(evaluateAnswer({ ...item, expected: " Returns   within 30 days. ", match: "exact" }, response), "passed")
  assert.equal(evaluateAnswer({ ...item, expected: "", source: "" }, response), "review")
  assert.equal(evaluateAnswer({ ...item, expected: "" }, response), "passed")
})

test("import validates sizes, versions, unique identities and actual API ranges", () => {
  assert.deepEqual(parseSuite(suite), suite)
  for (const invalid of [null, {}, { ...suite, version: 2 }, { ...suite, topK: [0, 10] }, { ...suite, topK: [5, 21] }, { ...suite, topK: [1.5, 2] }, { ...suite, cases: [item, item] }, { ...suite, cases: [{ ...item, question: "x".repeat(4001) }] }, { ...suite, cases: [null] }, { ...suite, cases: Array(21).fill(item) }]) {
    assert.throws(() => parseSuite(invalid))
  }
})

test("A/B execution is sequential and passes independent per-query settings", async () => {
  const calls = [], results = []
  let inFlight = 0
  await runEvaluation(suite, async (...args) => {
    assert.equal(++inFlight, 1)
    calls.push(args.slice(0, 2))
    await Promise.resolve()
    inFlight--
    return response
  }, new AbortController().signal, result => results.push(result))
  assert.deepEqual(calls, [[item.question, 5], [item.question, 10]])
  assert.deepEqual(results.map(r => [r.variant, r.status]), [[0, "passed"], [1, "passed"]])
})

test("single mode performs one query and cancellation stops the remaining queue", async () => {
  const results = []
  await runEvaluation({ ...suite, compare: false }, async () => response, new AbortController().signal, r => results.push(r))
  assert.equal(results.length, 1)
  const controller = new AbortController()
  const stopped = []
  await runEvaluation(suite, async () => { controller.abort(); return response }, controller.signal, r => stopped.push(r))
  assert.deepEqual(stopped.map(r => r.status), ["cancelled"])
})

test("budget/auth/provider failures halt the run; individual query failures stay visible", async () => {
  for (const status of [401, 403, 429, 503]) {
    const results = []
    await runEvaluation(suite, async () => { throw Object.assign(new Error("Unavailable"), { status }) }, new AbortController().signal, r => results.push(r))
    assert.equal(results.length, 1)
    assert.equal(results[0].status, "error")
  }
  const results = []
  let count = 0
  await runEvaluation(suite, async () => { if (!count++) throw new Error("Network error"); return response }, new AbortController().signal, r => results.push(r))
  assert.deepEqual(results.map(r => r.status), ["error", "passed"])
})
