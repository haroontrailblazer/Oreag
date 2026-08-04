import base64
import datetime
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
from app.schemas import ProjectCreate, ProjectOut, ProjectUpdate, ProviderKeyOut
from app.services.conversion import (
    convert_to_markdown,
    is_ingestable,
    is_supported_upload,
    markdown_path_for,
    try_decode_text,
)
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

        def execute(self, *args, **kwargs):  # content_version bump
            pass

        def scalar(self, *args, **kwargs):  # memory-quota count -> way below cap
            return 0

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

    def test_change_plan_grow_is_restorable(self):
        # INVERTED by migration 0024. This used to assert "reembed", on the
        # premise that "the truncated tail was never stored". That premise was
        # the bug: the shrink now banks the wide original in embedding_full, so
        # growing back is a pure UPDATE and costs nothing.
        assert (
            embedding_change_plan(
                "openai", "text-embedding-3-large", 1024,
                "openai", "text-embedding-3-large", 3072,
            )
            == "restore"
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
        def __init__(self, fail: bool = False, archive_supported: bool = True):
            self.fail = fail
            self.archive_supported = archive_supported
            self.statements: list[str] = []
            self.rollbacks = 0

        def execute(self, statement, params=None):
            text = str(statement)
            # _archive_supported probes information_schema; answer that without
            # recording it as one of the migration statements.
            if "information_schema" in text:
                return self._Probe(self.archive_supported)
            if self.fail:
                raise RuntimeError("no subvector on this postgres")
            self.statements.append(text)
            return self._Probe(False)

        class _Probe:
            def __init__(self, found: bool):
                self._found = found

            def first(self):
                return (1,) if self._found else None

            def all(self):
                return []

        def rollback(self):
            self.rollbacks += 1

    def test_shrink_updates_chunks_and_memories(self):
        from app.routers.files import _shrink_vectors_in_place

        db = self._RecordingDB(archive_supported=True)
        project = Project(id=uuid.uuid4(), embedding_dimensions=3072)
        assert _shrink_vectors_in_place(db, project, 1024) is True
        joined = "\n".join(db.statements).lower()
        assert "update chunks" in joined
        assert "update memories" in joined
        # both tables go through the same MRL prefix + re-normalize
        assert joined.count("subvector") == 2
        assert joined.count("l2_normalize") == 2
        # and both bank the wide original in the SAME statement
        assert joined.count("embedding_full =") == 2
        # the shrink remembers the width to restore back to
        assert project.embedding_native_dimensions == 3072

    def test_shrink_without_migration_0024_stays_free(self):
        """Deploy-order safety: referencing the archive columns before the SQL
        lands would raise, roll back and demote to a PAID re-embed. Shrinking
        destructively is exactly today's behaviour; charging for it is not."""
        from app.routers.files import _shrink_vectors_in_place

        db = self._RecordingDB(archive_supported=False)
        project = Project(id=uuid.uuid4(), embedding_dimensions=3072)
        assert _shrink_vectors_in_place(db, project, 1024) is True
        joined = "\n".join(db.statements).lower()
        assert "embedding_full" not in joined
        assert joined.count("l2_normalize") == 2
        # nothing was archived, so nothing claims to be restorable
        assert project.embedding_native_dimensions is None

    def test_shrink_falls_back_cleanly_on_db_error(self):
        from app.routers.files import _shrink_vectors_in_place

        db = self._RecordingDB(fail=True)
        assert (
            _shrink_vectors_in_place(db, Project(id=uuid.uuid4()), 512) is False
        )
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

            def execute(self, *args, **kwargs):  # content_version bump
                pass

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
        # INVERTED. This used to request cohere at 512 and assert
        # _send_dimensions is True, encoding the belief that embed-v4.0's
        # Matryoshka sizes were reachable. They are not on this transport:
        # Cohere's compatibility endpoint documents `dimensions` as unsupported
        # for embeddings and returns 1536 whatever you ask for - so the test
        # was asserting a promise the wire could not keep.
        with pytest.raises(ValueError):
            get_embedder("cohere", "embed-v4.0", api_key="k", dimensions=512)

        emb = get_embedder("cohere", "embed-v4.0", api_key="k")
        assert emb.dimensions == 1536
        # Single reachable size => no dimensions param goes over the wire.
        assert emb._send_dimensions is False
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


class TestEmbedderDimensionsAreAlwaysPassed:
    """Every get_embedder() call must pass dimensions=.

    Omitting it does not fail loudly - resolve_embedding_dimensions quietly
    substitutes the MODEL's default size. For a project that shrank a
    Matryoshka model in place (3072 -> 768, offered in Settings as an instant
    truncation) that produces a query vector of the wrong width, and pgvector
    refuses to compare mismatched widths.

    Asserted across the whole services package rather than per-call-site,
    because that is what would have caught it: explore.py was the ONE omission
    out of seven, and every individual site around it looked fine.
    """

    def _call_sites(self):
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "app"
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name == "get_embedder":
                    yield path, node

    def test_every_call_site_passes_dimensions(self):
        offenders = [
            f"{path.name}:{node.lineno}"
            for path, node in self._call_sites()
            if not any(kw.arg == "dimensions" for kw in node.keywords)
        ]
        assert offenders == [], (
            "get_embedder() without dimensions= silently uses the model default "
            f"instead of the project's configured size: {offenders}"
        )

    def test_the_scan_actually_finds_call_sites(self):
        """Guards the guard: a broken walk would make the test above vacuous."""
        assert len(list(self._call_sites())) >= 6


class TestGeminiProviderCompat:
    """The prefix must not decide the backend.

    This class previously asserted the opposite - that an "AQ." key routes to
    Vertex - which broke every key Google AI Studio issues today, since AQ. is
    now the only prefix it hands out for new keys. Verified live: an AQ. key
    lists models and embeds successfully on the Developer API.
    """

    def test_both_key_prefixes_are_recognised_as_api_keys(self):
        from app.providers.gemini_provider import looks_like_api_key

        assert looks_like_api_key("AQ.Ab8example")  # current AI Studio format
        assert looks_like_api_key("AIzaSyExample")  # legacy format
        assert not looks_like_api_key("")

    def test_other_google_credential_types_are_not_api_keys(self):
        """OAuth tokens and service-account JSON are the credentials people
        actually paste by mistake; google-genai can consume neither."""
        from app.providers.gemini_provider import looks_like_api_key

        assert not looks_like_api_key("ya29.a0AfB_oauth-access-token")
        assert not looks_like_api_key('{"type": "service_account"}')

    def test_no_key_shape_selects_the_vertex_backend(self, monkeypatch):
        """The regression guard. Vertex is reached only via vertexai=True, and
        nothing about the key may set it - an AQ. key sent there 403s with
        SERVICE_DISABLED for anyone without aiplatform enabled."""
        from google import genai

        import app.providers.gemini_provider as gp

        seen = []

        def fake_client(**kwargs):
            seen.append(kwargs)
            return object()

        # setattr on the real module, NOT setitem on sys.modules: _client does
        # `from google import genai`, which reads an ATTRIBUTE of the already
        # imported `google` package, so a sys.modules swap never reaches it.
        monkeypatch.setattr(genai, "Client", fake_client)

        for key in ["AQ.Ab8example", "AIzaSyExample"]:
            gp._client(key)
        assert seen, "client was never constructed"
        assert all("vertexai" not in kwargs for kwargs in seen)
        assert [kwargs["api_key"] for kwargs in seen] == [
            "AQ.Ab8example",
            "AIzaSyExample",
        ]


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
            openai_provider, "_client", lambda key, timeout=None: self._fake_client(calls)
        )
        llm = openai_provider.OpenAILLM("gpt-5.5", "k")
        assert llm.generate("sys", "user") == "ok"
        assert calls[0]["reasoning_effort"] == "none"
        assert "temperature" not in calls[0]

    def test_legacy_models_keep_temperature_zero(self, monkeypatch):
        from app.providers import openai_provider

        calls: list[dict] = []
        monkeypatch.setattr(
            openai_provider, "_client", lambda key, timeout=None: self._fake_client(calls)
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


class TestProjectDescriptionEdit:
    """Editing the description from project Settings.

    The interesting case is CLEARING it. `ProjectUpdate.description` is
    `str | None`, and the router skips the field when it is None - so null
    cannot double as "erase this", or the one edit the user asked for would
    silently no-op. Blank string is the clear signal, and it must land in the
    column as NULL so "no description" has a single representation shared with
    freshly-created projects.
    """

    class _DB:
        """Enough Session for update_project: no name clash, no counts."""

        def scalar(self, *args, **kwargs):  # _name_taken
            return None

        def execute(self, *args, **kwargs):  # _counts
            return self

        def all(self):
            return []

        def commit(self):
            pass

    def _update(self, project, **fields):
        from app.routers.projects import update_project

        return update_project(ProjectUpdate(**fields), project, self._DB())

    def _project(self, description="Original text"):
        # status/suspended/timestamps are server-side column defaults, so an
        # unsaved instance leaves them None and ProjectOut validation trips.
        now = datetime.datetime.now(datetime.timezone.utc)
        return Project(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="proj",
            description=description,
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            chunk_size=1000,
            chunk_overlap=200,
            top_k=5,
            status="ready",
            suspended=False,
            created_at=now,
            updated_at=now,
        )

    def test_description_is_updated(self):
        project = self._project()
        self._update(project, description="Rewritten")
        assert project.description == "Rewritten"

    def test_blank_clears_it_to_null(self):
        project = self._project()
        self._update(project, description="")
        assert project.description is None

    def test_whitespace_only_also_clears(self):
        """Otherwise the card renders a blank line instead of collapsing."""
        project = self._project()
        self._update(project, description="   \n  ")
        assert project.description is None

    def test_omitting_the_field_leaves_it_alone(self):
        """A PATCH that only touches top_k must not wipe the description."""
        project = self._project()
        self._update(project, top_k=9)
        assert project.description == "Original text"
        assert project.top_k == 9

    def test_description_survives_a_rename(self):
        project = self._project()
        self._update(project, name="renamed", description="Original text")
        assert project.name == "renamed"
        assert project.description == "Original text"


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


class TestNulBytesNeverReachPostgres:
    """A NUL (0x00) anywhere in a document failed the whole INSERT.

    Real-world cause, measured on five PDFs: PyMuPDF emits 0x00 for a glyph it
    cannot map to a codepoint, which in practice means emoji and icon-font
    characters. One emoji bullet on page 17 of a 33-page PDF was enough to mark
    the entire file failed with "(psycopg.DataError) PostgreSQL text fields
    cannot contain NUL (0x00) bytes" - a database error about a document that
    reads perfectly. The sibling PDF that indexed fine simply had no emoji.
    """

    def test_strip_nul_removes_only_the_nul(self):
        from app.services.conversion import strip_nul

        assert strip_nul("- \x00Can the agent recover?") == "- Can the agent recover?"
        assert strip_nul("Pencil \x00\x00 Learning") == "Pencil  Learning"

    def test_ordinary_text_is_returned_untouched(self):
        """Including the emoji that DID map - only unmappable glyphs become
        NUL, and the rest of the document must survive verbatim."""
        from app.services.conversion import strip_nul

        for text in ["plain", "", "emoji ✅ ok", "tabs\tand\nnewlines"]:
            assert strip_nul(text) == text

    def test_every_converted_document_is_cleaned(self):
        """Enforced on the dataclass, not at each return, so a converter added
        later cannot reintroduce this by forgetting to sanitise."""
        from app.services.conversion import ConvertedDocument

        assert ConvertedDocument(markdown="a\x00b", page_count=1).markdown == "ab"
        assert ConvertedDocument(markdown="x\x00", page_count=None).markdown == "x"

    def test_the_column_type_is_the_backstop(self):
        from app.models import NulSafeText

        assert NulSafeText().process_bind_param("x\x00y", None) == "xy"
        assert NulSafeText().process_bind_param("clean", None) == "clean"
        assert NulSafeText().process_bind_param(None, None) is None

    def test_external_text_columns_all_use_it(self):
        """The three places arbitrary outside text lands. Missing one leaves a
        path that still 500s on the same byte."""
        from app.models import Chunk, Memory, NulSafeText, QueryLog, SemanticQueryCache

        for column in (
            Chunk.__table__.c.content,
            Memory.__table__.c.content,
            QueryLog.__table__.c.question,
            # The semantic cache stores the asked question verbatim too, so a
            # NUL there would fail the cache write rather than the query.
            SemanticQueryCache.__table__.c.question,
        ):
            assert isinstance(column.type, NulSafeText), column


class TestConversion:
    def test_supported_upload_extensions(self):
        assert is_supported_upload("handbook.pdf")
        assert is_supported_upload("notes.docx")
        assert is_supported_upload("site.html")
        assert is_supported_upload("dataset.csv")
        assert not is_supported_upload("binary.exe")

    def test_markdown_sidecar_path(self):
        assert markdown_path_for("owner/project/file.pdf") == "owner/project/file.pdf.md"

    def test_text_files_ingestable_regardless_of_extension(self):
        code = b"def hello():\n    return 42\n"
        assert try_decode_text(code) == "def hello():\n    return 42\n"
        assert is_ingestable("script.py", code)
        assert is_ingestable("Dockerfile", b"FROM python:3.12\n")

    def test_opaque_binary_rejected(self):
        exe = b"MZ\x90\x00\x03\x00\x00\x00"
        assert try_decode_text(exe) is None
        assert not is_ingestable("app.exe", exe)
        # allowlisted extensions still route to MarkItDown, whatever the bytes
        assert is_ingestable("doc.pdf", exe)

    def test_convert_falls_back_to_plain_text(self):
        doc = convert_to_markdown(b"server:\n  port: 8080\n", "config.yaml")
        assert doc.markdown == "server:\n  port: 8080"
        assert doc.page_count is None

    def test_convert_rejects_unknown_binary(self):
        with pytest.raises(ValueError, match="Unsupported binary"):
            convert_to_markdown(b"MZ\x90\x00\x03\x00\x00\x00", "blob.bin")

    def test_cp1252_fallback_decodes_legacy_text(self):
        assert try_decode_text("caf\xe9 menu".encode("cp1252")) == "caf\xe9 menu"


# 1x1 transparent PNG - a real, valid image so MarkItDown's converter accepts it.
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class _FakeVisionClient:
    """OpenAI-SDK-shaped client that records the captioning request."""

    def __init__(self, caption="A tiny test pixel."):
        self.requests: list[dict] = []
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.requests.append(kwargs)
                msg = type("M", (), {"content": outer.caption})()
                choice = type("C", (), {"message": msg})()
                return type("R", (), {"choices": [choice]})()

        class _Chat:
            completions = _Completions()

        self.caption = caption
        self.chat = _Chat()


def _transcriber(text=None, fail=False):
    """A (data, filename) -> text stand-in for one provider's STT."""

    def transcribe(data, filename):
        if fail:
            raise RuntimeError("provider STT unavailable")
        return text

    return transcribe


class TestRichMediaIngestion:
    def test_image_is_ai_captioned_through_llm_client(self):
        client = _FakeVisionClient(caption="Screenshot of an invoice, total 42 USD.")
        doc = convert_to_markdown(
            _TINY_PNG, "shot.png", llm_client=client, llm_model="gpt-4o-mini"
        )
        assert "Screenshot of an invoice, total 42 USD." in doc.markdown
        # The captioning request carried the image and our verbatim-text prompt.
        [request] = client.requests
        assert request["model"] == "gpt-4o-mini"
        content = request["messages"][0]["content"]
        assert any(part.get("type") == "image_url" for part in content)
        assert any("verbatim" in part.get("text", "") for part in content)

    def test_image_without_vision_model_fails_with_guidance(self):
        with pytest.raises(ValueError, match="OpenAI or Gemini"):
            convert_to_markdown(_TINY_PNG, "shot.png")

    def test_audio_uses_byok_transcriber_and_skips_markitdown(self, monkeypatch):
        import markitdown

        def _boom(*a, **k):
            raise AssertionError("MarkItDown must not run when BYOK succeeds")

        monkeypatch.setattr(markitdown, "MarkItDown", _boom)
        doc = convert_to_markdown(
            b"not-really-audio", "meeting.mp3",
            transcribers=[("openai", _transcriber("quarterly numbers are up"))],
        )
        assert doc.markdown == "quarterly numbers are up"
        assert doc.page_count is None

    def test_audio_chain_moves_to_next_provider_on_failure(self, monkeypatch):
        import markitdown

        def _boom(*a, **k):
            raise AssertionError("MarkItDown must not run when the chain succeeds")

        monkeypatch.setattr(markitdown, "MarkItDown", _boom)
        doc = convert_to_markdown(
            b"not-really-audio", "meeting.mp3",
            transcribers=[
                ("gemini", _transcriber(fail=True)),
                ("sarvam", _transcriber("nammalude quarterly report")),
            ],
        )
        assert doc.markdown == "nammalude quarterly report"

    def test_audio_falls_back_to_free_endpoint_when_chain_exhausted(self, monkeypatch):
        import markitdown

        class _FakeMD:
            def __init__(self, **kwargs):
                pass

            def convert(self, path):
                return type("R", (), {"text_content": "google transcript"})()

        monkeypatch.setattr(markitdown, "MarkItDown", _FakeMD)
        doc = convert_to_markdown(
            b"not-really-audio", "meeting.mp3",
            transcribers=[
                ("openai", _transcriber(fail=True)),
                ("mistral", _transcriber(text=None)),  # succeeded but empty
            ],
        )
        assert doc.markdown == "google transcript"
        # The uploader is told their keys were bypassed - and which ones.
        assert "free Google speech endpoint" in doc.note
        assert "openai, mistral" in doc.note

    def test_audio_fallback_note_names_missing_keys(self, monkeypatch):
        import markitdown

        class _FakeMD:
            def __init__(self, **kwargs):
                pass

            def convert(self, path):
                return type("R", (), {"text_content": "google transcript"})()

        monkeypatch.setattr(markitdown, "MarkItDown", _FakeMD)
        doc = convert_to_markdown(b"not-really-audio", "meeting.mp3", transcribers=[])
        assert "none of your API keys support speech-to-text" in doc.note

    def test_byok_transcription_carries_no_note(self, monkeypatch):
        import markitdown

        def _boom(*a, **k):
            raise AssertionError("MarkItDown must not run when BYOK succeeds")

        monkeypatch.setattr(markitdown, "MarkItDown", _boom)
        doc = convert_to_markdown(
            b"not-really-audio", "meeting.mp3",
            transcribers=[("openai", _transcriber("clean transcript"))],
        )
        assert doc.note is None

    def test_non_audio_files_carry_no_note(self):
        doc = convert_to_markdown(b"server:\n  port: 8080\n", "config.yaml")
        assert doc.note is None


class TestVisionAndTranscriptionClients:
    def _project(self, provider, model="gpt-4o-mini"):
        return Project(llm_provider=provider, llm_model=model)

    def test_openai_project_gets_vision_client(self):
        from app.services.ingestion import vision_llm_for

        client, model = vision_llm_for(self._project("openai"), "sk-test")
        assert client is not None and model == "gpt-4o-mini"

    def test_gemini_project_routes_through_openai_compat_endpoint(self):
        from app.services.ingestion import vision_llm_for

        client, model = vision_llm_for(
            self._project("gemini", "gemini-2.5-flash"), "AIza-test"
        )
        assert client is not None and model == "gemini-2.5-flash"
        assert "generativelanguage.googleapis.com" in str(client.base_url)

    def test_modern_aq_key_still_gets_captioning(self):
        """Inverted deliberately. AQ. keys used to be refused captioning as
        "Vertex only"; they are ordinary AI Studio keys, so refusing them
        silently disabled image captioning for every current Gemini user and
        surfaced as "No text could be extracted"."""
        from app.services.ingestion import vision_llm_for

        client, model = vision_llm_for(
            self._project("gemini", "gemini-2.5-flash"), "AQ.Ab8example"
        )
        assert client is not None and model == "gemini-2.5-flash"
        assert "generativelanguage.googleapis.com" in str(client.base_url)

    def test_other_providers_get_no_captioning(self):
        from app.services.ingestion import vision_llm_for

        assert vision_llm_for(self._project("anthropic"), "sk-ant") == (None, None)
        assert vision_llm_for(self._project("openai"), None) == (None, None)

    def test_every_stt_provider_yields_a_transcriber(self):
        from app.providers.transcription import STT_PROVIDERS, transcriber_for

        for provider in STT_PROVIDERS:
            assert callable(transcriber_for(provider, "key-123")), provider
        assert transcriber_for("anthropic", "key-123") is None

    def test_transcriber_chain_prefers_the_projects_own_provider(self, monkeypatch):
        from app.services import ingestion

        keys = {"gemini": "AIza-x", "sarvam": "sv-x", "openai": None,
                "groq": None, "mistral": None}
        monkeypatch.setattr(
            ingestion.resolver,
            "resolve_key_for_provider",
            lambda db, project, provider: keys.get(provider),
        )
        chain = ingestion.audio_transcribers_for(
            None, self._project("gemini", "gemini-2.5-flash")
        )
        assert [name for name, _ in chain] == ["gemini", "sarvam"]

    def test_transcriber_chain_finds_other_keys_for_sttless_providers(self, monkeypatch):
        """An Anthropic-answering project still transcribes with the owner's
        OpenAI key - Anthropic itself has no speech-to-text."""
        from app.services import ingestion

        keys = {"openai": "sk-x"}
        monkeypatch.setattr(
            ingestion.resolver,
            "resolve_key_for_provider",
            lambda db, project, provider: keys.get(provider),
        )
        chain = ingestion.audio_transcribers_for(None, self._project("anthropic"))
        assert [name for name, _ in chain] == ["openai"]

    def test_transcriber_chain_empty_without_stt_keys(self, monkeypatch):
        from app.services import ingestion

        monkeypatch.setattr(
            ingestion.resolver,
            "resolve_key_for_provider",
            lambda db, project, provider: None,
        )
        assert ingestion.audio_transcribers_for(None, self._project("anthropic")) == []

    def test_resolve_key_for_provider_uses_account_key(self, monkeypatch):
        from app.providers import resolver

        monkeypatch.setattr(
            resolver, "_account_key", lambda db, owner, provider: f"acct-{provider}"
        )
        project = Project(
            owner_id=uuid.uuid4(), llm_provider="anthropic", llm_key_encrypted=None
        )
        assert resolver.resolve_key_for_provider(None, project, "openai") == "acct-openai"


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

        def execute(self, *args, **kwargs):  # chunk cleanup + version bump
            pass

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


class TestProjectSuspend:
    """A suspended project keeps all its data but blocks the public /v1 API and
    MCP (both funnel through rag_v1._get_project)."""

    class _DB:
        def __init__(self, project, account_suspended=False):
            self._project = project
            self._account_suspended = account_suspended

        def get(self, model, key):
            return self._project

        def scalar(self, *args, **kwargs):  # suspended_accounts lookup
            return self._project.owner_id if self._account_suspended else None

    def test_get_project_blocks_when_suspended(self):
        from fastapi import HTTPException

        from app.routers.rag_v1 import _get_project

        project = Project(id=uuid.uuid4(), suspended=True)
        with pytest.raises(HTTPException) as exc:
            _get_project(self._DB(project), project.id)
        assert exc.value.status_code == 403

    def test_get_project_allows_when_active(self):
        from app.routers.rag_v1 import _get_project

        project = Project(id=uuid.uuid4(), suspended=False)
        assert _get_project(self._DB(project), project.id) is project

    def test_get_project_blocks_suspended_account(self):
        """The operator kill switch cuts off ALL of an account's projects."""
        from fastapi import HTTPException

        from app.routers.rag_v1 import _get_project

        project = Project(id=uuid.uuid4(), owner_id=uuid.uuid4(), suspended=False)
        with pytest.raises(HTTPException) as exc:
            _get_project(self._DB(project, account_suspended=True), project.id)
        assert exc.value.status_code == 403
        assert "account is suspended" in exc.value.detail

    def test_project_out_defaults_suspended_false(self):
        cols = set(Project.__table__.columns.keys())
        assert "suspended" in cols


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


class TestPublicProjectInfoCounts:
    """GET /v1/projects/{id} must report the counts it claims to.

    chunk_count was declared on ProjectInfo with a default of 0 and then never
    passed by the handler, so a fully indexed project reported "0 chunks" to
    every API consumer. Nothing errored - the number was just always wrong,
    which is why it survived. A field with a silent default needs a test that
    the producer actually fills it.
    """

    def test_handler_populates_every_declared_field(self):
        import inspect

        from app.routers import rag_v1
        from app.schemas import ProjectInfo

        src = inspect.getsource(rag_v1.project_info)
        for field in ProjectInfo.model_fields:
            assert f"{field}=" in src, f"project_info never sets {field!r}"

    def test_chunk_count_is_not_left_to_its_default(self):
        from app.schemas import ProjectInfo

        # Guards the shape of the bug: the default is what hid it, so if the
        # default is ever removed this test should be revisited, not deleted.
        assert ProjectInfo.model_fields["chunk_count"].default == 0


class TestImageOnlyPdfDiagnosis:
    """A scanned PDF must say WHY it failed, not just that it failed.

    Real case: DL.pdf - one page, one embedded image, zero characters. The
    generic "No extractable text found in this file" is true but blames the
    file without naming the cause, and hides the fact that Oreag can read that
    exact content if the page is uploaded as an image instead.
    """

    def _pdf(self, *, with_text: bool, with_image: bool) -> bytes:
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page()
        if with_text:
            page.insert_text((72, 72), "readable text layer")
        if with_image:
            # A tiny real PNG, so get_images() actually reports one.
            png = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False)
            png.set_rect(png.irect, (255, 0, 0))
            page.insert_image(pymupdf.Rect(100, 100, 180, 180), pixmap=png)
        data = doc.tobytes()
        doc.close()
        return data

    def test_scanned_pdf_is_recognised(self):
        from app.services.conversion import pdf_is_image_only

        assert pdf_is_image_only(self._pdf(with_text=False, with_image=True))

    def test_a_normal_pdf_is_not_flagged(self):
        from app.services.conversion import pdf_is_image_only

        assert not pdf_is_image_only(self._pdf(with_text=True, with_image=False))
        # Text AND images is an ordinary illustrated document.
        assert not pdf_is_image_only(self._pdf(with_text=True, with_image=True))

    def test_empty_pdf_is_not_blamed_on_scanning(self):
        """No text and no image is a different fault - saying "scanned" there
        would send the user off to OCR a file that has nothing in it."""
        from app.services.conversion import pdf_is_image_only

        assert not pdf_is_image_only(self._pdf(with_text=False, with_image=False))

    def test_garbage_input_never_raises(self):
        """Runs inside an error path; throwing here would replace a clear
        message with a 500."""
        from app.services.conversion import pdf_is_image_only

        assert not pdf_is_image_only(b"not a pdf at all")
        assert not pdf_is_image_only(b"")


