import hashlib
import uuid

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import crypto
from app.auth.api_keys import KEY_PREFIX, generate_api_key, hash_key
from app.main import app
from app.models import Memory, Project, ProviderKey
from app.providers import resolver
from app.providers.gemini_provider import l2_normalize
from app.providers.registry import (
    CATALOG,
    embedding_change_plan,
    embedding_dimension_options,
    embedding_dimensions,
    get_embedder,
    get_llm,
    resolve_embedding_dimensions,
    validate_llm,
)
from app.schemas import ProjectCreate, ProjectOut, ProviderKeyOut
from app.services.conversion import is_supported_upload, markdown_path_for
from app.services.generation import build_user_prompt
from app.services.ingestion import parse_pdf
from app.services.memory_graph import _sections


class TestMemoryModel:
    def test_table_and_columns(self):
        assert Memory.__tablename__ == "memories"
        cols = set(Memory.__table__.columns.keys())
        assert {
            "id",
            "project_id",
            "content",
            "tags",
            "pinned",
            "source",
            "embedding",
            "created_at",
            "updated_at",
        } <= cols


class TestMemorySchemas:
    def test_content_bounds(self):
        from app.schemas import MemoryCreate

        MemoryCreate(content="x")
        with pytest.raises(ValueError):
            MemoryCreate(content="")
        with pytest.raises(ValueError):
            MemoryCreate(content="x" * 8001)

    def test_defaults(self):
        from app.schemas import MemoryCreate

        m = MemoryCreate(content="hi")
        assert m.tags == [] and m.pinned is False and m.source == "mcp"


class TestMemoryService:
    def _project(self):
        return Project(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
        )

    class _FakeDB:
        def __init__(self):
            self.added = []

        def add(self, obj):
            self.added.append(obj)

        def commit(self):
            pass

        def refresh(self, obj):
            pass

    def test_save_embeds_and_stores(self, monkeypatch):
        from app.schemas import MemoryCreate
        from app.services import memory

        class StubEmbedder:
            def embed_texts(self, texts):
                return [[0.1, 0.2, 0.3]]

        monkeypatch.setattr(memory.resolver, "resolve_embedding_key", lambda db, p: "k")
        monkeypatch.setattr(memory, "get_embedder", lambda *a, **k: StubEmbedder())

        db = self._FakeDB()
        m = memory.save_memory(db, self._project(), MemoryCreate(content="hello"))
        assert m.content == "hello"
        assert m.embedding == [0.1, 0.2, 0.3]
        assert m in db.added

    def test_save_without_key_stores_null_embedding(self, monkeypatch):
        from app.schemas import MemoryCreate
        from app.services import memory

        monkeypatch.setattr(memory.resolver, "resolve_embedding_key", lambda db, p: None)
        db = self._FakeDB()
        m = memory.save_memory(db, self._project(), MemoryCreate(content="hi"))
        assert m.embedding is None


