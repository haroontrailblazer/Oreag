export type QueryRecord = {
  id: string
  project_id: string
  project_name: string
  question: string
  created_at: string
  latency_ms: number | null
  top_k: number | null
  cache_layer: string | null
  retrieval_similarity: number | null
  cache_similarity: number | null
  feedback_rating?: "helpful" | "not_helpful" | null
  feedback_note?: string | null
  feedback_updated_at?: string | null
}

export type QueryPage = { items: QueryRecord[]; next_cursor: string | null }
export type QueryFilters = { days: string; project: string; search: string; cache: string; latency: string; feedback: string }
export const DEFAULT_QUERY_FILTERS: QueryFilters = { days: "30", project: "", search: "", cache: "all", latency: "", feedback: "all" }

export function queryExplorerKey(filters: QueryFilters = DEFAULT_QUERY_FILTERS, before?: string) {
  const params = new URLSearchParams({ days: filters.days, limit: "25" })
  if (filters.project) params.set("project_id", filters.project)
  if (filters.search.trim()) params.set("search", filters.search.trim())
  if (filters.cache !== "all") params.set("cache", filters.cache)
  if (filters.latency) params.set("min_latency_ms", filters.latency)
  if (filters.feedback && filters.feedback !== "all") params.set("feedback", filters.feedback)
  if (before) params.set("before", before)
  return `/api/account/queries?${params}`
}

export function queryLatency(value: number | null) {
  return value == null ? "Not measured" : value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(2)} s`
}

export function querySimilarity(value: number | null) {
  return value == null ? "Not measured" : value.toFixed(3)
}

export function queryCacheLabel(value: string | null) {
  return value === "l1" ? "Exact cache" : value === "l2" ? "Semantic cache" : value == null ? "Fresh" : value
}
