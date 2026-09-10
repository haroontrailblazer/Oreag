import type { Project, QueryResponse } from "./types"

export type EvaluationConfig = Pick<Project, "llm_provider" | "llm_model" | "embedding_provider" | "embedding_model" | "embedding_dimensions" | "top_k" | "min_similarity" | "min_strong" | "cross_lingual_floor" | "answer_language" | "answer_language_strict" | "answer_disclaimer" | "document_language"> & { hybrid_search: boolean; include_memories: boolean }
export type EvaluationDefinition = { version: 2; cases: EvaluationCase[]; variants: EvaluationConfig[] }
export type SavedEvaluation = { revision: number; suite: EvaluationDefinition | null }
export type QualityReport = { state: string; warnings: { variant: number; metric: string; change: number; limit: number }[] }
export type EvaluationRun = { archived_at?: string | null; execution?: "manual" | "background"; quality_report?: QualityReport | null; id: string; status: "preparing" | "running" | "completed" | "cancelled" | "failed"; suite: EvaluationDefinition; corpus_count: number; content_version: number; prepared: number; results: EvaluationResult[]; error: string | null; created_at: string; updated_at: string }

export function projectEvaluationConfig(project: Project): EvaluationConfig {
  return { llm_provider: project.llm_provider, llm_model: project.llm_model, embedding_provider: project.embedding_provider, embedding_model: project.embedding_model,
    embedding_dimensions: project.embedding_dimensions, top_k: project.top_k, min_similarity: project.min_similarity, min_strong: project.min_strong,
    cross_lingual_floor: project.cross_lingual_floor, answer_language: project.answer_language, answer_language_strict: project.answer_language_strict,
    answer_disclaimer: project.answer_disclaimer, document_language: project.document_language, hybrid_search: true, include_memories: true }
}

export function importEvaluation(value: unknown, baseline: EvaluationConfig): EvaluationDefinition {
  if (!value || typeof value !== "object") throw new Error("Choose an evaluation JSON test set.")
  if ((value as { version?: number }).version === 1) {
    const old = parseSuite(value)
    return { version: 2, cases: old.cases, variants: old.topK.slice(0, old.compare ? 2 : 1).map(top_k => ({ ...baseline, top_k })) }
  }
  const suite = value as EvaluationDefinition
  if (suite.version !== 2 || !Array.isArray(suite.variants) || suite.variants.length < 1 || suite.variants.length > 2) throw new Error("Choose a version 1 or 2 test set with one or two configurations.")
  const cases = parseSuite({ version: 1, cases: suite.cases, topK: [1, 2], compare: false }).cases
  const variants = suite.variants.map(config => {
    if (!config || typeof config !== "object") throw new Error("Invalid evaluation configuration.")
    const next = { ...baseline, ...config }
    if ([next.llm_provider, next.llm_model, next.embedding_provider, next.embedding_model].some(v => typeof v !== "string" || !v.trim()) ||
      !Number.isInteger(next.embedding_dimensions) || next.embedding_dimensions < 1 || next.embedding_dimensions > 8192 ||
      !Number.isInteger(next.top_k) || next.top_k < 1 || next.top_k > 20 || !Number.isInteger(next.min_strong) || next.min_strong < 0 || next.min_strong > 20 ||
      typeof next.min_similarity !== "number" || !Number.isFinite(next.min_similarity) || next.min_similarity < 0 || next.min_similarity > 1) throw new Error("Invalid model, dimension, or retrieval settings.")
    return next
  })
  return { version: 2, cases, variants }
}

export type EvaluationCase = { id: string; question: string; expected: string; match: "contains" | "exact"; source: string }
export type EvaluationSuite = { version: 1; cases: EvaluationCase[]; topK: [number, number]; compare: boolean }
export type EvaluationResult = { caseId: string; variant: number; status: "passed" | "failed" | "review" | "error" | "cancelled"; response?: QueryResponse; error?: string; feedback_rating?: "helpful" | "not_helpful" | null; feedback_note?: string | null }
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