class TestVectorWidthGuard:
    """A provider that ignores the requested size must not corrupt the index.

    chunks.embedding is an untyped `Vector` column, so a 1536-wide vector
    inserts happily into a project configured for 512 - no error, just a
    silently wrong vector space and answers to match. Cohere's compatibility
    endpoint did exactly this: it accepts `dimensions` and returns its native
    width regardless.
    """

    def test_mismatched_width_is_refused(self):
        from app.providers.base import ProviderUnavailableError, ensure_width

        with pytest.raises(ProviderUnavailableError) as exc:
            ensure_width([[0.0] * 1536], 512, "Cohere", "embed-v4.0")
        message = str(exc.value)
        # Both numbers have to appear or the error cannot be acted on.
        assert "1536" in message and "512" in message

    def test_correct_width_passes_through_unchanged(self):
        from app.providers.base import ensure_width

        vectors = [[0.1] * 768, [0.2] * 768]
        assert ensure_width(vectors, 768, "Gemini", "gemini-embedding-001") is vectors

    def test_every_vector_is_checked_not_just_the_first(self):
        """A partial batch failure is the likelier real-world shape."""
        from app.providers.base import ProviderUnavailableError, ensure_width

        with pytest.raises(ProviderUnavailableError):
            ensure_width([[0.0] * 768, [0.0] * 512], 768, "x", "y")

    def test_cohere_no_longer_offers_unreachable_sizes(self):
        """The compat endpoint ignores `dimensions`, so anything but the native
        1536 was a promise the transport could not keep."""
        from app.providers.registry import embedding_dimension_options

        assert embedding_dimension_options("cohere", "embed-v4.0") == [1536]

    def test_cohere_no_longer_sends_the_dimensions_param(self):
        """send_dimensions is derived from the option count, so trimming the
        catalog is also what stops the useless parameter going over the wire."""
        from app.providers.registry import embedding_dimension_options

        assert len(embedding_dimension_options("cohere", "embed-v4.0")) == 1


