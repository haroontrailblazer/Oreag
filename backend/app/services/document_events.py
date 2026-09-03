"""Append-only provenance for document editions: who, when, and what.

Migration 0034 made a `files` row an EDITION of a document, but recorded
nothing about the decisions taken over it. `files` has no `updated_at`, so a
supersession wrote `in_force_to` - a LEGAL date the user typed - and nothing
about when the decision was taken or by whom. "This edition governed until 22
Jan 2021" was recordable; "on 3 Sep 2026 this user recorded that" was not.

That missing transaction-time axis is why questions about proving what was in
force, approved or available on a date were unanswerable rather than answered
badly. This module is where they become answerable.

Two contracts, both deliberate:

* `record` DOES NOT COMMIT. The event lands in the caller's transaction, in the
  same commit as the decision it describes, so a rolled-back supersession
  cannot leave a record claiming it happened - and a recorded decision cannot
  go missing. Identical to `bump_content_version`'s contract, for the same
  reason.

* `record_safely` swallows everything. It exists for the worker paths, where an
  exception escaping into `_ingest_file_inner` aborts every queued ingest
  behind it. There, a missing informational event is strictly better than a
  stalled queue - so the DECISION events use `record` and the OBSERVATION
  events use `record_safely`.
"""
import logging
import uuid
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from ..models import DocumentEvent

logger = logging.getLogger(__name__)

# Mirrors the CHECK constraint in migration 0035. Kept here as well so a typo
# is a Python error at the call site rather than an IntegrityError that rolls
# back the user's operation.
EVENTS = frozenset({
    "uploaded",
    "indexed",
    "ingest_failed",
    "version_proposed",
    "parked_for_review",
    "version_confirmed",
    "version_rejected",
    "superseded",
    "reinstated",
    "detached",
    "deleted",
    "requeued",
})


def record(
    db: Session,
    project_id: uuid.UUID,
    event: str,
    *,
    file_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    **detail: Any,
) -> None:
    """Append one event. Commit is the caller's job.

    The insert is emitted directly rather than through the ORM so it cannot be
    caught up in a later flush of unrelated dirty objects, and so `detail` is
    written exactly as given.
    """
    if event not in EVENTS:
        raise ValueError(f"unknown document event {event!r}")
    db.execute(
        insert(DocumentEvent).values(
            project_id=project_id,
            file_id=file_id,
            document_id=document_id,
            event=event,
            actor_id=actor_id,
            # Values that are not JSON-native (uuid, date) are stringified at
            # the edge, so a detail payload can never fail the insert and take
            # the caller's transaction down with it.
            detail={k: _plain(v) for k, v in detail.items() if v is not None},
        )
    )


def record_safely(db: Session, project_id: uuid.UUID, event: str, **kwargs: Any) -> None:
    """`record`, but never raises. For worker paths only - see the module docstring."""
    try:
        record(db, project_id, event, **kwargs)
    except Exception:
        logger.warning("Could not record document event %s", event, exc_info=True)


def _plain(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def history(
    db: Session,
    project_id: uuid.UUID,
    *,
    document_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[DocumentEvent]:
    """A project's events, or one document's, newest first.

    Scoped by project_id FIRST in both shapes so the read cannot cross a tenant
    boundary even if a caller passes a document_id from elsewhere - document_id
    is not a foreign key and the database will not catch that for us.
    """
    stmt = select(DocumentEvent).where(DocumentEvent.project_id == project_id)
    if document_id is not None:
        stmt = stmt.where(DocumentEvent.document_id == document_id)
    return list(
        db.scalars(
            stmt.order_by(DocumentEvent.occurred_at.desc(), DocumentEvent.id.desc())
            .limit(limit)
        ).all()
    )