class TestRegistry:
    def test_known_embedding_dimensions(self):
        assert embedding_dimensions("openai", "text-embedding-3-small") == 1536
        assert embedding_dimensions("openai", "text-embedding-3-large") == 3072
        assert embedding_dimensions("ollama", "nomic-embed-text") == 768
        assert embedding_dimensions("sentence_transformers", "all-MiniLM-L6-v2") == 384

    def test_unknown_embedding_model_rejected(self):
        with pytest.raises(ValueError):
            embedding_dimensions("openai", "made-up-model")
        with pytest.raises(ValueError):
            embedding_dimensions("made-up-provider", "text-embedding-3-small")

    def test_validate_llm(self):
        validate_llm("openai", "gpt-4o-mini")
        validate_llm("ollama", "llama3.1")
        with pytest.raises(ValueError):
            validate_llm("openai", "not-a-model")

    def test_get_embedder_unknown_provider(self):
        with pytest.raises(ValueError):
            get_embedder("nope", "whatever")

    def test_catalog_consistent(self):
        # every catalog entry must round-trip through the validators
        for provider, entries in CATALOG["embedding"].items():
            for entry in entries:
                assert embedding_dimensions(provider, entry["model"]) > 0
        for provider, models in CATALOG["llm"].items():
            for model in models:
                validate_llm(provider, model)

    def test_byok_providers_present(self):
        assert "gemini" in CATALOG["embedding"]
        assert "gemini" in CATALOG["llm"]
        assert "anthropic" in CATALOG["llm"]
        # Anthropic is chat-only - no embedding model
        assert "anthropic" not in CATALOG["embedding"]

    def test_anthropic_has_no_embedder(self):
        with pytest.raises(ValueError):
            get_embedder("anthropic", "claude-haiku-4-5-20251001")

    def test_gemini_chat_models_are_current(self):
        # Google retired gemini-1.5-*, gemini-2.0-flash, and even
        # gemini-3-pro-preview (previews die fast); offering dead ids made every
        # Gemini chat answer fail while embeddings kept working. Offer verified
        # stable models plus Google's rolling -latest aliases (never previews).
        assert CATALOG["llm"]["gemini"] == [
            "gemini-3.5-flash",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-flash-latest",
            "gemini-pro-latest",
        ]
        with pytest.raises(ValueError):
            validate_llm("gemini", "gemini-2.0-flash")
        with pytest.raises(ValueError):
            validate_llm("gemini", "gemini-1.5-pro")
        with pytest.raises(ValueError):
            validate_llm("gemini", "gemini-3-pro-preview")

    def test_anthropic_chat_models_are_current(self):
        # Wide range: current Sonnet 5 + most-capable Opus 4.8, plus the still-
        # active previous generation. The dated haiku id stays for projects that
        # already store it (removing it would 500 their queries at validate_llm).
        assert CATALOG["llm"]["anthropic"] == [
            "claude-sonnet-5",
            "claude-opus-4-8",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        ]

    def test_openai_chat_models_are_current(self):
        # Current GPT-5.x lineup (cheap default → flagship) plus the legacy 4o
        # pair, which OpenAI still serves and existing projects have stored.
        assert CATALOG["llm"]["openai"] == [
            "gpt-5.4-mini",
            "gpt-5.4",
            "gpt-5.5",
            "gpt-4o-mini",
            "gpt-4o",
        ]

    def test_ollama_chat_models_are_current(self):
        # Local tags never 404, but the list should headline current models.
        # llama3.1 stays (top-pulled, only current-quality 8B Llama); qwen2.5 is
        # dropped for its direct successor qwen3.
        assert CATALOG["llm"]["ollama"] == [
            "llama3.3",
            "llama3.1",
            "qwen3",
            "gemma4",
            "deepseek-r1",
            "mistral",
        ]

    def test_sarvam_chat_models_are_current(self):
        # Verified against docs.sarvam.ai: these are the two current chat ids.
        assert CATALOG["llm"]["sarvam"] == ["sarvam-30b", "sarvam-105b"]


class TestMatryoshkaDimensions:
    def test_options_default_to_single_size(self):
        assert embedding_dimension_options("ollama", "nomic-embed-text") == [768]
        assert embedding_dimension_options("gemini", "text-embedding-004") == [768]

    def test_mrl_models_offer_prefix_sizes(self):
        assert embedding_dimension_options("openai", "text-embedding-3-small") == [
            512,
            1536,
        ]
        assert embedding_dimension_options("openai", "text-embedding-3-large") == [
            256,
            1024,
            3072,
        ]
        assert embedding_dimension_options("gemini", "gemini-embedding-001") == [
            768,
            1536,
            3072,
        ]

    def test_resolve_defaults_and_validates(self):
        assert (
            resolve_embedding_dimensions("openai", "text-embedding-3-small", None)
            == 1536
        )
        assert (
            resolve_embedding_dimensions("openai", "text-embedding-3-large", 1024)
            == 1024
        )
        with pytest.raises(ValueError):
            resolve_embedding_dimensions("openai", "text-embedding-3-small", 999)
        with pytest.raises(ValueError):
            # non-MRL models accept only their native size
            resolve_embedding_dimensions("ollama", "nomic-embed-text", 512)

    def test_change_plan_keep_when_nothing_changed(self):
        assert (
            embedding_change_plan(
                "openai", "text-embedding-3-small", 1536,
                "openai", "text-embedding-3-small", 1536,
            )
            == "keep"
        )

    def test_change_plan_truncate_for_same_model_shrink(self):
        assert (
            embedding_change_plan(
                "openai", "text-embedding-3-large", 3072,
                "openai", "text-embedding-3-large", 1024,
            )
            == "truncate"
        )
        assert (
            embedding_change_plan(
                "gemini", "gemini-embedding-001", 3072,
                "gemini", "gemini-embedding-001", 768,
            )
            == "truncate"
        )

    def test_change_plan_grow_requires_reembed(self):
        # the truncated tail was never stored - growing needs a full re-embed
        assert (
            embedding_change_plan(
                "openai", "text-embedding-3-large", 1024,
                "openai", "text-embedding-3-large", 3072,
            )
            == "reembed"
        )

    def test_change_plan_model_switch_requires_reembed(self):
        assert (
            embedding_change_plan(
                "openai", "text-embedding-3-small", 1536,
                "gemini", "gemini-embedding-001", 3072,
            )
            == "reembed"
        )
        # matching dimension COUNT is not a matching vector space
        assert (
            embedding_change_plan(
                "openai", "text-embedding-3-small", 1536,
                "gemini", "gemini-embedding-001", 1536,
            )
            == "reembed"
        )

    def test_l2_normalize(self):
        assert l2_normalize([3.0, 4.0]) == pytest.approx([0.6, 0.8])
        assert l2_normalize([0.0, 0.0]) == [0.0, 0.0]
        length = sum(v * v for v in l2_normalize([0.2, -1.7, 5.0])) ** 0.5
        assert length == pytest.approx(1.0)