class TestEveryEmbedderIsGuarded:
    """No embedder may return vectors without checking their width.

    Written as a scan over the package rather than five separate assertions,
    because the first version of this guard covered three of the five embedder
    classes and the two it missed - Ollama and sentence-transformers - were the
    ones that need it MOST: neither endpoint takes a dimensions parameter at
    all, so their width is whatever the locally resolved model happens to
    produce. A per-class test would have passed while the gap stayed open.
    """

    def _embedder_sources(self):
        import ast
        import inspect
        import pkgutil
        import importlib

        import app.providers as providers

        found = []
        for mod in pkgutil.iter_modules(providers.__path__):
            module = importlib.import_module(f"app.providers.{mod.name}")
            for name, obj in vars(module).items():
                if (
                    isinstance(obj, type)
                    and name.endswith("Embedder")
                    and obj.__module__ == module.__name__
                ):
                    src = inspect.getsource(obj)
                    found.append((f"{mod.name}.{name}", ast.parse(src), src))
        return found

    def test_all_embedders_call_ensure_width(self):
        offenders = [
            name
            for name, _tree, src in self._embedder_sources()
            if "ensure_width" not in src
        ]
        assert offenders == [], (
            "these embedders return vectors without verifying the width: "
            f"{offenders}"
        )

    def test_the_scan_finds_every_known_embedder(self):
        """Guards the guard - a broken scan would make the test above vacuous."""
        names = {n.split(".")[1] for n, _t, _s in self._embedder_sources()}
        assert {
            "OpenAIEmbedder",
            "GeminiEmbedder",
            "CompatEmbedder",
            "OllamaEmbedder",
            "SentenceTransformersEmbedder",
        } <= names, names


