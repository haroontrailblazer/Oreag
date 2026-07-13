"""Cache-invalidation counter for a project's searchable content.

Both answer-cache layers (L1 exact + L2 semantic) key on
``projects.content_version``. Bumping it in the SAME transaction as any
chunk/memory write instantly orphans every cached answer built on the old
content - correct on in-place edits (where the old chunk_count:memory_count
signature stayed unchanged and served stale answers) and free at query time
(the version rides on the already-loaded Project row instead of two COUNT(*)
statements per request).
"""
import uuid

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..models import Project


def bump_content_version(db: Session, project_id: uuid.UUID) -> None:
    """Mark the project's content as changed. Commit is the caller's job -
    the bump must land atomically with the content write it invalidates."""
    db.execute(
        update(Project)
        .where(Project.id == project_id)
        .values(content_version=Project.content_version + 1)
    )
