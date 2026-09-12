export type QualityMetrics = {
  queries: number; helpful: number; not_helpful: number; rated: number
  document_queries: number; measured: number; low_match: number
  helpful_percent: number | null; low_match_percent: number | null; avg_similarity: number | null
}
export type QualityPeriod = QualityMetrics & { start: string; end: string; complete: boolean }
export type QualityTrendsReport = {
  generated_at: string; window_days: number; project_id: string | null
  current: QualityPeriod; previous: QualityPeriod
  daily: (QualityMetrics & { date: string; complete: boolean })[]
  limited: boolean; scanned_queries: number; scan_limit: number; weak_similarity_threshold: number
}
export type EvaluationPoint = {
  id: string; created_at: string; variant: number; passed: number; checked: number
  errors: number; unscored: number; expected: number; pass_percent: number | null
  latency_ms: number | null; cost_usd: number | null; archived: boolean
}
export type EvaluationTrendsReport = {
  generated_at: string; window_days: number; project_id: string; limited: boolean; run_limit: number
  series: { key: string; cases: number; models: string[]; points: EvaluationPoint[] }[]
}
export function qualityTrendsKey(days: string, project: string, evaluation = false) {
  const params = new URLSearchParams({ days })
  if (project) params.set("project_id", project)
  return `/api/account/knowledge-health/${evaluation ? "evaluation-trends" : "trends"}?${params}`
}
export function qualityChange(current: QualityPeriod, previous: QualityPeriod, metric: "helpful_percent" | "low_match_percent") {
  const count = metric === "helpful_percent" ? "rated" : "measured"
  if (!current.complete || !previous.complete || current[count] < 5 || previous[count] < 5 || current[metric] == null || previous[metric] == null) return null
  return current[metric] - previous[metric]
}
export function evaluationChange(current: EvaluationPoint, previous?: EvaluationPoint) {
  if (!previous || current.expected === 0 || current.expected !== previous.expected || current.checked !== current.expected || previous.checked !== previous.expected || current.pass_percent == null || previous.pass_percent == null) return null
  return current.pass_percent - previous.pass_percent
}
