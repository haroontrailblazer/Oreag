export const KNOWLEDGE_HEALTH_KEY = "/api/account/knowledge-health"

export type ProjectHealth = {
  id: string
  name: string
  suspended: boolean
  current_files: number
  searchable_files: number
  indexed_chunks: number
  failed_files: number
  review_files: number
  indexing_files: number
  empty_indexed_files: number
  unknown_files: number
  duplicate_copies: number
  last_indexed_at: string | null
  total_queries?: number
  cached_queries?: number
  helpful_queries?: number
  not_helpful_queries?: number
  fresh_queries: number
  measured_queries: number
  avg_retrieval_similarity: number | null
}

export type KnowledgeHealth = {
  generated_at: string
  query_window_days: number
  projects: ProjectHealth[]
}

export type HealthState = "attention" | "paused" | "indexing" | "empty" | "ready"
export const HEALTH_LABELS: Record<HealthState, string> = {
  attention: "Needs attention", paused: "Paused", indexing: "Indexing", empty: "No searchable files", ready: "Ready",
}

export function healthState(project: ProjectHealth): HealthState {
  if (project.failed_files || project.review_files || project.empty_indexed_files || project.unknown_files) return "attention"
  if (project.suspended) return "paused"
  if (project.indexing_files) return "indexing"
  if (!project.searchable_files) return "empty"
  return "ready"
}

export function healthIssues(project: ProjectHealth) {
  const issues: { title: string; description: string; tab: "files" | "settings" | "playground" }[] = []
  if (project.failed_files) issues.push({ title: `${project.failed_files} failed indexing`, description: "Open Files to inspect the error, fix the cause, and retry indexing.", tab: "files" })
  if (project.review_files) issues.push({ title: `${project.review_files} awaiting version review`, description: "Confirm which document each upload replaces before its content can be indexed.", tab: "files" })
  if (project.empty_indexed_files) issues.push({ title: `${project.empty_indexed_files} indexed with no chunks`, description: "Inspect these documents for extractable content before re-indexing them.", tab: "files" })
  if (project.unknown_files) issues.push({ title: `${project.unknown_files} with an unrecognized status`, description: "Inspect the file status before treating these documents as ready.", tab: "files" })
  if (project.suspended) issues.push({ title: "Public access is paused", description: "The public API and MCP are blocked. Review project settings when you are ready to resume.", tab: "settings" })
  if (project.indexing_files) issues.push({ title: `${project.indexing_files} queued or indexing`, description: "Processing is still in progress. Open Files to follow the current status.", tab: "files" })
  if (!project.searchable_files && !project.indexing_files) issues.push({ title: "No searchable files", description: "Add documents or resolve the file issues so this project has indexed content to retrieve.", tab: "files" })
  if (project.duplicate_copies) issues.push({ title: `${project.duplicate_copies} extra identical upload${project.duplicate_copies === 1 ? "" : "s"}`, description: "These current files have matching original-upload hashes within this project. Review whether the copies are intentional before removing anything.", tab: "files" })
  if (!project.measured_queries) issues.push({ title: "No recent retrieval measurements", description: "Send representative questions through the query API, or test them in Playground. Only uncached queries with a recorded similarity contribute to this measurement.", tab: "playground" })
  return issues
}

export function healthProjectLink(id: string, tab: "files" | "settings" | "playground") {
  return `/projects/${encodeURIComponent(id)}?tab=${tab}`
}

export function healthSimilarity(value: number | null) {
  return value == null ? "Not measured" : value.toFixed(3)
}

const priority: Record<HealthState, number> = { attention: 0, empty: 1, indexing: 2, paused: 3, ready: 4 }
export function sortedHealthProjects(projects: ProjectHealth[], search: string, state: string) {
  return projects.filter(project => project.name.toLowerCase().includes(search.trim().toLowerCase()) && (state === "all" || healthState(project) === state))
    .sort((a, b) => priority[healthState(a)] - priority[healthState(b)] || a.name.localeCompare(b.name) || a.id.localeCompare(b.id))
}
