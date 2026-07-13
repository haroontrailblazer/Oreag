"""Fixed-window rate limiting for the public /v1 API.

Before this, the ONLY throttle in the backend was the per-project upload rate:
any one of a project's API keys could issue unlimited /query or /explore
calls, and one busy integration could starve every other tenant. Budgets are
enforced at two scopes - per API key AND per project (a project's keys share
the project bucket) - with heavier endpoints (/explore, /memory-graph) on a
much smaller budget than /query.

Backed by Redis when REDIS_URL is set (shared across workers, atomic INCR);
otherwise a per-process counter. The limiter FAILS OPEN: if Redis is down the
request proceeds - a throttle must never become the outage.
"""
import logging
import threading
import time

from fastapi import HTTPException

from ..config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, redis_url: str = ""):
        self._redis = None
        if redis_url:
            import redis  # lazy - only required when actually configured

            self._redis = redis.from_url(
                redis_url,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
                retry_on_timeout=False,
                health_check_interval=30,
            )
        self._local: dict[str, int] = {}
        self._guard = threading.Lock()

    def hit(self, bucket: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        """Count one request against ``bucket``.

        Returns (allowed, retry_after_seconds). retry_after is the time left
        in the current window - what a well-behaved client should wait.
        """
        now = int(time.time())
        window = now - now % window_seconds
        key = f"rl:{bucket}:{window}"
        retry_after = window + window_seconds - now
        if self._redis is not None:
            try:
                pipe = self._redis.pipeline()
                pipe.incr(key)
                pipe.expire(key, window_seconds + 5)
                count = int(pipe.execute()[0])
                return count <= limit, retry_after
            except Exception:
                logger.warning("Rate limiter Redis unavailable - failing open")
                return True, 0
        with self._guard:
            if len(self._local) > 8192:
                # Windows rotate every minute; drop counters from closed ones.
                suffix = f":{window}"
                self._local = {
                    k: v for k, v in self._local.items() if k.endswith(suffix)
                }
            count = self._local.get(key, 0) + 1
            self._local[key] = count
        return count <= limit, retry_after


limiter = RateLimiter(settings.redis_url)


def enforce_rate_limit(api_key_id, project_id, heavy: bool = False) -> None:
    """Raise 429 (with Retry-After) when either the key's or the project's
    per-minute budget is spent. ``heavy`` selects the small budget used for
    the platform's most expensive endpoints (/explore, /memory-graph)."""
    if not settings.rate_limit_enabled:
        return
    kind = "heavy" if heavy else "std"
    if heavy:
        per_key = settings.heavy_rate_per_minute_per_key
        per_project = settings.heavy_rate_per_minute_per_project
    else:
        per_key = settings.query_rate_per_minute_per_key
        per_project = settings.query_rate_per_minute_per_project
    for bucket, limit in (
        (f"{kind}:key:{api_key_id}", per_key),
        (f"{kind}:proj:{project_id}", per_project),
    ):
        allowed, retry_after = limiter.hit(bucket, limit)
        if not allowed:
            raise HTTPException(
                429,
                "Rate limit exceeded - please slow down and retry.",
                headers={"Retry-After": str(max(retry_after, 1))},
            )