class TestPlanEmbeddingChange:
    """The files-router helper that turns a request into a migration plan."""

    def _project(self) -> Project:
        return Project(
            embedding_provider="openai",
            embedding_model="text-embedding-3-large",
            embedding_dimensions=3072,
        )

    def test_same_model_shrink_truncates(self):
        from app.routers.files import _plan_embedding_change

        provider, model, dims, plan = _plan_embedding_change(
            self._project(), None, None, 1024
        )
        assert (provider, model, dims, plan) == (
            "openai",
            "text-embedding-3-large",
            1024,
            "truncate",
        )

    def test_model_switch_defaults_to_new_models_native_size(self):
        from app.routers.files import _plan_embedding_change

        provider, model, dims, plan = _plan_embedding_change(
            self._project(), "gemini", "gemini-embedding-001", None
        )
        assert (dims, plan) == (3072, "reembed")

    def test_no_change_keeps(self):
        from app.routers.files import _plan_embedding_change

        *_, plan = _plan_embedding_change(self._project(), None, None, None)
        assert plan == "keep"

    def test_invalid_dimensions_rejected(self):
        from fastapi import HTTPException

        from app.routers.files import _plan_embedding_change

        with pytest.raises(HTTPException):
            _plan_embedding_change(self._project(), None, None, 123)


class TestEmbedBatchSizes:
    """Batch size is per provider: hosted APIs take big batches, local Ollama
    prefers small ones. Ingestion batches (and commits) by the embedder's own
    declared size, so each batch is exactly one embedding request."""

    def test_each_provider_declares_its_size(self):
        # class attributes - no instantiation, so no keys/SDKs/model downloads
        from app.providers.gemini_provider import GeminiEmbedder
        from app.providers.ollama_provider import OllamaEmbedder
        from app.providers.openai_provider import OpenAIEmbedder
        from app.providers.st_provider import SentenceTransformersEmbedder

        assert OpenAIEmbedder.batch_size == 100
        assert GeminiEmbedder.batch_size == 100
        assert OllamaEmbedder.batch_size == 32
        assert SentenceTransformersEmbedder.batch_size == 64

    def test_ingestion_uses_the_embedders_size(self):
        from app.services.ingestion import embed_batch_size

        class _Declared:
            batch_size = 25

        assert embed_batch_size(_Declared()) == 25

    def test_ingestion_falls_back_conservatively(self):
        from app.services.ingestion import embed_batch_size

        class _Silent:
            pass

        class _Broken:
            batch_size = 0

        assert embed_batch_size(_Silent()) == 64
        assert embed_batch_size(_Broken()) == 64


