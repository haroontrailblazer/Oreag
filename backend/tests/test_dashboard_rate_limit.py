"""Per-user rate limiting on the signed-in dashboard API.

The public /v1 surface has been throttled since Phase 2. /api/* had nothing -
and /api/* is where the LLM-calling endpoints live, so a stolen JWT or a
runaway retry loop could spend BYOK credit with no ceiling at all.

These tests pin the three properties that make the limiter worth having:
it counts per user, the expensive routes get their own smaller allowance, and
it fails OPEN so a counter-store outage can never become an app outage.
"""
import uuid

import pytest
from fastapi import HTTPException

from app.services import rate_limit


@pytest.fixture(autouse=True)
def _fresh_limiter(monkeypatch):
    """A private in-process limiter per test, so counts never leak between them."""
    monkeypatch.setattr(rate_limit, "limiter", rate_limit.RateLimiter(""))
    monkeypatch.setattr(rate_limit.settings, "rate_limit_enabled", True)
    yield


def _drain(user, limit, heavy=False):
    """Spend the whole budget. Returns the call number that first tripped."""
    for n in range(1, limit + 5):
        try:
            rate_limit.enforce_user_rate_limit(user, heavy=heavy)
        except HTTPException:
            return n
    return None


class TestPerUserBudget:
    def test_allows_up_to_the_limit_then_429s(self, monkeypatch):
        monkeypatch.setattr(
            rate_limit.settings, "dashboard_rate_per_minute_per_user", 5
        )
        assert _drain(uuid.uuid4(), 5) == 6

    def test_the_429_carries_retry_after(self, monkeypatch):
        monkeypatch.setattr(
            rate_limit.settings, "dashboard_rate_per_minute_per_user", 1
        )
        user = uuid.uuid4()
        rate_limit.enforce_user_rate_limit(user)
        with pytest.raises(HTTPException) as exc:
            rate_limit.enforce_user_rate_limit(user)
        assert exc.value.status_code == 429
        # Without this a client has no idea how long to back off, and retries
        # immediately - which is the behaviour the limit exists to stop.
        assert int(exc.value.headers["Retry-After"]) >= 1

    def test_users_do_not_share_a_bucket(self, monkeypatch):
        """One noisy account must never throttle everyone else."""
        monkeypatch.setattr(
            rate_limit.settings, "dashboard_rate_per_minute_per_user", 2
        )
        noisy = uuid.uuid4()
        _drain(noisy, 2)
        rate_limit.enforce_user_rate_limit(uuid.uuid4())  # must not raise

    def test_heavy_budget_is_separate_and_smaller(self, monkeypatch):
        """Cheap CRUD must not be able to exhaust the expensive allowance."""
        monkeypatch.setattr(
            rate_limit.settings, "dashboard_rate_per_minute_per_user", 50
        )
        monkeypatch.setattr(
            rate_limit.settings, "dashboard_heavy_rate_per_minute_per_user", 2
        )
        user = uuid.uuid4()
        for _ in range(20):
            rate_limit.enforce_user_rate_limit(user)  # standard traffic
        # The heavy allowance is untouched by that burst.
        rate_limit.enforce_user_rate_limit(user, heavy=True)
        rate_limit.enforce_user_rate_limit(user, heavy=True)
        with pytest.raises(HTTPException):
            rate_limit.enforce_user_rate_limit(user, heavy=True)

    def test_dashboard_and_api_key_buckets_are_distinct(self, monkeypatch):
        """A user's dashboard usage must not consume their API key's budget."""
        monkeypatch.setattr(
            rate_limit.settings, "dashboard_rate_per_minute_per_user", 1
        )
        monkeypatch.setattr(rate_limit.settings, "query_rate_per_minute_per_key", 1)
        shared = uuid.uuid4()
        rate_limit.enforce_user_rate_limit(shared)
        # Same id, different scope prefix - still has its own allowance.
        rate_limit.enforce_rate_limit(shared, uuid.uuid4())

    def test_kill_switch_disables_it(self, monkeypatch):
        monkeypatch.setattr(rate_limit.settings, "rate_limit_enabled", False)
        monkeypatch.setattr(
            rate_limit.settings, "dashboard_rate_per_minute_per_user", 1
        )
        user = uuid.uuid4()
        for _ in range(50):
            rate_limit.enforce_user_rate_limit(user)  # never raises


class TestFailsOpen:
    def test_a_broken_counter_store_lets_traffic_through(self, monkeypatch):
        """A throttle must never become the outage."""

        class Exploding:
            def pipeline(self):
                raise RuntimeError("redis is down")

        broken = rate_limit.RateLimiter("")
        broken._redis = Exploding()
        monkeypatch.setattr(rate_limit, "limiter", broken)
        monkeypatch.setattr(
            rate_limit.settings, "dashboard_rate_per_minute_per_user", 1
        )
        user = uuid.uuid4()
        for _ in range(10):
            rate_limit.enforce_user_rate_limit(user)  # must not raise
