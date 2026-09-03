export interface Project {
  id: string
  name: string
  description: string | null
  chunk_size: number
  chunk_overlap: number
  embedding_provider: string
  embedding_model: string
  embedding_dimensions: number
  // Width the vectors were originally computed at. Greater than
  // embedding_dimensions means the project is shrunk and the wider originals
  // are archived, so growing back up to this width is instant and free.
  // null means never shrunk - nothing is archived.
  embedding_native_dimensions: number | null
  llm_provider: string
  llm_model: string
  top_k: number
  // Answer policy (migration 0032). Always concrete - there is no "inherit"
  // state, so the form never has to render a blank that means "the global
  // default, whatever that currently is".
  min_similarity: number
  min_strong: number
  // null = mirror the question's language / no disclaimer.
  answer_language: string | null
  answer_disclaimer: string | null
  status: "empty" | "indexing" | "ready" | "error"
  // When true the public /v1 API + MCP are blocked (403) until resumed.
  suspended: boolean
  // Document versions (migration 0034). When on, an upload that looks like a
  // new edition of a document already here is held for review before it can
  // replace it. Per project because the extractor's question is just as true
  // of report_v2.pdf as of an amending Act.
  version_tracking: boolean
  created_at: string
  updated_at: string
  file_count: number
  chunk_count: number
  query_count: number
  // Masked per-project key overrides (null = using the account-level key).
  embedding_key_last4: string | null
  llm_key_last4: string | null
}

export type ProviderId =
  | "openai"
  | "gemini"
  | "anthropic"
  | "azure"
  | "sarvam"
  | "xai"
  | "groq"
  | "mistral"
  | "deepseek"
  | "cohere"
  | "together"
  | "fireworks"
  | "openrouter"
  | "perplexity"
  | "voyage"
  | "jina"

export interface ProviderKey {
  id: string
  provider: ProviderId
  label: string
  last4: string
  // When this key's reachable-model list was last read, and how many models it
  // saw. null = never read, in which case the pickers show the full static
  // catalog rather than hiding anything.
  models_fetched_at: string | null
  models_available: number | null
  created_at: string
  updated_at: string
}

export interface Memory {
  id: number
  content: string
  tags: string[]
  pinned: boolean
  source: string
  created_at: string
}

export interface FileRecord {
  id: string
  project_id: string
  filename: string
  content_type: string | null
  source_extension: string | null
  size_bytes: number | null
  page_count: number | null
  chunk_count: number
  // "review" (migration 0034) means: converted and stored, but held back from
  // chunking because it looks like a new version of a document already in the
  // project. A person confirms what it replaces before it is indexed.
  status: "pending" | "processing" | "indexed" | "failed" | "review"
  error: string | null
  conversion_error: string | null
  // Non-fatal caveat (e.g. audio used the free transcription fallback).
  conversion_note: string | null
  // Document versions (migration 0034). The lineage key is
  // `document_id ?? id` - null means this file is its own document.
  document_id: string | null
  version_label: string | null
  // ISO "YYYY-MM-DD". Render these RAW: `new Date("2019-04-01")` parses as UTC
  // midnight, so toLocaleDateString() shows the previous day in any
  // negative-offset timezone.
  in_force_from: string | null
  // Non-null = superseded: stored, downloadable, and holding no chunks.
  in_force_to: string | null
  legal_status:
    | "in_force"
    | "amended"
    | "repealed"
    | "draft"
    | "unknown"
    | null
  // Provenance (migration 0035). instrument_role says what KIND of document
  // this is; the four "refers to another document" roles cannot supersede.
  content_sha256: string | null
  extracted_title: string | null
  instrument_role:
    | "principal"
    | "consolidated"
    | "amending"
    | "correction"
    | "translation"
    | "supplement"
    | "unknown"
    | null
  created_at: string
  indexed_at: string | null
}

export interface ApiKey {
  id: string
  name: string
  key_prefix: string
  last_used_at: string | null
  created_at: string
  revoked_at: string | null
  // When true the key may ingest documents (POST /v1/projects/{id}/files);
  // read-only keys (default) can only query.
  can_upload: boolean
}

export interface ApiKeyCreated extends ApiKey {
  key: string
}

export interface SourceChunk {
  filename: string
  page_number: number | null
  chunk_index: number
  content: string
  similarity: number
  // True when the answer actually cited this block as [n]. `sources` is
  // everything retrieval returned, which is wider than what the answer used.
  cited?: boolean
}

export interface QueryResponse {
  answer: string
  sources: SourceChunk[]
  model: string
  latency_ms: number
  // Agentic loop transparency (optional - older responses may omit them).
  depth?: "short" | "long"
  sub_queries?: string[]
  // Human-in-the-loop: set when the loop couldn't ground an answer and is
  // asking you to clarify instead of guessing. `answer` then holds the prompt.
  needs_clarification?: boolean
  clarification_questions?: string[]
  // Echoed back for a conversational query (server-side memory).
  conversation_id?: string | null
  // Which cache served this answer: "l1" exact match, "l2" semantically
  // similar question, or null/undefined when computed fresh.
  cache_layer?: "l1" | "l2" | null
  cache_similarity?: number | null
  // Mean similarity of the sources behind this answer. null - never 0 - when
  // nothing was retrieved.
  retrieval_similarity?: number | null
}

/** Node in the project "brain" graph (files, sections, chunks, memories). */
export interface MemoryGraphNode {
  id: string
  type: "project" | "file" | "section" | "chunk" | "memory" | (string & {})
  label: string
  text?: string | null
  metadata: Record<string, unknown>
}