class TestHybridRetrieval:
    """Semantic + lexical rankings fused with RRF; degrades to semantic-only
    when the full-text column is missing. Sits below both answer caches, so
    nothing here can affect L1/L2 behavior."""

    def _rows(self, *ids, sim=0.5):
        return [
            {
                "id": i,
                "content": f"chunk {i}",
                "page_number": None,
                "chunk_index": i,
                "filename": "f.pdf",
                "similarity": sim,
            }
            for i in ids
        ]

    def test_found_by_both_engines_ranks_first(self):
        from app.services.retrieval import rrf_merge

        semantic = self._rows(1, 2, 3)
        lexical = self._rows(3, 4)  # chunk 3 also matched by keywords
        out = rrf_merge(semantic, lexical, top_k=4)
        assert out[0]["chunk_index"] == 3
        assert all("id" not in row for row in out)  # SourceChunk-safe payloads

    def test_keyword_only_hit_is_included(self):
        from app.services.retrieval import rrf_merge

        semantic = self._rows(1, 2)
        lexical = self._rows(9)  # e.g. an exact error code vectors missed
        out = rrf_merge(semantic, lexical, top_k=5)
        assert any(row["chunk_index"] == 9 for row in out)

    def test_caps_at_top_k_and_preserves_order_and_similarity(self):
        from app.services.retrieval import rrf_merge

        out = rrf_merge(self._rows(*range(1, 8), sim=0.42), [], top_k=5)
        assert len(out) == 5
        assert [row["chunk_index"] for row in out] == [1, 2, 3, 4, 5]
        assert out[0]["similarity"] == 0.42  # cosine survives for thresholds/UI

    def test_lexical_failure_degrades_to_semantic_only(self, monkeypatch):
        from app.services import retrieval

        class _Embedder:
            def embed_query(self, q):
                return [0.1]

        monkeypatch.setattr(
            retrieval.resolver, "resolve_embedding_key", lambda db, p: "k"
        )
        monkeypatch.setattr(retrieval, "get_embedder", lambda *a, **k: _Embedder())

        sem_rows = self._rows(1, 2)

        class _Result:
            def mappings(self):
                return sem_rows

        class _DB:
            def __init__(self):
                self.calls = 0
                self.rollbacks = 0

            def execute(self, stmt, params=None):
                self.calls += 1
                if self.calls == 1:
                    return _Result()
                raise RuntimeError("column content_tsv does not exist")

            def rollback(self):
                self.rollbacks += 1

        db = _DB()
        project = Project(
            id=uuid.uuid4(),
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
        )
        out = retrieval.retrieve(db, project, "what is E-4417", 5)
        assert [row["chunk_index"] for row in out] == [1, 2]
        assert db.rollbacks == 1  # aborted transaction cleaned up


class TestVectorMigration:
    """Memory vectors must follow chunk vectors through every embedding change:
    truncated in place on a same-model MRL shrink, cleared and re-embedded with
    the new model on a model switch."""

    class _RecordingDB:
        def __init__(self, fail: bool = False):
            self.fail = fail
            self.statements: list[str] = []
            self.rollbacks = 0

        def execute(self, statement, params=None):
            if self.fail:
                raise RuntimeError("no subvector on this postgres")
            self.statements.append(str(statement))

        def rollback(self):
            self.rollbacks += 1

    def test_truncate_updates_chunks_and_memories(self):
        from app.routers.files import _truncate_vectors_in_place

        db = self._RecordingDB()
        assert _truncate_vectors_in_place(db, Project(id=uuid.uuid4()), 1024) is True
        joined = "\n".join(db.statements).lower()
        assert "update chunks" in joined
        assert "update memories" in joined
        # both tables go through the same MRL prefix + re-normalize
        assert joined.count("subvector") == 2
        assert joined.count("l2_normalize") == 2

    def test_truncate_falls_back_cleanly_on_db_error(self):
        from app.routers.files import _truncate_vectors_in_place

        db = self._RecordingDB(fail=True)
        assert _truncate_vectors_in_place(db, Project(id=uuid.uuid4()), 512) is False
        assert db.rollbacks == 1  # transaction cleaned up for the full-reembed path

    def test_reembed_memories_uses_the_projects_current_model(self, monkeypatch):
        from app.services import memory as memory_service

        project = Project(
            id=uuid.uuid4(),
            embedding_provider="openai",
            embedding_model="text-embedding-3-large",
            embedding_dimensions=1024,
        )
        memories = [
            Memory(project_id=project.id, content="alpha"),
            Memory(project_id=project.id, content="beta"),
        ]

        class _FakeScalars:
            def all(self):
                return memories

        class _FakeSession:
            def __init__(self):
                self.commits = 0
                self.closed = False

            def get(self, model, key):
                return project if model is Project else None

            def scalars(self, stmt):
                return _FakeScalars()

            def commit(self):
                self.commits += 1

            def rollback(self):
                pass

            def close(self):
                self.closed = True

        session = _FakeSession()
        monkeypatch.setattr(memory_service, "SessionLocal", lambda: session)
        embedded_with: list[tuple] = []

        def fake_embed(db, proj, content):
            embedded_with.append(
                (proj.embedding_model, proj.embedding_dimensions, content)
            )
            return [0.1, 0.2]

        monkeypatch.setattr(memory_service, "_embed", fake_embed)

        memory_service.reembed_project_memories(project.id)

        assert [m.embedding for m in memories] == [[0.1, 0.2], [0.1, 0.2]]
        assert embedded_with == [
            ("text-embedding-3-large", 1024, "alpha"),
            ("text-embedding-3-large", 1024, "beta"),
        ]
        assert session.commits == 1
        assert session.closed

    def test_reembed_survives_missing_project(self, monkeypatch):
        from app.services import memory as memory_service

        class _FakeSession:
            def __init__(self):
                self.closed = False

            def get(self, model, key):
                return None

            def rollback(self):
                pass

            def close(self):
                self.closed = True

        session = _FakeSession()
        monkeypatch.setattr(memory_service, "SessionLocal", lambda: session)
        memory_service.reembed_project_memories(uuid.uuid4())  # must not raise
        assert session.closed


