"""Usage metering: one row per public /v1 request.

Previously the only usage record was a QueryLog row from /query - /retrieve,
/explore, /memory* and /memory-graph were invisible: unbillable, and an abuse
spike couldn't be attributed to a key. Every event carries owner/project/key
and the endpoint name; token columns stay NULL until providers report usage.

Recording is strictly best-effort: metering must never fail a request.
"""
import logging
import uuid

from sqlalchemy.orm import Session

from ..models import Project, UsageEvent

logger = logging.getLogger(__name__)


def record_usage(
    db: Session,
    *,
    project: Project,
    api_key_id: uuid.UUID | None,
    endpoint: str,
    latency_ms: int | None = None,
) -> None:
    try:
        db.add(
            UsageEvent(
                owner_id=project.owner_id,
                project_id=project.id,
                api_key_id=api_key_id,
                endpoint=endpoint,
                latency_ms=latency_ms,
            )
        )
        db.commit()
    except Exception:
        logger.warning("Usage event write failed for %s", endpoint, exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
