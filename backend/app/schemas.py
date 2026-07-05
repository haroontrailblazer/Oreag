import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Per-project BYOK key override fields. None = leave unchanged; "" = clear
# (fall back to the account-level key); any other value = set for this project.


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    chunk_size: int = Field(default=1000, ge=100, le=8000)
    chunk_overlap: int = Field(default=200, ge=0)
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    # None = the model's default size; MRL models also accept smaller prefixes.
    embedding_dimensions: int | None = None
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    top_k: int = Field(default=5, ge=1, le=20)
    embedding_api_key: str | None = None
    llm_api_key: str | None = None


class ProjectUpdate(BaseModel):
    """Safe, instant edits. Chunking/embedding changes go through /reindex."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)
    # Changing a key (not the model) is a safe, instant edit - no reindex needed.
    embedding_api_key: str | None = None
    llm_api_key: str | None = None


class ReindexRequest(BaseModel):
    """Optional new config; project chunks are wiped and all files re-ingested.

    Exception: shrinking the SAME Matryoshka model's dimensions truncates the
    stored vectors in place - instant, no re-embedding.
    """

    chunk_size: int | None = Field(default=None, ge=100, le=8000)
    chunk_overlap: int | None = Field(default=None, ge=0)
    embedding_provider: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    embedding_api_key: str | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    chunk_size: int
    chunk_overlap: int
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    llm_provider: str
    llm_model: str
    top_k: int
    status: str
    created_at: datetime
    updated_at: datetime
    file_count: int = 0
    chunk_count: int = 0
    query_count: int = 0
    # Masked display of any per-project key override (null = using account key).
    embedding_key_last4: str | None = None
    llm_key_last4: str | None = None


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    content_type: str | None = None
    source_extension: str | None = None
    size_bytes: int | None
    page_count: int | None
    chunk_count: int
    status: str
    error: str | None
    conversion_error: str | None = None
    created_at: datetime
    indexed_at: datetime | None


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    key_prefix: str
    last_used_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None
    can_upload: bool = False


class ApiKeyCreated(ApiKeyOut):
    key: str  # full key, returned exactly once


class ApiKeyCreate(BaseModel):
    name: str = Field(default="default", min_length=1, max_length=100)
    can_upload: bool = False


class ApiKeyUpdate(BaseModel):
    can_upload: bool | None = None


class ProviderKeyCreate(BaseModel):
    provider: Literal["openai", "gemini", "anthropic", "sarvam"]
    key: str = Field(min_length=8, max_length=500)
    label: str = Field(default="default", min_length=1, max_length=100)


class ProviderKeyOut(BaseModel):
    """Masked view - the raw/encrypted key is never serialized."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    label: str
    last4: str
    created_at: datetime
    updated_at: datetime


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    # Opaque id tying queries into a conversation. When set, the server loads the
    # prior turns, rewrites this follow-up to be standalone, and remembers the new
    # turn. Omit for a one-off, stateless query.
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)


class SourceChunk(BaseModel):
    filename: str
    page_number: int | None
    chunk_index: int
    content: str
    similarity: float


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    model: str
    latency_ms: int
    # Agentic loop transparency (defaults keep older clients working):
    depth: str = "short"  # "short" or "long" - how the question was classified
    sub_queries: list[str] = Field(default_factory=list)  # the loop's queries
    # Human-in-the-loop: set when the loop couldn't ground an answer and is
    # asking the caller to clarify instead of guessing.
    needs_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list)
    # Echoed back when the query was part of a conversation (else null).
    conversation_id: str | None = None


class ProjectInfo(BaseModel):
    """Lightweight public info for /v1 consumers."""

    id: uuid.UUID
    name: str
    status: str
    file_count: int
    chunk_count: int = 0


class MemoryGraphNode(BaseModel):
    id: str
    type: str
    label: str
    text: str | None = None
    metadata: dict = Field(default_factory=dict)


class MemoryGraphEdge(BaseModel):
    source: str
    target: str
    type: str
    metadata: dict = Field(default_factory=dict)


class MemoryGraphResponse(BaseModel):
    project: ProjectInfo
    nodes: list[MemoryGraphNode]
    edges: list[MemoryGraphEdge]


# --- Agent memory (MCP) ---------------------------------------------------


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    tags: list[str] = Field(default_factory=list)
    pinned: bool = False
    source: str = Field(default="mcp", max_length=50)


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content: str
    tags: list[str]
    pinned: bool
    source: str
    created_at: datetime
    warning: str | None = None  # set when stored without an embedding


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class MemorySearchResult(MemoryOut):
    similarity: float


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class BrainExploreRequest(BaseModel):
    """Agentic, graph-aware retrieval over the brain (chunks + memories)."""

    query: str = Field(min_length=1, max_length=4000)
    hops: int = Field(default=1, ge=0, le=3)


class BrainExploreResponse(BaseModel):
    query: str
    seeds: list[str]  # node ids the walk started from (most relevant)
    nodes: list[MemoryGraphNode]
    edges: list[MemoryGraphEdge]
