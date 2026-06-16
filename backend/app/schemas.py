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
    # Changing a key (not the model) is a safe, instant edit — no reindex needed.
    embedding_api_key: str | None = None
    llm_api_key: str | None = None


class ReindexRequest(BaseModel):
    """Optional new config; project chunks are wiped and all files re-ingested."""

    chunk_size: int | None = Field(default=None, ge=100, le=8000)
    chunk_overlap: int | None = Field(default=None, ge=0)
    embedding_provider: str | None = None
    embedding_model: str | None = None
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


class ApiKeyCreated(ApiKeyOut):
    key: str  # full key, returned exactly once


class ApiKeyCreate(BaseModel):
    name: str = Field(default="default", min_length=1, max_length=100)


class ProviderKeyCreate(BaseModel):
    provider: Literal["openai", "gemini", "anthropic"]
    key: str = Field(min_length=8, max_length=500)
    label: str = Field(default="default", min_length=1, max_length=100)


class ProviderKeyOut(BaseModel):
    """Masked view — the raw/encrypted key is never serialized."""

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
