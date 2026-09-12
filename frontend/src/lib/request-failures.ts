export type FailureOutcome = "error" | "rejected" | "stream_error" | "disconnected"
export type FailedRequest = {
  id: string
  project_id: string | null
  project_name: string | null
  endpoint: string
  status_code: number
  outcome: FailureOutcome
  latency_ms: number | null
  first_token_ms: number | null
  created_at: string
}
export type FailurePage = { items: FailedRequest[]; next_cursor: string | null; as_of: string; window_hours: number; retention_days: number }
export type FailureFilters = { hours: string; project: string; search: string; outcome: string; status: string; latency: string }
export const DEFAULT_FAILURE_FILTERS: FailureFilters = { hours: "24", project: "", search: "", outcome: "all", status: "", latency: "" }
export const FAILURE_KEY = "/api/account/operations/failures"
export const FAILURE_VIEW = "/query-explorer?view=failures"
export const FAILURE_PERIODS = [{ value: "1", label: "Last hour" }, { value: "24", label: "Last 24 hours" }, { value: "168", label: "Last 7 days" }, { value: "720", label: "Last 30 days" }]
export const FAILURE_OUTCOMES: Record<FailureOutcome, { label: string; className: string }> = {
  error: { label: "Server error", className: "border-red-500/20 bg-red-500/10 text-red-700 dark:text-red-400" },
  rejected: { label: "Rejected", className: "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-400" },
  stream_error: { label: "Stream error", className: "border-red-500/20 bg-red-500/10 text-red-700 dark:text-red-400" },
  disconnected: { label: "Interrupted", className: "text-muted-foreground" },
}
export function failureKey(filters: FailureFilters, cursor?: string) {
  const params = new URLSearchParams({ hours: filters.hours, limit: "25" })
  if (filters.project) params.set("project_id", filters.project)
  if (filters.search.trim()) params.set("search", filters.search.trim())
  if (filters.outcome !== "all") params.set("outcome", filters.outcome)
  if (filters.status) params.set("status_code", filters.status)
  if (filters.latency) params.set("min_latency_ms", filters.latency)
  if (cursor) params.set("before", cursor)
  return `${FAILURE_KEY}?${params}`
}

export function failureGuidance(record: FailedRequest): { summary: string; steps: string[] } {
  if (record.outcome === "disconnected") return {
    summary: "The request was interrupted before the server finished handling it. The record does not identify who ended the connection.",
    steps: ["Check application cancellations, client timeouts, and proxy connection limits.", "For operations that change data, check whether they completed before sending them again."],
  }
  if (record.outcome === "stream_error") return {
    summary: "The response reported an error after streaming began. An HTTP 200 status only means the stream started; it does not mean the answer completed.",
    steps: ["Inspect the error event received by your application and server logs at this time.", "Keep partial answers marked as incomplete and handle stream error events in the client."],
  }
  const guidance: Record<number, { summary: string; steps: string[] }> = {
    400: { summary: "The server rejected the request as invalid.", steps: ["Check the request format and the error response received by your application."] },
    401: { summary: "Authentication was rejected for this recorded request.", steps: ["Check the credential used by your application and whether it is still valid."] },
    403: { summary: "The request was not allowed.", steps: ["Check project access, account or project suspension, and the error response."] },
    404: { summary: "The requested resource was not available to this caller.", steps: ["Check the project and resource IDs, and whether the caller can access them."] },
    408: { summary: "The request timed out.", steps: ["Check client and server timeout settings and request duration."] },
    409: { summary: "The request conflicted with the current resource state.", steps: ["Refresh the resource and inspect the error response before submitting it again."] },
    413: { summary: "The request was too large.", steps: ["Check upload and request size limits, then reduce the payload."] },
    415: { summary: "The request used an unsupported content type.", steps: ["Check the Content-Type header and supported file formats for this endpoint."] },
    422: { summary: "The request failed validation.", steps: ["Inspect the validation details returned to your application and correct the flagged fields."] },
    429: { summary: "The request exceeded an active limit.", steps: ["Reduce concurrent requests and use backoff. Respect Retry-After when the response provides it.", "Check the response for the specific rate or quota limit."] },
    502: { summary: "The server received an invalid response from an upstream service.", steps: ["Check upstream service availability and server logs at this time."] },
    503: { summary: "The service could not handle the request at this time.", steps: ["Check Operations for worker or capacity warnings, then inspect server logs for the specific cause."] },
    504: { summary: "An upstream service did not respond in time.", steps: ["Check upstream latency, timeouts, and server logs at this time."] },
  }
  return guidance[record.status_code] ?? (record.outcome === "error"
    ? { summary: "The server could not complete this request.", steps: ["Check server logs at this time and the error response received by your application.", "Check Operations for related availability or capacity warnings."] }
    : { summary: "The server rejected this request.", steps: ["Inspect the response received by your application to identify what needs to change."] })
}