class TestOpenAICompatProviders:
    """xAI, Groq, Mistral, DeepSeek, Cohere and LM Studio all ride the shared
    OpenAI-compatible provider - one implementation, per-vendor base URLs."""

    def test_every_compat_vendor_has_a_base_url_and_catalog_entry(self):
        from app.providers.registry import COMPAT_BASE_URLS

        for provider in ("xai", "groq", "mistral", "deepseek", "cohere"):
            assert COMPAT_BASE_URLS[provider].startswith("https://")
            assert CATALOG["llm"].get(provider) or CATALOG["embedding"].get(provider)

    def test_compat_llm_requires_a_key(self):
        from app.providers.base import ProviderUnavailableError

        with pytest.raises(ProviderUnavailableError):
            get_llm("groq", "llama-3.3-70b-versatile", api_key=None)

    def test_compat_llm_builds_with_a_key(self):
        llm = get_llm("xai", "grok-4", api_key="test-key")
        assert llm.model == "grok-4"
        assert "api.x.ai" in str(llm.client.base_url)

    def test_compat_embedder_wires_dimensions_and_batching(self):
        emb = get_embedder("cohere", "embed-v4.0", api_key="k", dimensions=512)
        assert emb.dimensions == 512
        assert emb._send_dimensions is True  # embed-v4.0 is Matryoshka-capable
        assert emb.batch_size == 64

        emb = get_embedder("mistral", "mistral-embed", api_key="k")
        assert emb.dimensions == 1024
        assert emb._send_dimensions is False  # single-size model: no dims param

    def test_lmstudio_is_keyless_and_local(self):
        from app.providers.resolver import requires_key

        assert not requires_key("lmstudio")
        llm = get_llm("lmstudio", "openai/gpt-oss-20b", api_key=None)
        assert "localhost:1234" in str(llm.client.base_url)
        emb = get_embedder(
            "lmstudio", "text-embedding-nomic-embed-text-v1.5", api_key=None
        )
        assert emb.batch_size == 32  # local inference - small batches

    def test_new_providers_accepted_for_account_keys(self):
        from app.schemas import ProviderKeyCreate

        for provider in (
            "xai", "groq", "mistral", "deepseek", "cohere",
            "together", "fireworks", "openrouter", "perplexity", "voyage", "jina",
            "azure",
        ):
            assert ProviderKeyCreate(provider=provider, key="x" * 20).provider == provider
        with pytest.raises(Exception):
            ProviderKeyCreate(provider="lmstudio", key="x" * 20)  # keyless - no key rows


class TestAzureOpenAI:
    """Azure's endpoint travels inside the encrypted credential ("endpoint|key")
    so key resolution stays a plain string end to end."""

    def test_credential_round_trip(self):
        from app.providers.openai_compat import (
            azure_base_url,
            join_azure_credential,
            split_azure_credential,
        )

        cred = join_azure_credential("https://res.openai.azure.com/", "sk-abc")
        endpoint, key = split_azure_credential(cred)
        assert endpoint == "https://res.openai.azure.com"
        assert key == "sk-abc"
        assert azure_base_url(endpoint) == "https://res.openai.azure.com/openai/v1"

    def test_bare_key_without_endpoint_raises(self):
        from app.providers.base import ProviderUnavailableError
        from app.providers.openai_compat import split_azure_credential

        with pytest.raises(ProviderUnavailableError):
            split_azure_credential("just-a-key")
        with pytest.raises(ProviderUnavailableError):
            split_azure_credential(None)

    def test_llm_and_embedder_route_to_the_resource(self):
        cred = "https://res.openai.azure.com|k"
        llm = get_llm("azure", "gpt-4o", api_key=cred)
        assert "res.openai.azure.com" in str(llm.client.base_url)
        assert "/openai/v1" in str(llm.client.base_url)

        emb = get_embedder(
            "azure", "text-embedding-3-small", api_key=cred, dimensions=512
        )
        assert emb.dimensions == 512
        assert emb._send_dimensions is True  # MRL deployment: dims param sent