class TestTruncationBumpsContentVersion:
    """Shrinking a Matryoshka model must move the cache signature.

    The fast path re-writes EVERY vector in the project in place and then
    returns early because nothing needs re-ingesting - and it used to return
    without bumping projects.content_version. That column is the cache key for
    the memory-graph response (services/memory_graph.py) and for the answer
    caches (services/query.py), so after a 3072 -> 1536 shrink the Visualize
    tab kept rendering the graph built from the OLD vectors and queries kept
    replaying answers computed against them. Nothing on screen suggested the
    shrink had not taken effect.

    Asserted by scanning the source: the bug was an early `return` skipping a
    call, and an execution-level test would need a live pgvector database to
    reach that branch at all.
    """

    def _truncate_branches(self):
        import ast
        import inspect

        from app.routers import files as files_router

        tree = ast.parse(inspect.getsource(files_router))
        # Every `if`/`elif` whose test mentions the truncate plan.
        return [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.If)
            and "truncate" in ast.unparse(node.test)
        ]

    def test_the_scan_finds_the_truncate_paths(self):
        """Guards the guard - a vacuous scan would pass the test below."""
        assert len(self._truncate_branches()) >= 2

    def test_every_truncate_path_bumps_the_version(self):
        """A branch is exempt only if it hands off to the re-embed path.

        `plan == "truncate" and not _truncate_vectors_in_place(...)` is the
        FALLBACK: truncation failed, so it sets plan = "reembed" and falls
        through to code that wipes the chunks and bumps there. Requiring a bump
        inside it would be wrong. What must never happen again is a truncate
        branch that neither bumps NOR defers - which is exactly what the
        early-returning fast path did.
        """
        import ast

        offenders = []
        for node in self._truncate_branches():
            body = ast.unparse(node)
            defers = 'plan = "reembed"' in body or "plan = 'reembed'" in body
            if "bump_content_version" not in body and not defers:
                offenders.append(ast.unparse(node.test))
        assert offenders == [], (
            "a truncate path rewrites every vector without bumping "
            f"content_version, leaving stale caches: {offenders}"
        )


