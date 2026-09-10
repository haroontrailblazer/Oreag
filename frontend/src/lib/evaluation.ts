import type { QueryResponse } from "./types"

export type EvaluationCase = { id: string; question: string; expected: string; match: "contains" | "exact"; source: string }
export type EvaluationSuite = { version: 1; cases: EvaluationCase[]; topK: [number, number]; compare: boolean }
export type EvaluationResult = { caseId: string; variant: number; status: "passed" | "failed" | "review" | "error" | "cancelled"; response?: QueryResponse; error?: string }
export const MAX_CASES = 20

export function parseSuite(value: unknown): EvaluationSuite {
  if (!value || typeof value !== "object") throw new Error("Choose an evaluation test set JSON file.")
  const suite = value as EvaluationSuite
  if (suite.version !== 1 || !Array.isArray(suite.cases) || suite.cases.length > MAX_CASES ||
    !Array.isArray(suite.topK) || suite.topK.length !== 2 || suite.topK.some(k => !Number.isInteger(k) || k < 1 || k > 20) || typeof suite.compare !== "boolean") {
    throw new Error("Invalid test set. Use version 1, up to 20 questions, and top_k values from 1 to 20.")
  }
  const ids = new Set<string>()
  const cases = suite.cases.map(item => {
    if (!item || typeof item.id !== "string" || !item.id || item.id.length > 100 || ids.has(item.id) ||
      typeof item.question !== "string" || item.question.length > 4000 || typeof item.expected !== "string" || item.expected.length > 4000 ||
      typeof item.source !== "string" || item.source.length > 500 || !["contains", "exact"].includes(item.match)) {
      throw new Error("Invalid question. Questions and expected text allow up to 4,000 characters; source names allow 500.")
    }
    ids.add(item.id)
    return { id: item.id, question: item.question, expected: item.expected, match: item.match, source: item.source }
  })
  return { version: 1, cases, topK: [suite.topK[0], suite.topK[1]], compare: suite.compare }
}

function normalize(text: string) { return text.normalize("NFKC").toLowerCase().replace(/\s+/gu, " ").trim() }

/** Transparent text/source checks, never a claim of semantic answer correctness. */
export function evaluateAnswer(item: EvaluationCase, response: QueryResponse): "passed" | "failed" | "review" {
  const expected = normalize(item.expected)
  const source = normalize(item.source)
  if (!expected && !source) return "review"
  const answer = normalize(response.answer)
  const textMatches = !expected || (item.match === "exact" ? answer === expected : answer.includes(expected))
  const sourceMatches = !source || response.sources.some(s => normalize(s.filename) === source)
  return textMatches && sourceMatches ? "passed" : "failed"
}

export async function runEvaluation(suite: EvaluationSuite, query: (question: string, topK: number, signal: AbortSignal) => Promise<QueryResponse>, signal: AbortSignal, onResult: (result: EvaluationResult) => void) {
  for (const item of suite.cases) {
    for (let variant = 0; variant < (suite.compare ? 2 : 1); variant++) {
      if (signal.aborted) return
      try {
        const response = await query(item.question.trim(), suite.topK[variant], signal)
        if (signal.aborted) { onResult({ caseId: item.id, variant, status: "cancelled" }); return }
        onResult({ caseId: item.id, variant, status: evaluateAnswer(item, response), response })
      } catch (error) {
        if (signal.aborted) { onResult({ caseId: item.id, variant, status: "cancelled" }); return }
        onResult({ caseId: item.id, variant, status: "error", error: error instanceof Error ? error.message : "Query failed" })
        // Do not hammer exhausted budgets, expired sessions, or unavailable providers.
        const status = (error as { status?: number } | null)?.status
        if (status === 401 || status === 403 || status === 429 || (status && status >= 500)) return
      }
    }
  }
}
