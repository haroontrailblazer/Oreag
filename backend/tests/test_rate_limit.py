"""Rate limiter: fixed-window budgets, dual scope, 429 shape, fail-open."""
import uuid

import pytest
from fastapi import HTTPException

from app.services import rate_limit
from app.services.rate_limit import RateLimiter


class TestRateLimiter:
    def test_allows_up_to_the_limit_then_blocks(self):
        limiter = RateLimiter()
        for _ in range(3):
            allowed, _ = limiter.hit("b", limit=3)
            assert allowed
        allowed, retry_after = limiter.hit("b", limit=3)
        assert not allowed
        assert 1 <= retry_after <= 60

    def test_buckets_are_independent(self):
        limiter = RateLimiter()
        assert limiter.hit("key:a", limit=1)[0]
        assert not limiter.hit("key:a", limit=1)[0]
        assert limiter.hit("key:b", limit=1)[0]  # other bucket unaffected

    def test_redis_outage_fails_open(self):
        """A throttle must never become the outage."""

        class _DeadRedis:
            def pipeline(self):
                raise ConnectionError("redis down")

        limiter = RateLimiter()
        limiter._redis = _DeadRedis()
        allowed, retry_after = limiter.hit("b", limit=1)
        assert allowed and retry_after == 0


class TestEnforceRateLimit:
    def _fresh(self, monkeypatch):
        monkeypatch.setattr(rate_limit, "limiter", RateLimiter())

    def test_within_budget_passes(self, monkeypatch):
        self._fresh(monkeypatch)
        rate_limit.enforce_rate_limit(uuid.uuid4(), uuid.uuid4())  # no raise

    def test_key_budget_exhaustion_raises_429_with_retry_after(self, monkeypatch):
        self._fresh(monkeypatch)
        monkeypatch.setattr(
            rate_limit.settings, "query_rate_per_minute_per_key", 2
        )
        key_id, project_id = uuid.uuid4(), uuid.uuid4()
        rate_limit.enforce_rate_limit(key_id, project_id)
        rate_limit.enforce_rate_limit(key_id, project_id)
        with pytest.raises(HTTPException) as exc:
            rate_limit.enforce_rate_limit(key_id, project_id)
        assert exc.value.status_code == 429
        assert "Retry-After" in exc.value.headers

    def test_project_budget_is_shared_across_keys(self, monkeypatch):
        """A project's keys live in different apps - they must share one
        project budget or 10 keys mean 10x the intended traffic."""
        self._fresh(monkeypatch)
        monkeypatch.setattr(rate_limit.settings, "query_rate_per_minute_per_key", 100)
        monkeypatch.setattr(
            rate_limit.settings, "query_rate_per_minute_per_project", 2
        )
        project_id = uuid.uuid4()
        rate_limit.enforce_rate_limit(uuid.uuid4(), project_id)
        rate_limit.enforce_rate_limit(uuid.uuid4(), project_id)
        with pytest.raises(HTTPException) as exc:
            rate_limit.enforce_rate_limit(uuid.uuid4(), project_id)
        assert exc.value.status_code == 429

    def test_heavy_bucket_is_separate_and_smaller(self, monkeypatch):
        self._fresh(monkeypatch)
        monkeypatch.setattr(rate_limit.settings, "heavy_rate_per_minute_per_key", 1)
        key_id, project_id = uuid.uuid4(), uuid.uuid4()
        rate_limit.enforce_rate_limit(key_id, project_id, heavy=True)
        with pytest.raises(HTTPException):
            rate_limit.enforce_rate_limit(key_id, project_id, heavy=True)
        # the standard bucket for the same key is untouched
        rate_limit.enforce_rate_limit(key_id, project_id)

    def test_disabled_flag_bypasses_everything(self, monkeypatch):
        self._fresh(monkeypatch)
        monkeypatch.setattr(rate_limit.settings, "rate_limit_enabled", False)
        monkeypatch.setattr(rate_limit.settings, "query_rate_per_minute_per_key", 0)
        rate_limit.enforce_rate_limit(uuid.uuid4(), uuid.uuid4())  # no raise


class TestUsageRecording:
    def test_usage_write_failure_never_raises(self):
        from app.models import Project
        from app.services.usage import record_usage

        class _ExplodingDB:
            def add(self, obj):
                raise RuntimeError("db down")

            def rollback(self):
                pass

        project = Project(id=uuid.uuid4(), owner_id=uuid.uuid4())
        record_usage(
            _ExplodingDB(), project=project, api_key_id=None, endpoint="query"
        )  # must not raise