class TestConvertedMarkdownReuse:
    """A re-embed must not pay for conversion twice.

    Re-embedding (model switch, or growing a Matryoshka dimension) deletes the
    chunks and re-ingests. That used to re-download the ORIGINAL file and run
    conversion again - for images that means re-running the vision model, for
    audio re-running speech-to-text, both on the user's own keys. The markdown
    was already in storage from the first pass.

    Everything here is about the guard rails, because the failure mode of a
    cache is serving something stale, and conversion output is only
    deterministic for a FIXED pipeline.
    """

    class _File:
        def __init__(self, **kw):
            self.id = uuid.uuid4()
            self.markdown_storage_path = kw.get("path", "p/doc.md")
            self.conversion_version = kw.get("version")

    def _reuse(self, monkeypatch, file, blob=b"# hello", raises=None):
        from app.services import ingestion

        def fake_download(path):
            if raises:
                raise raises
            return blob

        monkeypatch.setattr(ingestion.storage, "download", fake_download)
        return ingestion._reuse_converted_markdown(file)

    def test_current_version_is_reused(self, monkeypatch):
        from app.services.conversion import CONVERSION_VERSION

        file = self._File(version=CONVERSION_VERSION)
        assert self._reuse(monkeypatch, file) == "# hello"

    def test_markdown_from_an_older_pipeline_is_not_reused(self, monkeypatch):
        """The whole reason for the version. Blobs written before a conversion
        FIX still contain whatever it fixed - reusing them would silently undo
        it (e.g. the 0x00 bytes strip_nul now removes)."""
        from app.services.conversion import CONVERSION_VERSION

        file = self._File(version=CONVERSION_VERSION - 1)
        assert self._reuse(monkeypatch, file) is None

    def test_unstamped_rows_convert_again(self, monkeypatch):
        """Every row predating migration 0023 reads NULL, so the whole existing
        corpus re-converts once and is re-stamped - no bulk backfill."""
        assert self._reuse(monkeypatch, self._File(version=None)) is None

    def test_missing_markdown_path_converts(self, monkeypatch):
        assert self._reuse(monkeypatch, self._File(path=None)) is None

    def test_unreadable_blob_falls_back_instead_of_failing(self, monkeypatch):
        """This is an optimisation; a storage hiccup must cost time, not the
        whole ingest."""
        from app.services.conversion import CONVERSION_VERSION

        file = self._File(version=CONVERSION_VERSION)
        assert self._reuse(monkeypatch, file, raises=RuntimeError("gone")) is None

    def test_empty_blob_is_treated_as_absent(self, monkeypatch):
        """Returning "" would mark the file indexed with zero chunks - worse
        than converting again, because it looks like success."""
        from app.services.conversion import CONVERSION_VERSION

        file = self._File(version=CONVERSION_VERSION)
        assert self._reuse(monkeypatch, file, blob=b"   \n  ") is None

    def test_version_is_stamped_only_after_the_upload(self):
        """A crash between writing the blob and stamping the row must leave the
        row UNSTAMPED - claiming markdown that was never stored is the one
        failure this design cannot recover from on its own."""
        import inspect

        from app.services import ingestion

        src = inspect.getsource(ingestion.ingest_file)
        assert src.index("storage.upload_file") < src.index(
            "file.conversion_version = CONVERSION_VERSION"
        )


