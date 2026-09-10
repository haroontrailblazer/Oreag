import assert from "node:assert/strict"
import { test } from "node:test"
import { healthIssues, healthState, healthSimilarity, sortedHealthProjects, healthProjectLink } from "../src/lib/knowledge-health.ts"

const project = { id: "a", name: "Alpha", suspended: false, current_files: 2, searchable_files: 2, indexed_chunks: 10, failed_files: 0, review_files: 0, indexing_files: 0, empty_indexed_files: 0, unknown_files: 0, duplicate_copies: 0, last_indexed_at: null, fresh_queries: 0, measured_queries: 0, avg_retrieval_similarity: null }

test("readiness distinguishes empty, indexing, paused, and actionable issues", () => {
  assert.equal(healthState(project), "ready")
  assert.equal(healthState({ ...project, searchable_files: 0 }), "empty")
  assert.equal(healthState({ ...project, searchable_files: 0, indexing_files: 1 }), "indexing")
  assert.equal(healthState({ ...project, suspended: true }), "paused")
  for (const field of ["failed_files", "review_files", "empty_indexed_files", "unknown_files"]) {
    assert.equal(healthState({ ...project, [field]: 1, suspended: true }), "attention")
  }
})

test("duplicate copies and absent measurements are advisory, not evidence of failed indexing", () => {
  const p = { ...project, duplicate_copies: 2 }
  assert.equal(healthState(p), "ready")
  assert(healthIssues(p).some(issue => issue.title.includes("identical")))
  assert(healthIssues(p).some(issue => issue.tab === "playground"))
  assert.equal(healthSimilarity(null), "Not measured")
  assert.equal(healthSimilarity(0), "0.000")
})

test("filters and attention ordering leave the source report untouched", () => {
  const rows = [project, { ...project, id: "b", name: "Beta", failed_files: 1 }]
  assert.deepEqual(sortedHealthProjects(rows, "", "all").map(p => p.id), ["b", "a"])
  assert.equal(rows[0].id, "a")
  assert.deepEqual(sortedHealthProjects(rows, " ALP ", "ready").map(p => p.id), ["a"])
  assert.equal(sortedHealthProjects(rows, "Beta", "ready").length, 0)
  assert.equal(healthProjectLink("a/b", "files"), "/projects/a%2Fb?tab=files")
})

test("queued and processing states stay distinct, with attention taking priority", () => {
  const queued = { ...project, indexing_files: 2, queued_files: 2, processing_files: 0 }
  const indexing = { ...queued, indexing_files: 3, processing_files: 1 }
  assert.equal(healthState(queued), "queued")
  assert.equal(healthState(indexing), "indexing")
  assert.equal(healthState({ ...indexing, failed_files: 1 }), "attention")
  assert.equal(healthState({ ...queued, suspended: true }), "paused")
  assert.equal(sortedHealthProjects([queued, indexing], "", "queued").length, 1)
})