class TestGeminiProviderCompat:
    def test_vertex_express_keys_are_detected(self):
        # AQ.-prefixed Vertex express keys must route to the Vertex backend;
        # sending them to the Gemini Developer API 401s
        # (ACCESS_TOKEN_TYPE_UNSUPPORTED). AIza keys stay on the Developer API.
        from app.providers.gemini_provider import is_vertex_express_key

        assert is_vertex_express_key("AQ.Ab8example")
        assert not is_vertex_express_key("AIzaSyExample")
        assert not is_vertex_express_key("")


class TestAnthropicProviderCompat:
    """Claude Sonnet 5 / Opus 4.8 removed `temperature` (400 if sent), and the
    old max_tokens=1024 truncated the agentic loop's long exam-style answers."""

    def _fake_client(self, calls):
        class _Messages:
            def create(self, **kwargs):
                calls.append(kwargs)

                class _Resp:
                    content = [type("B", (), {"text": "ok"})()]

                return _Resp()

        class _Client:
            messages = _Messages()

        return _Client()

    def test_generate_omits_temperature_and_allows_long_answers(self, monkeypatch):
        from app.providers import anthropic_provider

        calls: list[dict] = []
        monkeypatch.setattr(
            anthropic_provider, "_client", lambda key: self._fake_client(calls)
        )
        llm = anthropic_provider.AnthropicLLM("claude-sonnet-5", "k")
        assert llm.generate("sys", "user") == "ok"
        assert "temperature" not in calls[0]
        assert calls[0]["max_tokens"] >= 8192


class TestOpenAIProviderCompat:
    """GPT-5.x reasoning models reject `temperature` unless reasoning_effort is
    'none' (gpt-5.5 defaults to 'medium'); gpt-4o-era models keep temperature=0."""

    def _fake_client(self, calls):
        class _Completions:
            def create(self, **kwargs):
                calls.append(kwargs)
                msg = type("M", (), {"content": "ok"})()
                choice = type("C", (), {"message": msg})()
                return type("R", (), {"choices": [choice]})()

        class _Chat:
            completions = _Completions()

        class _Client:
            chat = _Chat()

        return _Client()

    def test_gpt5_family_uses_no_reasoning_and_no_temperature(self, monkeypatch):
        from app.providers import openai_provider

        calls: list[dict] = []
        monkeypatch.setattr(
            openai_provider, "_client", lambda key: self._fake_client(calls)
        )
        llm = openai_provider.OpenAILLM("gpt-5.5", "k")
        assert llm.generate("sys", "user") == "ok"
        assert calls[0]["reasoning_effort"] == "none"
        assert "temperature" not in calls[0]

    def test_legacy_models_keep_temperature_zero(self, monkeypatch):
        from app.providers import openai_provider

        calls: list[dict] = []
        monkeypatch.setattr(
            openai_provider, "_client", lambda key: self._fake_client(calls)
        )
        llm = openai_provider.OpenAILLM("gpt-4o-mini", "k")
        assert llm.generate("sys", "user") == "ok"
        assert calls[0]["temperature"] == 0
        assert "reasoning_effort" not in calls[0]


class TestCrypto:
    def test_encrypt_roundtrip(self):
        assert crypto.decrypt(crypto.encrypt("hello-secret")) == "hello-secret"

    def test_last4(self):
        assert crypto.last4("sk-proj-abcd1234") == "1234"

    def test_apply_override(self):
        assert crypto.apply_override(None) is None  # leave unchanged
        assert crypto.apply_override("") == (None, None)  # clear
        enc, masked = crypto.apply_override("sk-test-wxyz5678")
        assert masked == "5678"
        assert crypto.decrypt(enc) == "sk-test-wxyz5678"


