import hashlib

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.auth.api_keys import KEY_PREFIX, generate_api_key, hash_key
from app.main import app
from app.providers.registry import (
    CATALOG,
    embedding_dimensions,
    get_embedder,
    validate_llm,
)
from app.schemas import ProjectCreate
from app.services.generation import build_user_prompt
from app.services.ingestion import parse_pdf


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


class TestParsePdf:
    def test_extracts_pages_with_text(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello Oreag, this is page one.")
        doc.new_page()  # blank page — should be skipped
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


class TestApiSurface:
    def test_healthz(self):
        client = TestClient(app)
        assert client.get("/healthz").json() == {"status": "ok"}

    def test_dashboard_routes_require_auth(self):
        client = TestClient(app)
        assert client.get("/api/projects").status_code == 401
        assert client.get("/api/models").status_code == 401

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
