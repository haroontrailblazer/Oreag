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
  created_at: string
  updated_at: string
  file_count: number
  chunk_count: number
  query_count: number
  // Masked per-project key overrides (null = using the account-level key).
  embedding_key_last4: string | null
  llm_key_last4: string | null
}

export type ProviderId = "openai" | "gemini" | "anthropic" | "sarvam"

export interface ProviderKey {
  id: string
  provider: ProviderId
  label: string
  last4: string
  created_at: string
  updated_at: string
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
}

export interface EmbeddingModelEntry {
  model: string
  dimensions: number
}

export interface ModelsResponse {
  catalog: {
    embedding: Record<string, EmbeddingModelEntry[]>
    llm: Record<string, string[]>
  }
  availability: Record<string, boolean>
}