class TestResolver:
    def test_requires_key(self):
        assert resolver.requires_key("openai")
        assert resolver.requires_key("gemini")
        assert resolver.requires_key("anthropic")
        assert not resolver.requires_key("ollama")
        assert not resolver.requires_key("sentence_transformers")

    def test_project_override_takes_precedence(self):
        project = Project(
            owner_id=uuid.uuid4(),
            llm_provider="openai",
            llm_key_encrypted=crypto.encrypt("project-key"),
        )
        # db is never touched when a project override is present
        assert resolver.resolve_llm_key(None, project) == "project-key"

    def test_keyless_provider_returns_none(self):
        project = Project(owner_id=uuid.uuid4(), embedding_provider="ollama")
        assert resolver.resolve_embedding_key(None, project) is None

    def test_falls_back_to_account_key(self):
        class FakeDB:
            def __init__(self, row):
                self.row = row

            def scalar(self, *args, **kwargs):
                return self.row

        account = ProviderKey(
            owner_id=uuid.uuid4(),
            provider="anthropic",
            encrypted_key=crypto.encrypt("account-key"),
            last4="-key",
        )
        project = Project(owner_id=account.owner_id, llm_provider="anthropic")
        assert resolver.resolve_llm_key(FakeDB(account), project) == "account-key"

    def test_no_key_anywhere_returns_none(self):
        class FakeDB:
            def scalar(self, *args, **kwargs):
                return None

        project = Project(owner_id=uuid.uuid4(), llm_provider="openai")
        assert resolver.resolve_llm_key(FakeDB(), project) is None


class TestApiKeys:
    def test_generate_format(self):
        full_key, key_hash, prefix = generate_api_key()
        assert full_key.startswith(KEY_PREFIX)
        assert len(full_key) > len(KEY_PREFIX) + 30
        assert prefix == full_key[:16]
        assert key_hash == hashlib.sha256(full_key.encode()).hexdigest()

    def test_hash_roundtrip(self):
        full_key, key_hash, _ = generate_api_key()
        assert hash_key(full_key) == key_hash

    def test_keys_unique(self):
        keys = {generate_api_key()[0] for _ in range(50)}
        assert len(keys) == 50


class TestSchemas:
    def test_project_defaults(self):
        p = ProjectCreate(name="test")
        assert p.chunk_size == 1000
        assert p.chunk_overlap == 200
        assert p.embedding_provider == "openai"
        assert p.top_k == 5

    def test_chunk_size_bounds(self):
        with pytest.raises(ValueError):
            ProjectCreate(name="x", chunk_size=50)
        with pytest.raises(ValueError):
            ProjectCreate(name="x", chunk_size=10000)

    def test_name_required(self):
        with pytest.raises(ValueError):
            ProjectCreate(name="")

    def test_key_material_never_serialized(self):
        # masked outputs must never expose raw or encrypted keys
        provider_fields = set(ProviderKeyOut.model_fields)
        assert "encrypted_key" not in provider_fields
        assert "key" not in provider_fields
        assert "last4" in provider_fields

        project_fields = set(ProjectOut.model_fields)
        assert "embedding_key_encrypted" not in project_fields
        assert "llm_key_encrypted" not in project_fields
        assert "embedding_key_last4" in project_fields
        assert "llm_key_last4" in project_fields


class TestGeneration:
    def test_prompt_numbers_sources(self):
        sources = [
            {"filename": "a.pdf", "page_number": 1, "content": "alpha"},
            {"filename": "b.pdf", "page_number": 7, "content": "beta"},
        ]
        prompt = build_user_prompt("what?", sources)
        assert "[1] a.pdf (page 1):\nalpha" in prompt
        assert "[2] b.pdf (page 7):\nbeta" in prompt
        assert prompt.endswith("Question: what?")


class TestConversion:
    def test_supported_upload_extensions(self):
        assert is_supported_upload("handbook.pdf")
        assert is_supported_upload("notes.docx")
        assert is_supported_upload("site.html")
        assert is_supported_upload("dataset.csv")
        assert not is_supported_upload("binary.exe")

    def test_markdown_sidecar_path(self):
        assert markdown_path_for("owner/project/file.pdf") == "owner/project/file.pdf.md"


class TestMemoryGraph:
    def test_sections_from_markdown_headings(self):
        sections = _sections("# Intro\nAlpha\n## Details\nBeta", "file-id")
        assert [section.title for section in sections] == ["Intro", "Details"]
        assert [section.level for section in sections] == [1, 2]
        assert sections[0].end == sections[1].start


