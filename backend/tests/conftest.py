"""Shared test setup.

`.env` now carries a real REDIS_URL, which means importing app.services.query
builds Redis-backed cache/conversation stores. Unit tests must not depend on a
network Redis (slow, flaky offline, and it would pollute the live Upstash DB), so
this autouse fixture swaps the module-level stores for fresh in-memory ones. Each
test also gets its own backends, isolating cache/conversation state between tests.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_query_stores(monkeypatch):
    from app.services import query, query_cache

    cache_backend = query_cache.InMemoryBackend()
    conv_backend = query_cache.InMemoryBackend()
    monkeypatch.setattr(
        query,
        "_cache",
        query_cache.QueryCache(
            cache_backend,
            ttl_seconds=300,
            serialize=query._serialize_result,
            deserialize=query._deserialize_result,
        ),
    )
    monkeypatch.setattr(
        query,
        "_conversations",
        query_cache.ConversationStore(conv_backend, ttl_seconds=3600, max_turns=20),
    )