export interface MemoryGraphEdge {
  source: string
  target: string
  type: string
  metadata?: Record<string, unknown>
}

export interface MemoryGraphResponse {
  project: { id: string; name: string; status: string; file_count: number }
  nodes: MemoryGraphNode[]
  edges: MemoryGraphEdge[]
}

export interface EmbeddingModelEntry {
  model: string
  dimensions: number
  // Matryoshka (MRL) models can serve these smaller prefix sizes too; the
  // backend truncates stored vectors in place when shrinking within a model.
  dimension_options?: number[]
  // Retired upstream: the provider no longer serves it, so it must not be
  // offered to a new project. Still present in the catalog (and so still
  // resolvable) because projects that already chose it would otherwise error
  // on every read - they keep seeing it, marked, so the breakage is legible.
  deprecated?: boolean
}

/**
 * Retired model ids, per role and provider.
 *
 * Reported separately from the catalog rather than removed from it: the backend
 * still has to RESOLVE these for projects that already store them (validate_llm
 * runs on every query), so the only safe way to retire one is to stop offering
 * it. LLM entries are bare strings and cannot carry a flag of their own, which
 * is why this is a lookup rather than a property on the entry.
 */
export interface DeprecatedModels {
  llm: Record<string, string[] | undefined>
  embedding: Record<string, string[] | undefined>
}

export interface ModelsResponse {
  catalog: {
    embedding: Record<string, EmbeddingModelEntry[]>
    llm: Record<string, string[]>
  }
  // Optional: a backend older than this field simply hides nothing.
  deprecated?: DeprecatedModels
  availability: Record<string, boolean>
}

/*
 * GET /api/account/usage?days=N
 *
 * Everywhere `| null` appears below it means "the provider did not report
 * this" - unmeasured, which is NOT the same as zero. The UI must render null
 * as "not measured", never as 0: a provider that reports no token counts has
 * to stay visible as such, or the totals silently understate real spend.
 */

export interface UsageTotals {
  requests: number
  prompt_tokens: number | null
  completion_tokens: number | null
  cost_usd: number | null
  saved_prompt_tokens: number | null
  saved_completion_tokens: number | null
  /** Priced per row at write time from the model that produced the cached
   *  answer - a measurement, not a rate blended across the window. */
  saved_cost_usd: number | null
  /** The EMBEDDER's side: retrieval, ingestion, memory writes, cache probes.
   *  Kept apart from prompt_tokens because embedding tokens are 10-100x
   *  cheaper, so one combined number would be wrong for both. */
  embedding_tokens: number | null
  embedding_cost_usd: number | null
  /** Embedding avoided by a Matryoshka grow-back - vectors restored from the
   *  archive instead of re-embedded. Replayed from what the files originally
   *  cost, so null means "not measured", never zero. */
  saved_embedding_tokens: number | null
  saved_embedding_cost_usd: number | null
}

export interface UsageByModel {
  model: string
  requests: number
  prompt_tokens: number | null
  completion_tokens: number | null
  cost_usd: number | null
  /** "llm" answered questions; "embedding" produced vectors. Both appear in
   *  one list because "what did this account spend, by model" is one
   *  question - but they must be labelled, not silently mixed. */
  kind: "llm" | "embedding"
}

export interface UsageByApiKey {
  api_key_id: string
  key_prefix: string
  revoked: boolean
  requests: number
  prompt_tokens: number | null
  completion_tokens: number | null
  cost_usd: number | null
}

export interface UsageProjectCache {
  l1: number
  l2: number
  miss: number
  /** Fraction 0..1 of cacheable requests answered from L1 or L2. */
  hit_rate: number
}

export interface UsageByProject {
  project_id: string
  name: string
  requests: number
  cost_usd: number | null
  cache: UsageProjectCache
  avg_retrieval_similarity: number | null
  avg_cache_similarity: number | null
  saved_prompt_tokens: number | null
  saved_completion_tokens: number | null
}

export interface UsageDaily {
  /** YYYY-MM-DD */
  date: string
  requests: number
  prompt_tokens: number | null
  completion_tokens: number | null
  cost_usd: number | null
  saved_prompt_tokens: number | null
  embedding_tokens: number | null
  embedding_cost_usd: number | null
  /** Percentiles, never a mean - an average latency hides the tail it is
   *  asked about. p50 is the typical request, p95 the one users complain about. */
  p50_latency_ms: number | null
  p95_latency_ms: number | null
  p99_latency_ms: number | null
  cache_l1: number
  cache_l2: number
  cache_miss: number
  avg_retrieval_similarity: number | null
}

export interface UsageByEndpoint {
  endpoint: string
  requests: number
  prompt_tokens: number | null
  completion_tokens: number | null
  embedding_tokens: number | null
  cost_usd: number | null
  p50_latency_ms: number | null
}

export interface UsageCaveats {
  /** Requests whose provider reported no token usage - excluded from token/cost sums. */
  unmeasured_requests: number
  unmeasured_models: string[]
  /** Image captioning and audio transcription build their SDK clients directly
   *  rather than going through the provider factory, so no wrapper sees them.
   *  Ingestion-time embedding IS now counted. */
  vision_and_audio_excluded: boolean
}

export interface AccountUsage {
  window_days: number
  totals: UsageTotals
  by_model: UsageByModel[]
  by_endpoint: UsageByEndpoint[]
  by_api_key: UsageByApiKey[]
  by_project: UsageByProject[]
  daily: UsageDaily[]
  caveats: UsageCaveats
}
