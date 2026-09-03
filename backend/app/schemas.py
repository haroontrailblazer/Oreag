import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import settings

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
    # Answer policy. Bounds mirror the CHECK constraints in migration 0032 so
    # the API and the database reject the same values.
    min_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    min_strong: int | None = Field(default=None, ge=0, le=20)
    # "" clears back to NULL, exactly as description does - null means "leave
    # it alone", so it cannot double as the clear signal.
    answer_language: str | None = Field(default=None, max_length=60)
    answer_disclaimer: str | None = Field(default=None, max_length=500)
    # Document versions (0034). Toggling this changes nothing already indexed,
    # so - like the four answer-policy fields above - it must NOT bump
    # content_version. Turning it OFF only stops new uploads being held for
    # review; already-superseded versions stay superseded, because every
    # requeue guard keys on files.in_force_to and never on this flag.
    version_tracking: bool | None = None
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
    # Width the vectors were originally computed at. Greater than
    # embedding_dimensions means this project is shrunk and the wider originals
    # are archived - so the UI can tell a FREE grow (back up to this width,
    # restored from the archive) from a PAID one, instead of warning about a
    # re-index that will not happen.
    embedding_native_dimensions: int | None = None
    llm_provider: str
    llm_model: str
    top_k: int
    # Answer policy (0032). Always concrete - there is no "inherit" state.
    #
    # The validator below exists for the window in which new code runs against
    # a database that has not had 0032 applied (a rolling deploy), where the
    # attribute is absent or None on a loaded row. It reports the value the
    # query path would actually use in that window, so the settings screen
    # never shows a blank where a policy is in force.
    min_similarity: float = 0.2
    min_strong: int = 1
    answer_language: str | None = None
    answer_disclaimer: str | None = None

    @field_validator("min_similarity", mode="before")
    @classmethod
    def _default_min_similarity(cls, v):
        return settings.agentic_min_similarity if v is None else v

    @field_validator("min_strong", mode="before")
    @classmethod
    def _default_min_strong(cls, v):
        return settings.agentic_min_strong if v is None else v

    @field_validator("version_tracking", mode="before")
    @classmethod
    def _default_version_tracking(cls, v):
        # Same rolling-deploy guard as the two above: on a database without
        # 0034 the attribute loads as None, and a project that cannot be
        # serialised takes the whole dashboard down rather than one toggle.
        return False if v is None else v
    status: str
    suspended: bool = False
    # Defaulted so a rolling deploy against a database without 0034 reports
    # "off" rather than 500ing the whole settings screen.
    version_tracking: bool = False
    # Whether the DEPLOYMENT allows extraction at all. Both switches must be on
    # for anything to happen, so a project toggle that saves cheerfully while
    # the fleet flag is off is a setting that silently does nothing - the user
    # uploads revisions for months and never sees a review. Reported so the UI
    # can say so instead of lying.
    version_extraction_available: bool = False
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
    conversion_note: str | None = None
    # Document versions (migration 0034). Defaulted, so every route returning a
    # FileOut carries them with no per-route work - and so a response built
    # before the migration lands still validates. `in_force_to` non-null means
    # superseded: stored and downloadable, but holding no chunks.
    document_id: uuid.UUID | None = None
    version_label: str | None = None
    in_force_from: date | None = None
    in_force_to: date | None = None
    legal_status: str | None = None
    # Provenance (0035). content_sha256 lets a client tell "I already have this
    # file" without downloading it; extracted_title is what the shortlist
    # actually matches on; instrument_role says whether this edition is even
    # ALLOWED to supersede something.
    content_sha256: str | None = None
    extracted_title: str | None = None
    instrument_role: str | None = None
    # 0036. supersedes_file_id lets a client walk the lineage in real order
    # instead of sorting on a legal date that may be null.
    supersedes_file_id: uuid.UUID | None = None
    markdown_sha256: str | None = None
    created_at: datetime
    indexed_at: datetime | None


LEGAL_STATUSES = ("in_force", "amended", "repealed", "draft", "unknown")

# What KIND of document an edition is (migration 0035). The last four refer to
# another document rather than replacing it, and are refused as supersessions -
# see ingestion.NON_SUPERSEDING_ROLES. Mirrors the CHECK constraint in 0035.
INSTRUMENT_ROLES = (
    "principal",
    "consolidated",
    "amending",
    "correction",
    "translation",
    "supplement",
    "unknown",
)


