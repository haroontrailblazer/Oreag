export type Source = { filename: string; page_number: number | null; chunk_index: number; content: string; similarity: number; cited: boolean };
export type QueryResponse = { query_id: string | null; answer: string; sources: Source[]; model: string; latency_ms: number; depth: string; sub_queries: string[]; needs_clarification: boolean; clarification_questions: string[]; conversation_id: string | null; cache_layer: "l1" | "l2" | null; cache_similarity: number | null; retrieval_similarity: number | null };
export type QueryOptions = { top_k?: number; conversation_id?: string; signal?: AbortSignal };
export type StreamEvent = { type: "token"; text: string } | { type: "done"; response: QueryResponse } | { type: "ping" };
export type Feedback = { query_id: string; rating: "helpful" | "not_helpful" | null; note: string | null; updated_at: string | null };
export type QueryRecord = { feedback_rating: "helpful" | "not_helpful" | null; feedback_note: string | null; id: string; project_id: string; project_name: string; question: string; created_at: string; latency_ms: number | null; timeline: { total_ms: number; trace_id: string; spans: { stage: string; start_ms: number; duration_ms: number; success: boolean }[] } | null };
export type UploadedFile = { id: string; filename: string; status: string; [key: string]: unknown };
export type EvaluationSuite = { version: 2; cases: { id: string; question: string; expected?: string; source?: string; match?: "contains" | "exact" }[]; variants: { llm_provider: string; llm_model: string; embedding_provider: string; embedding_model: string; embedding_dimensions: number; top_k?: number; [key: string]: unknown }[] };
export type EvaluationRun = { id: string; status: "preparing" | "running" | "completed" | "failed" | "cancelled"; suite: EvaluationSuite; execution: "background" | "manual"; results: Record<string, unknown>[]; quality_report: Record<string, unknown> | null; error: string | null };
export class OreagError extends Error { status: number; detail: unknown; retryAfter: string | null }
export class OreagClient {
  constructor(options: { apiKey: string; projectId: string; baseUrl?: string; fetch?: typeof fetch });
  query(question: string, options?: QueryOptions): Promise<QueryResponse>;
  streamQuery(question: string, options?: QueryOptions): AsyncGenerator<StreamEvent>;
  uploadFiles(files: { data: Blob; name: string }[], options?: { signal?: AbortSignal }): Promise<UploadedFile[]>;
  feedback(queryId: string, rating: "helpful" | "not_helpful", note?: string): Promise<Feedback>;
  clearFeedback(queryId: string): Promise<void>;
  getQuery(queryId: string): Promise<QueryRecord>;
  health(): Promise<Record<string, unknown>>;
  getTestSet(): Promise<{ revision: number; suite: EvaluationSuite | null }>;
  addToTestSet(queryId: string, expected: string, revision: number, options?: { source?: string; match?: "contains" | "exact" }): Promise<{ revision: number; suite: EvaluationSuite }>;
  startEvaluation(id: string, suite: EvaluationSuite, referenceRunId?: string | null): Promise<EvaluationRun>;
  getEvaluation(id: string): Promise<EvaluationRun>;
  cancelEvaluation(id: string): Promise<EvaluationRun>;
}
