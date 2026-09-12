export type DocumentFreshness = "not_reviewed" | "reviewed" | "review_due" | "changed" | "not_searchable"
export type DocumentInsight = {
  id: string; filename: string; status: string; chunk_count: number
  created_at: string; indexed_at: string | null; content_signature: string
  reviewed_at: string | null; review_due_at: string | null; freshness: DocumentFreshness
  included_queries: number | null; cited_answers: number | null
  helpful: number; not_helpful: number; last_cited_at: string | null
}
export type DocumentInsightsReport = {
  generated_at: string; project_id: string; window_days: number; review_after_days: number
  query_count: number; tracked_queries: number; answers_with_citations: number
  tracking_started_at: string | null; limited: boolean; scan_limit: number
  total_documents: number; matching_documents: number; offset: number; page_size: number
  items: DocumentInsight[]
}
export const DOCUMENT_INSIGHTS_KEY = "/api/account/knowledge-health/documents"
export function documentInsightsKey(project: string, days: string, search: string, offset: number) {
  const params = new URLSearchParams({ project_id: project, days, offset: String(offset) })
  if (search.trim()) params.set("search", search.trim())
  return `${DOCUMENT_INSIGHTS_KEY}?${params}`
}
export const FRESHNESS: Record<DocumentFreshness, { label: string; description: string; className: string }> = {
  not_reviewed: { label: "Not reviewed", description: "Check that the current document is still accurate, then record your review.", className: "text-muted-foreground" },
  reviewed: { label: "Reviewed", description: "This version was reviewed within the last 90 days.", className: "border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400" },
  review_due: { label: "Review due", description: "The last review was at least 90 days ago. Check whether the information is still current.", className: "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-400" },
  changed: { label: "Changed since review", description: "The document changed after its last review. Check the current version before recording a new review.", className: "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-400" },
  not_searchable: { label: "Not searchable", description: "Open Files to resolve indexing or version-review issues before recording a content review.", className: "text-muted-foreground" },
}
