export const KNOWLEDGE_GAPS_KEY = "/api/account/knowledge-gaps"

export type GapItem = {
  project_id: string; project_name: string; question_key: string; question: string
  query_count: number; flagged_count: number; not_helpful_count: number; weak_evidence_count: number
  helpful_count: number; unmeasured_count: number; first_seen: string; last_seen: string
  status: "open" | "resolved"; reopened: boolean; revision: number; note: string | null
  resolved_at: string | null; updated_at: string | null; evidence_version: string
  verification_run_id?: string | null
}
export type GapEvidence = {
  id: string; question: string; created_at: string; feedback_rating: string | null
  feedback_note: string | null; retrieval_similarity: number | null; cache_layer: string | null
  not_helpful: boolean; weak_evidence: boolean
}
export type GapReport = {
  generated_at: string; window_days: number; scanned_queries: number; scan_limit: number; limited: boolean
  weak_similarity_threshold: number; open_groups: number; resolved_groups: number; flagged_queries: number
  matched_groups: number; items: GapItem[]; next_offset: number | null
}
export type GapDetail = {
  item: GapItem; window_days: number; limited: boolean; scanned_queries: number; scan_limit: number
  weak_similarity_threshold: number; evidence: GapEvidence[]; evidence_total: number; next_offset: number | null
}
export type GapFilters = { days: string; project: string; status: string; search: string; recurring: boolean }
export const DEFAULT_GAP_FILTERS: GapFilters = { days: "30", project: "", status: "open", search: "", recurring: false }

export function knowledgeGapsKey(filters: GapFilters = DEFAULT_GAP_FILTERS, offset = 0) {
  const params = new URLSearchParams({ days: filters.days, status: filters.status, limit: "25" })
  if (filters.project) params.set("project_id", filters.project)
  if (filters.search.trim()) params.set("search", filters.search.trim())
  if (filters.recurring) params.set("recurring", "true")
  if (offset) params.set("offset", String(offset))
  return `${KNOWLEDGE_GAPS_KEY}?${params}`
}

export function gapDetailKey(project: string, key: string, days: string, offset = 0) {
  const params = new URLSearchParams({ days, limit: "25" })
  if (offset) params.set("offset", String(offset))
  return `${KNOWLEDGE_GAPS_KEY}/${encodeURIComponent(project)}/${encodeURIComponent(key)}?${params}`
}

export function gapStatus(item: Pick<GapItem, "status" | "reopened">) {
  return item.reopened ? "New evidence" : item.status === "resolved" ? "Resolved" : "Needs review"
}