class FileVersionRequest(BaseModel):
    """One version decision: confirm, reject, retire by hand, or reinstate.

    Every field is REQUIRED so that `document_id: null` is unambiguous - it
    means "this is a separate document", not "I forgot to send it". That
    distinction is the whole reject path, so it cannot be left to a default.

    `in_force_to` is deliberately absent: it is derived, never supplied. The
    endpoint writes the successor's `in_force_from` onto the predecessor, so
    the two rows cannot disagree.
    """

    # NULL = this file is its own document. Non-null must name a lineage that
    # already exists in the project.
    document_id: uuid.UUID | None
    # The currently-in-force file this replaces. NULL = replace nothing.
    supersede_file_id: uuid.UUID | None
    # Required-but-nullable like the rest: the endpoint WRITES every field it is
    # given, so an omitted `version_label` would silently erase a label the user
    # never touched - and would then also defeat the idempotency short-circuit,
    # turning a harmless retry into a destructive edit.
    version_label: str | None = Field(max_length=200)
    # Pydantic's `date` is strict ISO-8601, so 2019-02-30 is a 422 rather than
    # a silently wrong row. Required by the endpoint whenever a predecessor is
    # named, because in_force_to is the only thing keeping a superseded version
    # out of the index and it must never be invented.
    in_force_from: date | None
    legal_status: Literal[LEGAL_STATUSES] | None  # type: ignore[valid-type]
    # The reviewer's judgement of what kind of document this is. Required like
    # every other field because the endpoint writes it unconditionally, and
    # load-bearing: a role in NON_SUPERSEDING_ROLES cannot name a predecessor.
    instrument_role: Literal[INSTRUMENT_ROLES] | None  # type: ignore[valid-type]


class DocumentEventOut(BaseModel):
    """One recorded decision about a document edition (migration 0035).

    Read-only and append-only at the database level; there is no create or
    update shape because events are written by the operations they describe,
    never by a client.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    file_id: uuid.UUID | None
    document_id: uuid.UUID | None
    event: str
    actor_id: uuid.UUID | None
    occurred_at: datetime
    detail: dict


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
    provider: Literal[
        "openai",
        "gemini",
        "anthropic",
        "azure",
        "sarvam",
        "xai",
        "groq",
        "mistral",
        "deepseek",
        "cohere",
        "together",
        "fireworks",
        "openrouter",
        "perplexity",
        "voyage",
        "jina",
    ]
    key: str = Field(min_length=8, max_length=500)
    label: str = Field(default="default", min_length=1, max_length=100)
    # Azure OpenAI only: the resource endpoint, stored inside the credential.
    endpoint: str | None = Field(default=None, max_length=300)


class ProviderKeyOut(BaseModel):
    """Masked view - the raw/encrypted key is never serialized."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    label: str
    last4: str
    # When this key's reachable-model list was last read from the provider, and
    # how many it saw. None means never read - the pickers then show the full
    # static catalog. The model NAMES are deliberately not serialised: the UI
    # only needs to say whether the list is known and how fresh it is, and the
    # merged catalog already arrives via /api/models.
    # NB "models_available", not "model_count" - a `model_` prefix collides with
    # Pydantic's protected namespace.
    models_fetched_at: datetime | None = None
    models_available: int | None = None
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
    # True when the answer actually cited this block as [n]. The list is
    # everything the loop retrieved, which is deliberately wider than what the
    # answer used - without this a caller cannot tell "supported this claim"
    # from "was in the context and ignored".
    cited: bool = False


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
    # Which cache served this answer: "l1" (exact match), "l2" (semantically
    # similar question), or null when it was computed fresh. cache_similarity
    # is the L2 cosine similarity that cleared the threshold.
    cache_layer: Literal["l1", "l2"] | None = None
    cache_similarity: float | None = None
    # Mean similarity of the sources behind this answer - the same number
    # already persisted as query_logs.retrieval_similarity and charted on the
    # Usage page. NULL, never 0, when nothing was retrieved (a clarification):
    # "not measured" is a different fact from "matched at 0.0".
    retrieval_similarity: float | None = None


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