class TestParsePdf:
    def test_extracts_pages_with_text(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello Oreag, this is page one.")
        doc.new_page()  # blank page - should be skipped
        page3 = doc.new_page()
        page3.insert_text((72, 72), "And this is page three.")
        data = doc.tobytes()
        doc.close()

        pages = parse_pdf(data)
        assert [p[0] for p in pages] == [1, 3]
        assert "page one" in pages[0][1]

    def test_invalid_pdf_raises(self):
        with pytest.raises(Exception):
            parse_pdf(b"this is not a pdf")


class TestIngestionDeleteRace:
    """Deleting a file while it's queued/indexing must not blow up the
    background task - an exception escaping one task aborts every queued
    ingestion behind it (the 'delete during indexing crashes the backend' bug)."""

    class _FakeDB:
        def __init__(self, file_obj=None, commit_error=None):
            self._file = file_obj
            self._commit_error = commit_error
            self.commits = 0
            self.rollbacks = 0
            self.expunged = False

        def rollback(self):
            self.rollbacks += 1

        def expunge_all(self):
            self.expunged = True

        def get(self, model, key):
            from app.models import File as FileModel

            if model is FileModel:
                return self._file
            return None

        def commit(self):
            if self._commit_error:
                raise self._commit_error
            self.commits += 1

    def test_skips_quietly_when_file_was_deleted(self):
        from app.services.ingestion import mark_file_failed

        db = self._FakeDB(file_obj=None)
        mark_file_failed(db, uuid.uuid4(), "boom")  # must not raise
        assert db.expunged  # bypassed the stale identity map
        assert db.commits == 0  # nothing to mark

    def test_swallows_errors_from_the_marking_commit(self):
        from app.models import File as FileModel
        from app.services.ingestion import mark_file_failed

        file_obj = FileModel(project_id=uuid.uuid4())
        db = self._FakeDB(file_obj=file_obj, commit_error=RuntimeError("row gone"))
        mark_file_failed(db, uuid.uuid4(), "boom")  # must not raise
        assert db.rollbacks >= 2  # initial rollback + cleanup after failed commit

    def test_marks_failed_when_file_still_exists(self):
        from app.models import File as FileModel
        from app.services.ingestion import mark_file_failed

        file_obj = FileModel(project_id=uuid.uuid4())
        db = self._FakeDB(file_obj=file_obj)
        mark_file_failed(db, uuid.uuid4(), "x" * 900)
        assert file_obj.status == "failed"
        assert len(file_obj.error) <= 500
        assert db.commits == 1


class TestApiSurface:
    def test_healthz(self):
        client = TestClient(app)
        assert client.get("/healthz").json() == {"status": "ok"}

    def test_dashboard_routes_require_auth(self):
        client = TestClient(app)
        assert client.get("/api/projects").status_code == 401
        assert client.get("/api/models").status_code == 401
        assert client.get("/api/provider-keys").status_code == 401

    def test_public_route_requires_api_key(self):
        client = TestClient(app)
        res = client.post(
            "/v1/projects/00000000-0000-0000-0000-000000000000/query",
            json={"question": "hi"},
        )
        assert res.status_code == 401

    def test_malformed_api_key_rejected(self):
        client = TestClient(app)
        res = client.post(
            "/v1/projects/00000000-0000-0000-0000-000000000000/query",
            json={"question": "hi"},
            headers={"Authorization": "Bearer wrong_prefix_key"},
        )
        assert res.status_code == 401

    def test_memory_graph_routes_require_auth(self):
        client = TestClient(app)
        project_id = "00000000-0000-0000-0000-000000000000"
        assert client.get(f"/api/projects/{project_id}/memory-graph").status_code == 401
        assert client.get(f"/v1/projects/{project_id}/memory-graph").status_code == 401

    def test_memory_routes_require_api_key(self):
        client = TestClient(app)
        pid = "00000000-0000-0000-0000-000000000000"
        assert client.post(f"/v1/projects/{pid}/memory", json={"content": "x"}).status_code == 401
        assert client.post(f"/v1/projects/{pid}/memory/search", json={"query": "x"}).status_code == 401
        assert client.get(f"/v1/projects/{pid}/memory/recent").status_code == 401

    def test_retrieve_requires_api_key(self):
        client = TestClient(app)
        pid = "00000000-0000-0000-0000-000000000000"
        assert client.post(f"/v1/projects/{pid}/retrieve", json={"query": "x"}).status_code == 401

    def test_owner_memory_requires_auth(self):
        client = TestClient(app)
        pid = "00000000-0000-0000-0000-000000000000"
        assert client.get(f"/api/projects/{pid}/memory").status_code == 401
