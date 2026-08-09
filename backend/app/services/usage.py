"""Usage metering: one row per public /v1 request.

Previously the only usage record was a QueryLog row from /query - /retrieve,
/explore, /memory* and /memory-graph were invisible: unbillable, and an abuse
spike couldn't be attributed to a key. Every event carries owner/project/key
and the endpoint name; the /query paths additionally report tokens, cost and
cache savings. A column stays NULL unless a real measurement exists - NULL is
"not measured", 0 is a measurement.

Recording is strictly best-effort: metering must never fail a request.
"""
import logging
import uuid

from sqlalchemy.orm import Session

from ..models import Project, UsageEvent
from ..providers.base import TokenUsage
from ..providers.registry import cost_for

logger = logging.getLogger(__name__)


def record_usage(
    db: Session,
    *,
    project: Project,
    api_key_id: uuid.UUID | None,
    endpoint: str,
    latency_ms: int | None = None,
    usage: TokenUsage | None = None,
    cost_usd: float | None = None,
    saved: TokenUsage | None = None,
    cache_layer: str | None = None,
) -> None:
    """Write one UsageEvent. Never raises - metering must not fail a request.

    NULL discipline: every analytics column stays None unless a real
    measurement exists. A provider that reported nothing writes NULL token
    counts, not zeros - 0 is a real measurement (an empty completion), and
    conflating the two would make the billing table lie. Cost follows the same
    rule: ``cost_usd`` is taken as given, or derived via ``cost_for`` when a
    usage was measured, and stays NULL for unpriced models rather than
    guessing. ``saved`` is what a cache hit did NOT spend - the counts
    persisted with the cached answer when it was first computed, never an
    estimate.
    """
    try:
        prompt_tokens = completion_tokens = None
        model = None
        if usage is not None:
            prompt_tokens = usage.prompt_tokens
            completion_tokens = usage.completion_tokens
            model = usage.model or None
            if cost_usd is None:
                cost_usd = cost_for(usage.model, usage)
        db.add(
            UsageEvent(
                owner_id=project.owner_id,
                project_id=project.id,
                api_key_id=api_key_id,
                endpoint=endpoint,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model=model,
                cost_usd=cost_usd,
                saved_prompt_tokens=(
                    saved.prompt_tokens if saved is not None else None
                ),
                saved_completion_tokens=(
                    saved.completion_tokens if saved is not None else None
                ),
                cache_layer=cache_layer,
            )
        )
        db.commit()
    except Exception:
        logger.warning("Usage event write failed for %s", endpoint, exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