class MemoryUpdate(BaseModel):
    """Owner-side edits to an existing memory.

    Only `pinned` for now, deliberately. Content is NOT editable here: changing
    it would leave the stored vector describing the old text, so an edit has to
    go through re-embedding rather than a field assignment.
    """

    pinned: bool | None = None


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


# --- Account usage report -------------------------------------------------
#
# GET /api/account/usage. Contract note that applies to every model below:
# a token/cost field is None when nothing was MEASURED, which is a different
# fact from a measured 0. Only request counts are genuinely 0 when empty.


class UsageTotals(BaseModel):
    requests: int
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    saved_prompt_tokens: int | None
    saved_completion_tokens: int | None
    # Priced per row at write time from the model that produced the cached
    # answer - a measurement, not a rate blended across the window.
    saved_cost_usd: float | None
    # The EMBEDDER's side: retrieval, ingestion, memory writes, cache probes.
    # Kept separate from prompt_tokens because embedding tokens are 10-100x
    # cheaper, so one combined number would be wrong for both.
    embedding_tokens: int | None
    embedding_cost_usd: float | None
    # Embedding avoided by a Matryoshka grow-back: restoring vectors from the
    # archive instead of re-embedding. Replayed from what the files originally
    # cost, so it is a measurement - NULL for files ingested before that was
    # recorded, never a fabricated figure.
    saved_embedding_tokens: int | None
    saved_embedding_cost_usd: float | None


class UsageByModel(BaseModel):
    model: str
    requests: int
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    # True for rows aggregated from embedding_model rather than model, so the
    # UI can label an embedder as such instead of implying it answered
    # questions. Chat and embedding models appear in one list because "what did
    # this account spend, by model" is one question.
    kind: str = "llm"


class UsageByApiKey(BaseModel):
    api_key_id: str
    key_prefix: str
    revoked: bool
    requests: int
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None


class UsageCacheSplit(BaseModel):
    l1: int
    l2: int
    miss: int
    hit_rate: float  # (l1 + l2) / (l1 + l2 + miss); 0.0 when no queries


class UsageByProject(BaseModel):
    project_id: str
    name: str
    requests: int
    cost_usd: float | None
    cache: UsageCacheSplit
    avg_retrieval_similarity: float | None
    avg_cache_similarity: float | None
    saved_prompt_tokens: int | None
    saved_completion_tokens: int | None


class UsageDaily(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    requests: int
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    saved_prompt_tokens: int | None
    embedding_tokens: int | None
    embedding_cost_usd: float | None
    # Latency percentiles over the day's queries, from query_logs. p50 is the
    # typical experience; p95 is the one users complain about. Both, never a
    # mean - an average latency hides exactly the tail it is asked about.
    p50_latency_ms: int | None
    p95_latency_ms: int | None
    p99_latency_ms: int | None
    # Cache split for the day, so the hit rate can be read as a trend rather
    # than one lifetime number.
    cache_l1: int
    cache_l2: int
    cache_miss: int
    # Mean similarity of the chunks retrieval returned that day - the closest
    # thing to an answer-quality trend that costs nothing to collect.
    avg_retrieval_similarity: float | None


class UsageByEndpoint(BaseModel):
    """One row per API surface: /query vs ingest vs memory vs the judge.

    `usage_events.endpoint` has been recorded since metering began and was
    never once shown, so "what is this account actually doing" had no answer -
    a spike in spend could not be attributed to a surface.
    """

    endpoint: str
    requests: int
    prompt_tokens: int | None
    completion_tokens: int | None
    embedding_tokens: int | None
    cost_usd: float | None
    p50_latency_ms: int | None


class UsageCaveats(BaseModel):
    """What the report could NOT see - shown, not hidden, on purpose."""

    unmeasured_requests: int  # rows whose provider reported no token usage
    unmeasured_models: list[str]  # distinct models on those rows
    # Kept in the contract, now normally False: embedding, image captioning and
    # audio transcription are all metered. It stays True only where a vendor
    # reports no usage for those calls (Whisper and Sarvam STT return none), so
    # the page can still say what it could not see rather than implying free.
    vision_and_audio_excluded: bool


class UsageReport(BaseModel):
    window_days: int
    totals: UsageTotals
    by_model: list[UsageByModel]
    by_endpoint: list[UsageByEndpoint]
    by_api_key: list[UsageByApiKey]
    by_project: list[UsageByProject]
    daily: list[UsageDaily]
    caveats: UsageCaveats