class TestReversibleMatryoshkaShrink:
    """Shrinking must be reversible, and reversing must not corrupt.

    Growing back used to re-embed because the shrink OVERWROTE the row - the
    wide tail was deleted, not hidden. Migration 0024 banks it in
    embedding_full instead. These tests pin the invariants three adversarial
    reviews said were the difference between reversible and corrupting.
    """

    def test_grow_is_restore_not_reembed(self):
        from app.providers.registry import embedding_change_plan

        assert (
            embedding_change_plan(
                "openai", "text-embedding-3-large", 1024,
                "openai", "text-embedding-3-large", 3072,
            )
            == "restore"
        )

    def test_shrink_is_still_truncate(self):
        from app.providers.registry import embedding_change_plan

        assert (
            embedding_change_plan(
                "openai", "text-embedding-3-large", 3072,
                "openai", "text-embedding-3-large", 1024,
            )
            == "truncate"
        )

    def test_a_model_switch_is_never_restorable(self):
        """An archive from another model is a vector from an incompatible
        space. Restoring it would produce embeddings that are silently
        meaningless rather than merely missing."""
        from app.providers.registry import embedding_change_plan

        assert (
            embedding_change_plan(
                "openai", "text-embedding-3-large", 1024,
                "gemini", "gemini-embedding-001", 3072,
            )
            == "reembed"
        )

    def test_a_size_the_model_does_not_offer_is_reembed(self):
        from app.providers.registry import embedding_change_plan

        assert (
            embedding_change_plan(
                "openai", "text-embedding-3-large", 1024,
                "openai", "text-embedding-3-large", 2048,
            )
            == "reembed"
        )

    def test_model_switch_clears_the_memory_ARCHIVE_too(self):
        """THE load-bearing invariant. If a model switch nulls memories.embedding
        but leaves embedding_full, a later grow restores an old-model vector
        into the new model's space - corruption that no error reports."""
        from app.routers.files import _CLEAR_MEMORY_EMBEDDINGS_SQL

        sql = str(_CLEAR_MEMORY_EMBEDDINGS_SQL).lower()
        assert "embedding = null" in sql
        assert "embedding_full = null" in sql

    def test_shrink_never_narrows_an_existing_archive(self):
        """3072 -> 1536 -> 768 must keep the 3072 archive. Overwriting it with
        the 1536 intermediate would make the trip irreversible one step after
        the user was told it was reversible."""
        from app.routers.files import _SHRINK_CHUNKS_SQL, _SHRINK_MEMORIES_SQL

        for stmt in (_SHRINK_CHUNKS_SQL, _SHRINK_MEMORIES_SQL):
            sql = " ".join(str(stmt).split()).lower()
            assert "case" in sql and "embedding_full is null" in sql
            assert "vector_dims(embedding_full) < vector_dims(embedding)" in sql

    def test_shrink_archives_and_truncates_in_one_statement(self):
        """Two statements would leave an instant where the tail exists nowhere.
        SET expressions read the pre-update row, so one statement is atomic."""
        from app.routers.files import _SHRINK_CHUNKS_SQL

        sql = " ".join(str(_SHRINK_CHUNKS_SQL).split()).lower()
        assert sql.count("update") == 1
        assert "embedding_full =" in sql and "embedding = l2_normalize" in sql

    def test_shrink_is_idempotent(self):
        """A retry must not re-archive a narrower vector over a wider one."""
        from app.routers.files import _SHRINK_CHUNKS_SQL

        sql = " ".join(str(_SHRINK_CHUNKS_SQL).split()).lower()
        assert "vector_dims(embedding) > :dims" in sql

    def test_restore_clears_the_archive_only_when_fully_grown(self):
        """Growing to an intermediate width must KEEP the wider archive, or the
        next grow silently becomes a paid re-embed."""
        from app.routers.files import _RESTORE_CHUNKS_SQL

        sql = " ".join(str(_RESTORE_CHUNKS_SQL).split()).lower()
        assert "vector_dims(embedding_full) <= :dims" in sql
        assert "then null" in sql

    def test_unmigrated_database_keeps_the_free_shrink(self):
        """Deploy-order safety. Referencing the archive columns before 0024 runs
        would raise, roll back, and demote to 'reembed' - turning today's FREE
        shrink into a PAID one purely because code shipped before SQL."""
        import inspect

        from app.routers import files as files_router

        src = inspect.getsource(files_router._shrink_vectors_in_place)
        assert "_archive_supported" in src
        assert "_LEGACY_TRUNCATE_CHUNKS_SQL" in src

    def test_archive_support_probe_is_not_memoised(self):
        """Migrations land while old instances serve. A cached 'absent' would
        keep shrinking destructively for the whole process lifetime."""
        import inspect

        from app.routers import files as files_router

        src = inspect.getsource(files_router._archive_supported)
        assert "lru_cache" not in src and "cache" not in src.split('"""')[2]

    def test_restore_path_only_fills_missing_memories(self):
        """A partial restore has just put correct vectors back; re-embedding
        everything would pay to overwrite exactly what it preserved."""
        import inspect

        from app.services.memory import reembed_project_memories

        sig = inspect.signature(reembed_project_memories)
        assert "only_missing" in sig.parameters
        assert sig.parameters["only_missing"].default is False

    def test_archive_columns_are_deferred(self):
        """Undeferred, every full ORM load of a Chunk or Memory would ship a
        second whole vector over the wire."""
        from sqlalchemy import inspect as sa_inspect

        from app.models import Chunk, Memory

        for model in (Chunk, Memory):
            attr = sa_inspect(model).attrs["embedding_full"]
            assert attr.deferred, f"{model.__name__}.embedding_full must be deferred"

    def test_ingest_prefix_matches_the_sql_shrink(self):
        """A chunk ingested while shrunk must be comparable with one shrunk in
        place - same prefix, same re-normalisation."""
        import math

        from app.services.ingestion import _prefix_normalize

        out = _prefix_normalize([3.0, 4.0, 99.0, 99.0], 2)
        assert len(out) == 2
        assert math.isclose(math.sqrt(sum(v * v for v in out)), 1.0, rel_tol=1e-9)
        assert math.isclose(out[0], 0.6, rel_tol=1e-9)

    def test_prefix_normalize_survives_a_zero_vector(self):
        from app.services.ingestion import _prefix_normalize

        assert _prefix_normalize([0.0, 0.0, 1.0], 2) == [0.0, 0.0]


