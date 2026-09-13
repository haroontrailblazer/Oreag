import assert from "node:assert/strict"
import { existsSync } from "node:fs"
import { registerHooks } from "node:module"
import { test } from "node:test"
import { fileURLToPath } from "node:url"

// Resolve the same source aliases as Next while running the pure key planner.
registerHooks({ resolve(specifier, context, nextResolve) {
  if (specifier.startsWith("@/")) {
    return nextResolve(new URL(`../src/${specifier.slice(2)}.ts`, import.meta.url).href, context)
  }
  if (specifier.startsWith(".") && context.parentURL?.endsWith(".ts")) {
    const candidate = new URL(`${specifier}.ts`, context.parentURL)
    if (existsSync(fileURLToPath(candidate))) return nextResolve(candidate.href, context)
  }
  return nextResolve(specifier, context)
} })
const { dashboardDataKeys } = await import("../src/lib/navigation-data.ts")
const { queryExplorerKey } = await import("../src/lib/query-explorer.ts")
const { DEFAULT_FAILURE_FILTERS, failureKey } = await import("../src/lib/request-failures.ts")
const { DEFAULT_GAP_FILTERS, knowledgeGapsKey } = await import("../src/lib/knowledge-gaps.ts")
const project = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"

test("same-path Failed requests links warm failures instead of query history", () => {
  assert.deepEqual(dashboardDataKeys("/query-explorer", []), [queryExplorerKey()])
  assert.deepEqual(dashboardDataKeys("/query-explorer?view=failures", []), [failureKey(DEFAULT_FAILURE_FILTERS)])
})
test("Gaps uses its actual defaults and preserves an owned project filter", () => {
  assert.deepEqual(dashboardDataKeys("/knowledge-gaps", []), [knowledgeGapsKey()])
  assert.deepEqual(dashboardDataKeys(`/knowledge-gaps?project=${project}`, [project]), [knowledgeGapsKey({ ...DEFAULT_GAP_FILTERS, project })])
  assert.deepEqual(dashboardDataKeys(`/knowledge-gaps?project=${project}`, []), [])
  assert.deepEqual(dashboardDataKeys("/knowledge-gaps?project=invalid", []), [knowledgeGapsKey()])
})
test("Health prepares live quality trends alongside the project report", () => {
  assert.deepEqual(dashboardDataKeys("/knowledge-health", []), ["/api/account/knowledge-health", "/api/account/knowledge-health/trends?days=30"])
})
test("Usage warms budgets and operations as well as recorded usage", () => {
  assert.deepEqual(dashboardDataKeys("/settings/usage", []), ["/api/account/usage?days=30", "/api/account/budgets", "/api/account/operations"])
})
test("project deep links warm their initial data without querying unowned projects", () => {
  const base = `/api/projects/${project}`
  assert.deepEqual(dashboardDataKeys(`/projects/${project}?tab=memory`, [project]), [base, `${base}/files`, `${base}/memory`])
  assert.deepEqual(dashboardDataKeys(`/projects/${project}?tab=api`, [project]), [base, `${base}/files`, `${base}/keys`])
  assert.deepEqual(dashboardDataKeys(`/projects/${project}?tab=files`, []), [])
})
