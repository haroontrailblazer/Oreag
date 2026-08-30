import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.types import TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, deferred, mapped_column

# Safe: config imports nothing from the app, so this cannot cycle. Used only to
# seed NEW projects' answer policy from the deployment defaults.
from .config import settings


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    chunk_size: Mapped[int] = mapped_column(Integer, default=1000)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=200)
    embedding_provider: Mapped[str] = mapped_column(Text, default="openai")
    embedding_model: Mapped[str] = mapped_column(Text, default="text-embedding-3-small")
    embedding_dimensions: Mapped[int] = mapped_column(Integer, default=1536)
    # Width the vectors were ORIGINALLY computed at (migration 0024). NULL or
    # == embedding_dimensions means never shrunk, so nothing is archived.
    # Greater means shrunk: ingestion embeds at this width and banks it, and a
    # grow back up to it restores from the archive instead of re-embedding.
    embedding_native_dimensions: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    llm_provider: Mapped[str] = mapped_column(Text, default="openai")
    llm_model: Mapped[str] = mapped_column(Text, default="gpt-4o-mini")
    top_k: Mapped[int] = mapped_column(Integer, default=5)
    # Answer policy (migration 0032). NOT NULL with defaults rather than
    # nullable-inherit: 0 and 0.0 are meaningful ("never abstain"), so an `or`
    # fallback would silently restore the global default while the UI showed 0.
    # The config values seed NEW projects; they no longer steer existing ones.
    min_similarity: Mapped[float] = mapped_column(
        Float, default=lambda: settings.agentic_min_similarity, server_default="0.2"
    )
    min_strong: Mapped[int] = mapped_column(
        Integer, default=lambda: settings.agentic_min_strong, server_default="1"
    )
    # NULL = mirror the question's language / no disclaimer. Both are read at
    # the single generation chokepoint, so they cost nothing when unset.
    answer_language: Mapped[str | None] = mapped_column(Text)
    answer_disclaimer: Mapped[str | None] = mapped_column(Text)
    # Optional per-project BYOK key overrides (Fernet ciphertext + last4 for
    # display). When null, key resolution falls back to the owner's account key.
    embedding_key_encrypted: Mapped[str | None] = mapped_column(Text)
    embedding_key_last4: Mapped[str | None] = mapped_column(Text)
    llm_key_encrypted: Mapped[str | None] = mapped_column(Text)
    llm_key_last4: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="empty")  # empty|indexing|ready|error
    # When true, all external access (public /v1 API + MCP) is blocked with a
    # 403 - the keys and data are kept, but the project is paused until resumed.
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    # Document versions (migration 0034). When true, an upload that looks like
    # a new edition of a document already in this project is held in
    # files.status = 'review' until a person confirms what it replaces. Per
    # PROJECT, not fleet-wide: the extractor's question ("is this a new edition
    # of something already here?") is just as true of report_v2.pdf, so a
    # global switch would park uploads in projects that never asked for it.
    # False leaves ingestion byte-identical to its pre-0034 behaviour, down to
    # making no extraction LLM call.
    version_tracking: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # Monotonic counter bumped on every chunk/memory write - the cache
    # signature for both answer-cache layers (replaces per-request COUNT(*)s).
    content_version: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class File(Base):
    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(Text)
    storage_path: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    source_extension: Mapped[str | None] = mapped_column(Text)
    markdown_storage_path: Mapped[str | None] = mapped_column(Text)
    chunk_size: Mapped[int | None] = mapped_column(Integer)
    chunk_overlap: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    page_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    # pending|processing|indexed|failed|review. "review" (migration 0034) means
    # converted and stored but held back from chunking because it looks like a
    # new edition of a document already here. It is inert in the queue by
    # construction: claim_next selects only 'pending' (or 'processing' with a
    # lapsed lease), and files_queue_idx does not index it.
    status: Mapped[str] = mapped_column(Text, default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    conversion_error: Mapped[str | None] = mapped_column(Text)
    # Non-fatal: the file indexed, but the uploader should know how (e.g. audio
    # fell back to the free transcription endpoint - no capable provider key).
    conversion_note: Mapped[str | None] = mapped_column(Text)
    # Which conversion pipeline wrote markdown_storage_path (migration 0023).
    # A re-index reuses that markdown only when this matches the running
    # CONVERSION_VERSION, so a pipeline fix invalidates older blobs instead of
    # silently resurrecting whatever it fixed.
    conversion_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Durable-queue bookkeeping: workers claim pending rows, take a lease and
    # bump attempts; an expired lease means the worker died mid-ingest and the
    # file is re-queued (up to the retry cap) instead of bulk-failed.
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # What this file cost to embed at ingest. Replayed as the saving when a
    # Matryoshka grow-back restores its vectors instead of re-embedding -
    # there is no way to know that cost at restore time without doing the
    # very work being avoided, so it has to come from the past.
    embedding_tokens: Mapped[int | None] = mapped_column(Integer)
    # Document versions (migration 0034). document_id groups the editions of
    # one document and is NOT a foreign key: a lineage must outlive the
    # deletion of any member, including the first. NULL means "this file is its
    # own document", so the lineage key is always coalesce(document_id, id).
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    version_label: Mapped[str | None] = mapped_column(Text)
    in_force_from: Mapped[date | None] = mapped_column(Date)
    # THE indexability switch. NOT NULL means superseded: the row keeps its
    # blobs, its conversion stamp and all its metadata, holds zero chunks, and
    # is skipped by every requeue path. Exclusive end of a half-open interval,
    # always written as the successor's in_force_from so the two cannot
    # disagree. legal_status deliberately does NOT gate anything - one
    # authority, so a descriptive edit can never drop a document out of search.
    in_force_to: Mapped[date | None] = mapped_column(Date)
    legal_status: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NulSafeText(TypeDecorator):
    """Text that drops NUL (0x00) bytes on the way into PostgreSQL.

    PostgreSQL text columns cannot hold 0x00, and psycopg raises DataError for
    the whole statement - so one stray byte fails an entire batch INSERT and
    reports it as a database error about a document that reads perfectly.

    Applied to the three columns that hold arbitrary EXTERNAL text: extracted
    document content, agent-written memories, and inbound questions. The primary
    fix lives upstream in services/conversion.py, which cleans extraction output
    before it is both chunked AND written to storage; this is the backstop for
    every other way text arrives - the MCP memory tools and the public /v1 query
    API among them - so the same opaque failure cannot reappear through a path
    nobody thought to sanitise.

    Bind-side only: existing rows are untouched and reads are unaffected.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if isinstance(value, str) and "\x00" in value:
            return value.replace("\x00", "")
        return value


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(NulSafeText)
    embedding = mapped_column(Vector)  # dimension varies per project
    # Full-fidelity original, banked by a Matryoshka shrink (migration 0024).
    # DEFERRED: it is never read by search, and loading a full ORM Chunk would
    # otherwise ship a second whole vector over the wire on every query.
    embedding_full = deferred(mapped_column(Vector, nullable=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text, default="default")
    key_prefix: Mapped[str] = mapped_column(Text)
    key_hash: Mapped[str] = mapped_column(Text, unique=True)
    # Read-only by default; only keys created with this true may ingest via
    # POST /v1/projects/{id}/files.
    can_upload: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderKey(Base):
    """Account-level BYOK provider credential (one per owner+provider)."""

    __tablename__ = "provider_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    provider: Mapped[str] = mapped_column(Text)  # openai|gemini|anthropic
    label: Mapped[str] = mapped_column(Text, default="default")
    encrypted_key: Mapped[str] = mapped_column(Text)
    last4: Mapped[str] = mapped_column(Text)
    # What this key can actually reach, fetched when the key is saved (see
    # migration 0022). NULL = never fetched, which readers treat as "no opinion"
    # and fall back to the full static catalog - so a vendor that is down, or
    # one that serves no models endpoint, can never empty a picker.
    models_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    models_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def models_available(self) -> int | None:
        """How many models this key was last seen to reach (None = unknown)."""
        if not self.models_json:
            return None
        return len(self.models_json.get("models") or ())


class Memory(Base):
    """Agent memory entry - saved and recalled via the MCP server."""

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(NulSafeText)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(Text, default="mcp")
    embedding = mapped_column(Vector)  # per-project dimension; nullable
    # Same contract as Chunk.embedding_full. Deferred for the same reason:
    # services/memory.py and memory_graph.py load whole Memory entities.
    embedding_full = deferred(mapped_column(Vector, nullable=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MemoryChunk(Base):
    """A split piece of a LONG memory, with its own embedding (migration 0025).

    Only exists for memories too long to be a single well-focused vector; short
    ones are served by Memory.embedding alone and have no rows here. Search
    scores both and keeps the best result per memory, so the parent stays the
    unit of record for pinning, tags, display and deletion.
    """

    __tablename__ = "memory_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    memory_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("memories.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(NulSafeText)
    embedding = mapped_column(Vector)
    embedding_full = deferred(mapped_column(Vector, nullable=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SemanticQueryCache(Base):
    """L2 answer cache: similar (not just identical) questions hit by cosine
    similarity on the cached question's embedding. Scoped to everything that
    could change the answer; rows expire by TTL."""

    __tablename__ = "semantic_query_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(NulSafeText)
    embedding = mapped_column(Vector)  # dimension varies per project
    content_signature: Mapped[str] = mapped_column(Text)
    embedding_provider: Mapped[str] = mapped_column(Text)
    embedding_model: Mapped[str] = mapped_column(Text)
    llm_provider: Mapped[str] = mapped_column(Text)
    llm_model: Mapped[str] = mapped_column(Text)
    top_k: Mapped[int] = mapped_column(Integer)
    result: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QueryLog(Base):
    __tablename__ = "query_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL")
    )
    question: Mapped[str] = mapped_column(NulSafeText)
    top_k: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    # Which cache served this query: "l1" (exact), "l2" (semantic), or NULL when
    # it was computed fresh. Powers the project-wide cache hit rate.
    cache_layer: Mapped[str | None] = mapped_column(Text)
    # Mean similarity of the chunks actually used - the best single signal for
    # "is retrieval working on this project", computed today and discarded.
    retrieval_similarity: Mapped[float | None] = mapped_column(Float)
    # How close the L2 match was. Without it nobody can tell whether
    # semantic_cache_min_similarity (0.75) is too loose.
    cache_similarity: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SuspendedAccount(Base):
    """Operator kill switch: an owner listed here has every project's public
    API traffic rejected (403). Inserted manually - there is no UI."""

    __tablename__ = "suspended_accounts"

    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageEvent(Base):
    """One row per public /v1 request - the attribution/billing trail that
    /retrieve, /explore and /memory-graph previously never wrote."""

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    endpoint: Mapped[str] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    # Which model produced them. Text rather than an FK: models are retired
    # from the catalog, and a usage row must stay readable afterwards.
    model: Mapped[str | None] = mapped_column(Text)
    # Priced at WRITE time. Deriving cost at read time would let a price change
    # silently rewrite every past invoice.
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6))
    # Tokens NOT spent because the cache answered. Set only on a hit - NULL on a
    # miss, which is a different fact from 0.
    saved_prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    saved_completion_tokens: Mapped[int | None] = mapped_column(Integer)
    # What those saved tokens were worth, priced from the ORIGINAL run's model
    # at write time - not blended from the window, which made a fixed set of
    # cache hits report a different saving as unrelated traffic arrived.
    saved_cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6))
    # The EMBEDDER's side of the same request, kept apart from the LLM's
    # because embedding tokens are 10-100x cheaper and pricing them together
    # would be wrong for both. Ingestion rows carry only these.
    embedding_tokens: Mapped[int | None] = mapped_column(Integer)
    embedding_model: Mapped[str | None] = mapped_column(Text)
    embedding_cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6))
    # Embedding NOT spent because a Matryoshka grow-back restored the vectors
    # from the archive instead of calling the provider. Replayed from what the
    # files originally cost, so it is a measurement like every other saving.
    saved_embedding_tokens: Mapped[int | None] = mapped_column(Integer)
    saved_embedding_cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6))
    cache_layer: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