class TestPartialRestoreScope:
    """Growing back must re-embed ONLY the files the archive could not cover.

    The hard case: a file uploaded while the project was shrunk to 1536 never
    had 3072 numbers, so growing back can restore every other file but not that
    one. Two wrong answers are available and both are expensive - re-embed the
    whole corpus (hands back the bill the archive exists to avoid), or leave the
    odd file at the old width (retrieval compares with <=>, which RAISES on
    mismatched widths on the exact path and silently drops the row on the ANN
    path - a project that is either broken or quietly lying).
    """

    class _F:
        def __init__(self):
            self.id = uuid.uuid4()

    def test_only_the_gap_files_are_requeued(self):
        from app.routers.files import _files_to_requeue

        keep_a, gap, keep_b = self._F(), self._F(), self._F()
        files = [keep_a, gap, keep_b]
        assert _files_to_requeue(files, [gap.id]) == [gap]

    def test_an_empty_gap_requeues_everything(self):
        """No gap means this is not a partial restore - a model switch or a
        chunking change - and those must still re-ingest the whole project."""
        from app.routers.files import _files_to_requeue

        files = [self._F(), self._F()]
        assert _files_to_requeue(files, []) == files

    def test_a_gap_naming_every_file_requeues_every_file(self):
        from app.routers.files import _files_to_requeue

        files = [self._F(), self._F()]
        assert _files_to_requeue(files, [f.id for f in files]) == files

    def test_a_stale_gap_id_cannot_resurrect_a_deleted_file(self):
        """Backstop half of the guarantee: even handed a dead id, the requeue
        list only ever contains files that still exist."""
        from app.routers.files import _files_to_requeue

        alive = self._F()
        assert _files_to_requeue([alive], [uuid.uuid4()]) == []

    def test_the_gap_query_cannot_return_a_deleted_file(self):
        """Primary half: the JOIN means a dead id never leaves the database, so
        the guarantee does not depend on the caller remembering to intersect.
        The gap query and the later file SELECT are two statements under READ
        COMMITTED - a delete landing between them would otherwise leave a
        live-looking id in a list built from the earlier snapshot."""
        from app.routers.files import _UNRESTORABLE_CHUNK_FILES_SQL

        sql = " ".join(str(_UNRESTORABLE_CHUNK_FILES_SQL).split()).lower()
        assert "join files f on f.id = c.file_id" in sql

    def test_the_gap_query_finds_rows_the_archive_cannot_reach(self):
        from app.routers.files import _UNRESTORABLE_CHUNK_FILES_SQL

        sql = " ".join(str(_UNRESTORABLE_CHUNK_FILES_SQL).split()).lower()
        assert "select distinct c.file_id" in sql
        # wrong width now...
        assert "vector_dims(c.embedding) <> :dims" in sql
        # ...AND no archive able to supply it
        assert "c.embedding_full is null" in sql
        assert "vector_dims(c.embedding_full) < :dims" in sql

    def test_gap_files_have_their_chunks_deleted_not_left_behind(self):
        """Leaving them is the silent-corruption option: mismatched widths
        either raise on <=> or vanish from ANN results."""
        import inspect

        from app.routers import files as files_router

        src = inspect.getsource(files_router.reindex_project)
        assert "Chunk.file_id.in_(restore_gap)" in src


