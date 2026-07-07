export interface Project {
  id: string
  name: string
  description: string | null
  chunk_size: number
  chunk_overlap: number
  embedding_provider: string
  embedding_model: string
  embedding_dimensions: number
  llm_provider: string
  llm_model: string
  top_k: number
  status: "empty" | "indexing" | "ready" | "error"
  // When true the public /v1 API + MCP are blocked (403) until resumed.
  suspended: boolean
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
  status: "pending" | "processing" | "indexed" | "failed"
  error: string | null
  conversion_error: string | null
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
}

export interface ModelsResponse {
  catalog: {
    embedding: Record<string, EmbeddingModelEntry[]>
    llm: Record<string, string[]>
  }
  availability: Record<string, boolean>
}