class TestConversionNoteSurvivesReindex:
    """A re-index must not silently drop the conversion caveat.

    conversion_note describes how the MARKDOWN was produced ("audio used the
    free transcription endpoint - none of your keys support speech-to-text").
    The requeue loops used to clear it, which was harmless while every re-index
    re-converted and regenerated it. Once re-index started REUSING the stored
    markdown, clearing it deleted a caveat that was still true, and nothing
    regenerated it - the file came back looking like a clean transcription.
    """

    def test_reindex_requeue_preserves_the_note(self):
        import inspect

        from app.routers import files as files_router

        src = inspect.getsource(files_router.reindex_project)
        assert "conversion_note = None" not in src

    def test_upload_requeue_preserves_the_note(self):
        import inspect

        from app.routers import files as files_router

        src = inspect.getsource(files_router.upload_files)
        assert "conversion_note = None" not in src

    def test_ingest_still_rewrites_it_either_way(self):
        """Preserving is only safe because ingest_file sets it unconditionally:
        carried forward on the reuse path, replaced on a real conversion."""
        import inspect

        from app.services import ingestion

        src = inspect.getsource(ingestion.ingest_file)
        assert "file.conversion_note = converted.note" in src
        assert "note=file.conversion_note" in src

    def test_a_failed_file_still_drops_its_note(self):
        """The exception: a failed ingest's caveat describes work that did not
        finish, so it would only mislead."""
        import inspect

        from app.services import ingestion

        assert "conversion_note = None" in inspect.getsource(
            ingestion.mark_file_failed
        )


class TestArchiveColumnIsOmittedNotNulled:
    """The archive column must be ABSENT from the INSERT when unused.

    A key present in the row dict makes SQLAlchemy name that column in the
    INSERT. Carrying "embedding_full": None therefore referenced a column that
    does not exist until migration 0024 runs - breaking EVERY file upload on a
    database that had not had it applied, for projects that were not even
    shrunk. Omission is what keeps the statement identical to today's.
    """

    def test_insert_omits_the_key_when_not_archiving(self):
        import inspect

        from app.services import ingestion

        # CODE only. The comment above the fix quotes the bad literal in order
        # to explain it, so a naive substring check matches the explanation and
        # fails on correct code - a test that cannot tell code from prose.
        code = "\n".join(
            line
            for line in inspect.getsource(ingestion.ingest_file).splitlines()
            if not line.strip().startswith("#")
        )
        assert '"embedding_full": None' not in code
        assert '"embedding_full": vector if archiving else None' not in code
        # Added only under the archiving branch.
        assert "if archiving:" in code
        assert 'row["embedding_full"] = vector' in code

    def test_memory_save_never_writes_the_archive(self):
        """Memories are archived only by the SQL shrink, never at save time -
        so save_memory must not name the column either."""
        import inspect

        from app.services import memory

        assert "embedding_full" not in inspect.getsource(memory)
