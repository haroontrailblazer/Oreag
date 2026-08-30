import logging
import re
import uuid
from typing import NamedTuple
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Response, UploadFile
from fastapi import File as FastAPIFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy import update
from sqlalchemy.orm import Session

from .. import crypto
from ..config import settings
from ..db import get_db
from ..models import Chunk, File, Project
from ..providers import registry
from ..schemas import FileOut, FileVersionRequest, ReindexRequest
from ..services import storage
from ..services.content_version import bump_content_version
from ..services.usage import record_usage
from ..providers.base import TokenUsage
from ..services.conversion import content_type_for, is_ingestable, source_extension
from ..services.ingestion import recompute_project_status
from ..services.memory import reembed_project_memories
from .deps import ensure_valid_provider_key, get_owned_project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}", tags=["files"])

# Matryoshka shrink: cut to the prefix and re-normalize, entirely in SQL
# (pgvector 0.7+) - AND bank the wider original in the same statement so the
# shrink stays reversible (migration 0024).
#
# One statement, not two. SET expressions all read the row as it was BEFORE the
# update, so `embedding` on the right-hand side is still the pre-shrink vector:
# the archive is written from it and the truncation applied to it atomically,
# and there is no instant - not even inside the transaction - where the wider
# numbers exist nowhere.
#
# The CASE keeps the WIDEST vector ever held. On a repeated shrink
# (3072 -> 1536 -> 768) the second pass must NOT overwrite the 3072 archive with
# the 1536 intermediate, or growing back to 3072 would silently become
# impossible after a step the user thought was reversible.
_SHRINK_CHUNKS_SQL = sql_text(
    "UPDATE chunks SET "
    "  embedding_full = CASE "
    "    WHEN embedding_full IS NULL "
    "      OR vector_dims(embedding_full) < vector_dims(embedding) "
    "    THEN embedding ELSE embedding_full END, "
    "  embedding = l2_normalize(subvector(embedding, 1, :dims)) "
    "WHERE project_id = :project_id AND embedding IS NOT NULL "
    # Idempotent: a retry skips rows already at or below the target, so it
    # cannot re-archive a narrower vector over a wider one, and avoids pointless
    # MVCC churn and HNSW re-insertion on rows that are already correct.
    "  AND vector_dims(embedding) > :dims"
)
_SHRINK_MEMORIES_SQL = sql_text(
    "UPDATE memories SET "
    "  embedding_full = CASE "
    "    WHEN embedding_full IS NULL "
    "      OR vector_dims(embedding_full) < vector_dims(embedding) "
    "    THEN embedding ELSE embedding_full END, "
    "  embedding = l2_normalize(subvector(embedding, 1, :dims)) "
    "WHERE project_id = :project_id AND embedding IS NOT NULL "
    "  AND vector_dims(embedding) > :dims"
)
# memory_chunks (migration 0025) holds the split pieces of long memories, and
# they are searched exactly like the parents are - so every width migration that
# touches `memories` MUST touch these too. A piece left at the old width is not
# merely stale: pgvector RAISES when comparing mismatched widths, so memory
# search would fail outright rather than return fewer results.
_SHRINK_MEMORY_CHUNKS_SQL = sql_text(
    "UPDATE memory_chunks SET "
    "  embedding_full = CASE "
    "    WHEN embedding_full IS NULL "
    "      OR vector_dims(embedding_full) < vector_dims(embedding) "
    "    THEN embedding ELSE embedding_full END, "
    "  embedding = l2_normalize(subvector(embedding, 1, :dims)) "
    "WHERE project_id = :project_id AND embedding IS NOT NULL "
    "  AND vector_dims(embedding) > :dims"
)

# Grow: restore from the archive instead of re-embedding. Exact bytes back when
# the archive is the requested width; a prefix of it otherwise (768 -> 1536
# under a 3072 archive). Clearing the archive once it no longer holds anything
# above the active width returns storage to pre-shrink levels.
_RESTORE_CHUNKS_SQL = sql_text(
    "UPDATE chunks SET "
    "  embedding = CASE WHEN vector_dims(embedding_full) = :dims "
    "                   THEN embedding_full "
    "                   ELSE l2_normalize(subvector(embedding_full, 1, :dims)) END, "
    "  embedding_full = CASE WHEN vector_dims(embedding_full) <= :dims "
    "                        THEN NULL ELSE embedding_full END "
    "WHERE project_id = :project_id AND embedding_full IS NOT NULL "
    "  AND vector_dims(embedding_full) >= :dims"
)
_RESTORE_MEMORIES_SQL = sql_text(
    "UPDATE memories SET "
    "  embedding = CASE WHEN vector_dims(embedding_full) = :dims "
    "                   THEN embedding_full "
    "                   ELSE l2_normalize(subvector(embedding_full, 1, :dims)) END, "
    "  embedding_full = CASE WHEN vector_dims(embedding_full) <= :dims "
    "                        THEN NULL ELSE embedding_full END "
    "WHERE project_id = :project_id AND embedding_full IS NOT NULL "
    "  AND vector_dims(embedding_full) >= :dims"
)
_RESTORE_MEMORY_CHUNKS_SQL = sql_text(
    "UPDATE memory_chunks SET "
    "  embedding = CASE WHEN vector_dims(embedding_full) = :dims "
    "                   THEN embedding_full "
    "                   ELSE l2_normalize(subvector(embedding_full, 1, :dims)) END, "
    "  embedding_full = CASE WHEN vector_dims(embedding_full) <= :dims "
    "                        THEN NULL ELSE embedding_full END "
    "WHERE project_id = :project_id AND embedding_full IS NOT NULL "
    "  AND vector_dims(embedding_full) >= :dims"
)
# A piece the archive cannot reach is DELETED, not left at the wrong width. It
# is safe to delete because the parent memory still holds the full text and its
# own vector - the memory stays findable by gist, and the pieces are rebuilt on
# the next save or model switch. Leaving it would break search for the project.
_DROP_UNRESTORABLE_MEMORY_CHUNKS_SQL = sql_text(
    "DELETE FROM memory_chunks "
    "WHERE project_id = :project_id AND embedding IS NOT NULL "
    "  AND vector_dims(embedding) <> :dims"
)
# Rows the archive cannot reach - they must be re-embedded, so report them.
#
# JOINed to files on purpose. The result feeds a re-queue loop, so a file id
# that no longer exists would push a deleted file back into the ingest queue.
# chunks.file_id cascades on delete, so an orphan chunk cannot normally exist -
# but this statement and the later `SELECT File` are two statements under READ
# COMMITTED, and a delete landing between them would leave a live-looking id in
# a list built from the earlier snapshot. The JOIN makes the query itself
# incapable of returning one, instead of relying on every caller to intersect
# against the file list afterwards. _files_to_requeue still does intersect -
# defence in depth, since only one of the two can be forgotten in a refactor.
_UNRESTORABLE_CHUNK_FILES_SQL = sql_text(
    "SELECT DISTINCT c.file_id FROM chunks c "
    "JOIN files f ON f.id = c.file_id "
    "WHERE c.project_id = :project_id AND c.embedding IS NOT NULL "
    "  AND vector_dims(c.embedding) <> :dims "
    "  AND (c.embedding_full IS NULL OR vector_dims(c.embedding_full) < :dims)"
)

# Model switch: old-model memory vectors live in an incompatible space. They're
# nulled synchronously (search skips NULL) and re-embedded in the background.
#
# The ARCHIVE must be nulled with them, in the same statement. An archive minted
# under the previous model is a vector from a different space; leaving it behind
# would let a later grow "restore" it into the new model's space, producing
# embeddings that are silently meaningless rather than merely missing. This one
# clause is the whole difference between reversible and corrupting.
_CLEAR_MEMORY_EMBEDDINGS_SQL = sql_text(
    "UPDATE memories SET embedding = NULL, embedding_full = NULL "
    "WHERE project_id = :project_id"
)
# The split pieces are DELETED rather than nulled. Unlike a memory, a chunk row
# carries nothing but its text and its vector - it is pure derived data, rebuilt
# from the parent by reembed_project_memories. Nulling would leave rows that are
# useless until the background pass reaches them and permanently dead if it
# never does (no key on file), which is how an old-model piece survives to be
# scored against new-model queries.
_DROP_MEMORY_CHUNKS_SQL = sql_text(
    "DELETE FROM memory_chunks WHERE project_id = :project_id"
)


def _memory_chunks_supported(db: Session) -> bool:
    """Has migration 0025 been applied?

    Separate probe from _archive_supported, not folded into it: 0024 can be
    applied without 0025, and then every memory_chunks statement below would
    raise, roll back, and demote a free shrink to a paid re-embed - the exact
    regression _archive_supported exists to prevent. Same per-request,
    never-memoised rationale as that probe; see its docstring.
    """
    try:
        return bool(
            db.execute(
                sql_text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = 'memory_chunks'"
                )
            ).first()
        )
    except Exception:
        return False


def clear_memory_vectors(db: Session, project_id: uuid.UUID) -> None:
    """Drop every memory vector in a project, parents and split pieces alike.

    Called on an embedding MODEL switch, where the old vectors live in a space
    the new model cannot be compared against. The pieces must go with the
    parents: they are searched by the same query vector, so one left behind is
    not stale-but-harmless - it can outrank a correct result, and if its width
    differs it makes memory search RAISE instead of return.
    """
    params = {"project_id": str(project_id)}
    db.execute(_CLEAR_MEMORY_EMBEDDINGS_SQL, params)
    if _memory_chunks_supported(db):
        db.execute(_DROP_MEMORY_CHUNKS_SQL, params)


def _plan_embedding_change(
    project: Project,
    provider: str | None,
    model: str | None,
    dimensions: int | None,
) -> tuple[str, str, int, str]:
    """Resolve a requested embedding config against the project's current one.

    Returns (provider, model, dimensions, plan) where plan is "keep",
    "truncate" (same MRL model, smaller size - reuse vectors in place) or
    "reembed" (incompatible change - everything must be re-embedded).
    """
    provider = provider or project.embedding_provider
    model = model or project.embedding_model
    same_model = (provider, model) == (
        project.embedding_provider,
        project.embedding_model,
    )
    try:
        if dimensions is not None:
            dims = registry.resolve_embedding_dimensions(provider, model, dimensions)
        elif same_model:
            dims = project.embedding_dimensions
        else:
            dims = registry.embedding_dimensions(provider, model)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    plan = registry.embedding_change_plan(
        project.embedding_provider,
        project.embedding_model,
        project.embedding_dimensions,
        provider,
        model,
        dims,
    )
    return provider, model, dims, plan


_LEGACY_TRUNCATE_CHUNKS_SQL = sql_text(
    "UPDATE chunks SET embedding = l2_normalize(subvector(embedding, 1, :dims)) "
    "WHERE project_id = :project_id AND embedding IS NOT NULL "
    "  AND vector_dims(embedding) > :dims"
)
_LEGACY_TRUNCATE_MEMORIES_SQL = sql_text(
    "UPDATE memories SET embedding = l2_normalize(subvector(embedding, 1, :dims)) "
    "WHERE project_id = :project_id AND embedding IS NOT NULL "
    "  AND vector_dims(embedding) > :dims"
)
# Reachable only if 0025 were applied without 0024 - out of order, but the cost
# of covering it is one statement, and the cost of NOT covering it is a memory
# search that raises on every query for that project.
_LEGACY_TRUNCATE_MEMORY_CHUNKS_SQL = sql_text(
    "UPDATE memory_chunks SET "
    "  embedding = l2_normalize(subvector(embedding, 1, :dims)) "
    "WHERE project_id = :project_id AND embedding IS NOT NULL "
    "  AND vector_dims(embedding) > :dims"
)


def _archive_supported(db: Session) -> bool:
    """Has migration 0024 been applied?

    Scope: this guards COST, not availability. It exists so a shrink attempted
    without the archive columns keeps today's free in-place truncate instead of
    demoting to a paid re-embed. It does NOT make the code safe to deploy ahead
    of the migration - projects.embedding_native_dimensions is mapped
    non-deferred, so loading a Project already fails before anything reaches
    here. Migration 0024 is mandatory before deploy; see its header.

    Probed per request, NOT memoised. Memoising looks obviously right and is
    the trap: migrations are applied to the live database while old instances
    are still serving, so a process that cached "absent" at boot would keep
    shrinking destructively for its whole lifetime, minutes after the column
    appeared. One cheap catalog lookup is worth not having that failure mode.
    """
    try:
        return bool(
            db.execute(
                sql_text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'chunks' "
                    "  AND column_name = 'embedding_full'"
                )
            ).first()
        )
    except Exception:
        return False


def _shrink_vectors_in_place(db: Session, project: Project, dims: int) -> bool:
    """Cut chunk + memory vectors to the MRL prefix, banking the original.

    Returns False (after rolling back) when the database lacks pgvector 0.7+
    (subvector/l2_normalize), so callers can fall back to a full re-embed.
    Must run before other pending writes in the request - the rollback on
    failure discards everything uncommitted.

    WITHOUT migration 0024 this still shrinks, using the old destructive SQL.
    That degradation is deliberate and is the single most important safety
    property here: the archive columns do not exist yet, so referencing them
    would raise, roll back, and demote the whole operation to "reembed" -
    turning today's FREE instant shrink into a PAID re-embed purely because the
    code reached production before the SQL did. Shrinking without an archive is
    exactly today's behaviour; charging for it is a regression.
    """
    archived = _archive_supported(db)
    try:
        params = {"dims": dims, "project_id": str(project.id)}
        if archived:
            db.execute(_SHRINK_CHUNKS_SQL, params)
            db.execute(_SHRINK_MEMORIES_SQL, params)
        else:
            logger.warning(
                "Migration 0024 not applied - shrinking project %s destructively; "
                "growing back will need a re-embed",
                project.id,
            )
            db.execute(_LEGACY_TRUNCATE_CHUNKS_SQL, params)
            db.execute(_LEGACY_TRUNCATE_MEMORIES_SQL, params)
        # Shrunk in the same transaction as the parents, never left for a
        # background pass. The parents are at the new width the moment this
        # commits, and search scores both in one UNION - a piece still at the old
        # width would make that query RAISE on the very next memory lookup.
        if _memory_chunks_supported(db):
            db.execute(
                _SHRINK_MEMORY_CHUNKS_SQL
                if archived
                else _LEGACY_TRUNCATE_MEMORY_CHUNKS_SQL,
                params,
            )
        if archived:
            # Remember the width the vectors were originally computed at, so
            # ingestion keeps banking that width while the project stays shrunk.
            # COALESCE: a second shrink must not lower the remembered native.
            project.embedding_native_dimensions = max(
                project.embedding_native_dimensions or project.embedding_dimensions,
                project.embedding_dimensions,
            )
        return True
    except Exception:
        logger.exception(
            "In-place vector shrink failed for project %s; falling back to "
            "a full re-embed",
            project.id,
        )
        db.rollback()
        return False



def _record_restore_savings(
    db: Session, project: Project, files: list[File], restore_gap: list[uuid.UUID]
) -> None:
    """Report the embedding a Matryoshka grow-back did NOT have to buy.

    Restoring from `embedding_full` is the single largest avoided cost in the
    product on a big corpus, and it used to leave no trace whatsoever - a
    grow-back that rescued ten thousand chunks looked identical to one that did
    nothing.

    The figure is REPLAYED, never estimated: each restored file reports what it
    actually cost to embed at ingest (`files.embedding_tokens`). Files ingested
    before that column existed contribute nothing and their saving stays
    unmeasured, which is the honest answer - the same rule the answer cache
    follows. Files in the gap are excluded because they are about to be
    re-embedded and paid for.
    """
    gap = set(restore_gap)
    # A superseded version (migration 0034) keeps the embedding_tokens from its
    # original ingest but has no chunks to restore, and can never be in
    # restore_gap - the gap is computed FROM chunks. Leaving it in would report
    # a Matryoshka saving for embedding work that was never avoided.
    restored = [f for f in files if f.id not in gap and f.in_force_to is None]
    tokens = [f.embedding_tokens for f in restored if f.embedding_tokens is not None]
    if not tokens:
        return
    record_usage(
        db,
        project=project,
        api_key_id=None,
        endpoint="matryoshka_restore",
        saved_embedding=TokenUsage(
            prompt_tokens=sum(tokens),
            completion_tokens=0,
            model=project.embedding_model or "",
        ),
    )


def _lineage(file) -> uuid.UUID:
    """The document a file belongs to. NULL document_id means it is its own."""
    return file.document_id or file.id


class VersionOp(NamedTuple):
    file_id: uuid.UUID
    fields: dict  # attribute -> value to assign on the File row
    delete_chunks: bool


class SupersessionPlan(NamedTuple):
    ops: list[VersionOp]
    requeued: bool


def plan_supersession(target, predecessor, lineage, body) -> SupersessionPlan:
    """Every row write for one version decision, as data.

    PURE: takes anything with .id / .status / .chunk_count, so the semantics
    that actually matter - the predecessor loses its chunks AND its count in the
    same op, the successor is queued only when it needs to be - are asserted by
    unit tests rather than by an AST scan. CI has no database service, so this
    is the only shape that gets them under real test.
    """
    fields: dict = {
        "document_id": lineage,
        "version_label": body.version_label,
        "in_force_from": body.in_force_from,
        "legal_status": body.legal_status,
        "in_force_to": None,  # this row is the current one
    }
    # Queue it: a confirmed review file, or a historical version being brought
    # back into force. An already-indexed, already-current file having only its
    # metadata corrected is left alone - re-embedding it would be a bill for
    # nothing.
    requeued = target.chunk_count == 0 or target.status != "indexed"
    if requeued:
        fields.update(
            status="pending",
            error=None,
            conversion_error=None,
            attempts=0,  # claim_next burned one parking it; refund it
            chunk_count=0,
        )
        # conversion_note is NOT cleared: it describes how the MARKDOWN was
        # produced and the re-index REUSES that markdown, so the caveat is
        # still true. Same reasoning as the upload requeue.
    ops = [VersionOp(target.id, fields, delete_chunks=False)]
    if predecessor is not None:
        ops.append(VersionOp(
            predecessor.id,
            {
                # Half-open: the successor's start date IS the predecessor's end
                # date, so one date serves both rows and they cannot disagree.
                # No date arithmetic anywhere.
                "in_force_to": body.in_force_from,
                # MUST be zeroed in the same transaction as the delete.
                # retrieval._PROJECT_CHUNKS_SQL sums files.chunk_count to feed
                # the ANN gate; a superseded row keeping its old count inflates
                # both the absolute vector_ann_min_chunks check and the
                # owned/total share, opening the HNSW path for a project whose
                # real chunk count is below both.
                "chunk_count": 0,
                "lease_expires_at": None,
            },
            delete_chunks=True,
        ))
    return SupersessionPlan(ops, requeued)


def _files_to_requeue(files: list[File], restore_gap: list[uuid.UUID]) -> list[File]:
    """Which files must be re-embedded after a vector migration.

    An EMPTY gap means this is not a partial restore at all - a model switch or
    a chunking change - so every file is re-ingested, which is the historical
    behaviour and must not narrow.

    A NON-EMPTY gap means the archive covered most of the project but not these
    files: they were ingested before the archive existed, or by an older build.
    Only they are re-embedded. Everything else keeps the vectors it just got
    back for free, which is the entire point of the archive - re-embedding the
    whole corpus because one file could not be restored would hand back the
    bill this feature exists to avoid.

    File granularity, never chunk granularity: a file's chunks are re-derived
    together from its markdown, so half of one cannot be re-ingested in
    isolation.
    """
    # Superseded versions are excluded before EITHER branch. The empty-gap
    # branch above "must not narrow" - this is the one exception, and it is not
    # a narrowing of intent: a superseded version is REQUIRED to hold zero
    # chunks (migration 0034), so re-embedding it would put a retired edition
    # of a document back into the live index. Keyed on in_force_to, never on
    # status: a superseded file can also be 'failed'.
    files = [f for f in files if f.in_force_to is None]
    if not restore_gap:
        return list(files)
    gap = set(restore_gap)
    return [f for f in files if f.id in gap]


def _restore_vectors_from_archive(
    db: Session, project: Project, dims: int
) -> list[uuid.UUID] | None:
    """Grow vectors back from the archive instead of re-embedding.

    Returns the file ids that could NOT be restored (their chunks must be
    re-embedded), or None when the restore itself failed and the caller should
    fall back to a full re-embed. An empty list means everything was restored
    and no API call is needed at all.

    Same first-write contract as the shrink: it rolls back on failure, so any
    write made before it would be discarded.
    """
    if not _archive_supported(db):
        return None
    try:
        params = {"dims": dims, "project_id": str(project.id)}
        # Read the gap BEFORE restoring - afterwards the restored rows are at
        # the target width and would no longer look unrestorable.
        gap = [
            row[0]
            for row in db.execute(_UNRESTORABLE_CHUNK_FILES_SQL, params).all()
        ]
        db.execute(_RESTORE_CHUNKS_SQL, params)
        db.execute(_RESTORE_MEMORIES_SQL, params)
        # Memories the archive could not reach are nulled rather than left at the
        # wrong width: retrieval compares vectors with <=>, which RAISES on a
        # width mismatch, so a stale-width row would break search outright
        # rather than merely be missing. NULL is skipped by search and refilled
        # by the background re-embed.
        db.execute(
            sql_text(
                "UPDATE memories SET embedding = NULL, embedding_full = NULL "
                "WHERE project_id = :project_id AND embedding IS NOT NULL "
                "  AND vector_dims(embedding) <> :dims"
            ),
            params,
        )
        if _memory_chunks_supported(db):
            db.execute(_RESTORE_MEMORY_CHUNKS_SQL, params)
            db.execute(_DROP_UNRESTORABLE_MEMORY_CHUNKS_SQL, params)
        return gap
    except Exception:
        logger.exception(
            "Archive restore failed for project %s; falling back to a full "
            "re-embed",
            project.id,
        )
        db.rollback()
        return None


@router.get("/files", response_model=list[FileOut])
def list_files(
    project: Project = Depends(get_owned_project), db: Session = Depends(get_db)
):
    return db.scalars(
        select(File).where(File.project_id == project.id).order_by(File.created_at)
    ).all()


@router.post("/files", response_model=list[FileOut], status_code=201)
async def upload_files(
    background_tasks: BackgroundTasks,
    uploads: list[UploadFile] = FastAPIFile(...),
    chunk_size: int | None = Form(None),
    chunk_overlap: int | None = Form(None),
    top_k: int | None = Form(None),
    embedding_provider: str | None = Form(None),
    embedding_model: str | None = Form(None),
    embedding_dimensions: int | None = Form(None),
    embedding_api_key: str | None = Form(None),
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    # validate the per-file chunking overrides (null = use project defaults)
    if chunk_size is not None and not (100 <= chunk_size <= 8000):
        raise HTTPException(422, "chunk_size must be between 100 and 8000")
    if chunk_overlap is not None and chunk_overlap < 0:
        raise HTTPException(422, "chunk_overlap must be >= 0")
    effective_size = chunk_size if chunk_size is not None else project.chunk_size
    if chunk_overlap is not None and chunk_overlap >= effective_size:
        raise HTTPException(422, "chunk_overlap must be smaller than chunk_size")

    # Up here with the other input validation, not down beside apply_override:
    # a key the provider rejects must stop the request before the embedding
    # columns move or a single file reaches storage.
    ensure_valid_provider_key(
        embedding_provider or project.embedding_provider, embedding_api_key
    )

    # embedding config is project-wide (uniform vector dimension). A model
    # switch re-embeds every existing file (and memories); shrinking the same
    # Matryoshka model's dimensions truncates stored vectors in place instead.
    reindex_existing = False
    memories_need_backfill = False
    if embedding_provider or embedding_model or embedding_dimensions is not None:
        provider, model, dims, plan = _plan_embedding_change(
            project, embedding_provider, embedding_model, embedding_dimensions
        )
        # Both vector migrations must be this request's FIRST write (see the
        # helper docstrings): each rolls back on failure and would discard
        # anything written before it.
        if plan == "truncate" and not _shrink_vectors_in_place(db, project, dims):
            plan = "reembed"
        elif plan == "restore":
            # Growing back on the same MRL model. This branch did not exist,
            # and its absence was silent CORRUPTION rather than a missing
            # feature: the code fell through to set project.embedding_dimensions
            # to the new width while every stored vector kept the old one, and
            # pgvector RAISES on a width mismatch - so document search AND
            # memory search 500 on every subsequent request, with no path back
            # through the UI (a later reindex at the same value plans "keep").
            #
            # Anything short of a COMPLETE restore is demoted to a full
            # re-embed. Unlike the reindex route this endpoint has no
            # partial-requeue machinery, and a partial restore that left some
            # rows at the old width would break search outright rather than
            # degrade it. Paying for a re-embed in the rare partial case is the
            # cheap side of that trade; the settings route still does the
            # free partial restore.
            gap = _restore_vectors_from_archive(db, project, dims)
            if gap is None or gap:
                plan = "reembed"
            elif dims >= (project.embedding_native_dimensions or dims):
                # Back at full fidelity - the restore SQL emptied the archive,
                # so stop treating the project as shrunk. Without this the
                # project keeps banking a "wide original" that is the same width
                # as the active one, and reindex_project's matching branch made
                # the two endpoints disagree about the project's own state.
                project.embedding_native_dimensions = None
        if plan in ("truncate", "restore"):
            # A successful migration rewrote every existing vector, so the
            # cache signature has to move even though nothing is re-ingested.
            # Bumped HERE rather than relying on the uploaded files bumping it
            # during ingestion: that happens to work today, but it makes a
            # correctness invariant depend on a side effect of an unrelated
            # step, and it fails outright if every uploaded file errors out.
            bump_content_version(db, project.id)
        project.embedding_provider = provider
        project.embedding_model = model
        project.embedding_dimensions = dims
        if plan == "reembed":
            # See reindex_project: a native width recorded under the OLD model
            # names a vector space this path is about to destroy, and the next
            # write would ask the new model for a width it may reject.
            project.embedding_native_dimensions = None
        reindex_existing = plan == "reembed"
        # A completed restore ALSO needs the memory pass, and reindex_existing
        # only covers "reembed". The restore nulls any memory the archive could
        # not reach and drops its pieces; without this that memory is left
        # permanently unsearchable on this route, which is the same defect the
        # reindex route was just fixed for.
        memories_need_backfill = plan == "restore"

    # top_k is a project/query setting
    if top_k is not None:
        if not (1 <= top_k <= 20):
            raise HTTPException(422, "top_k must be between 1 and 20")
        project.top_k = top_k

    pair = crypto.apply_override(embedding_api_key)
    if pair is not None:
        project.embedding_key_encrypted, project.embedding_key_last4 = pair

    # Validate EVERY file before uploading ANY to storage - a mid-batch
    # rejection then can't strand already-uploaded objects (see public route).
    validated: list[tuple[str, bytes, str, str]] = []
    for upload in uploads:
        filename = upload.filename or "upload"
        # Size cap BEFORE buffering/decoding - see the public route for why.
        if upload.size is not None and upload.size > settings.max_upload_bytes:
            raise HTTPException(
                413,
                f"{filename} exceeds the "
                f"{settings.max_upload_bytes // (1024 * 1024)} MB limit",
            )
        data = await upload.read()
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(
                413,
                f"{filename} exceeds the "
                f"{settings.max_upload_bytes // (1024 * 1024)} MB limit",
            )
        if not is_ingestable(filename, data):
            raise HTTPException(
                400, f"Unsupported file type: {filename} (no text could be extracted)"
            )
        validated.append(
            (
                filename,
                data,
                source_extension(filename),
                content_type_for(filename, upload.content_type),
            )
        )

    created: list[File] = []
    for filename, data, extension, content_type in validated:
        file_id = uuid.uuid4()
        path = f"{project.owner_id}/{project.id}/{file_id}{extension}"
        # Sync storage PUT off the event loop - this handler is async.
        await run_in_threadpool(storage.upload_file, path, data, content_type)
        record = File(
            id=file_id,
            project_id=project.id,
            filename=filename,
            storage_path=path,
            content_type=content_type,
            source_extension=extension,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            size_bytes=len(data),
        )
        db.add(record)
        created.append(record)

    # a new embedding model means every existing file (and every memory) must
    # be re-embedded - the old vectors live in an incompatible space
    if reindex_existing:
        new_ids = {record.id for record in created}
        db.execute(sql_delete(Chunk).where(Chunk.project_id == project.id))
        clear_memory_vectors(db, project.id)
        bump_content_version(db, project.id)
        # A set-based UPDATE, not a loop over a pre-loaded list. Under READ
        # COMMITTED the SELECT could read a row as current, block on a concurrent
        # confirm's row lock, and then write status='pending' onto a row that
        # was superseded in between; an UPDATE re-evaluates its predicate
        # against the row it actually locks. synchronize_session stays at its
        # default so the in-session File objects are refreshed.
        db.execute(
            update(File)
            .where(
                File.project_id == project.id,
                File.id.notin_(new_ids),
                # Superseded versions must never come back into the index, and
                # an unconfirmed review must never be chunked ahead of the
                # human. Keyed on in_force_to, NEVER on status - a superseded
                # file can also be 'failed' - and never on
                # projects.version_tracking: switching the toggle off must not
                # resurrect editions that were already retired.
                File.in_force_to.is_(None),
                File.status != "review",
            )
            .values(
                status="pending",
                chunk_count=0,
                error=None,
                conversion_error=None,
                # conversion_note is NOT cleared. It describes how the MARKDOWN
                # was produced ("audio used the free fallback endpoint"), and a
                # re-index now REUSES that markdown, so clearing it would drop a
                # caveat that is still true. ingest_file rewrites it either way:
                # the reuse path carries it forward, a real re-conversion
                # replaces it with a fresh one.
                attempts=0,  # fresh retry budget for the re-ingest
            )
        )

    project.status = "indexing"
    db.commit()

    # Memories re-embed as a background task (quick); files sit in
    # status='pending' for the durable queue workers - no in-process queue to
    # lose on a restart.
    if reindex_existing:
        background_tasks.add_task(reembed_project_memories, project.id)
    elif memories_need_backfill:
        background_tasks.add_task(
            reembed_project_memories, project.id, only_missing=True
        )
    return created


@router.delete("/files/{file_id}", status_code=204)
def delete_file(
    file_id: uuid.UUID,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    file = db.get(File, file_id)
    if file is None or file.project_id != project.id:
        raise HTTPException(404, "File not found")
    paths = [file.storage_path]
    if file.markdown_storage_path:
        paths.append(file.markdown_storage_path)
    db.delete(file)  # cascades to its chunks
    bump_content_version(db, project.id)
    recompute_project_status(db, project)
    db.commit()
    # Best-effort, and deliberately so: the row is already gone when this runs,
    # so a raising storage.delete would return 500 for a delete that HAS
    # succeeded, and the client's retry would 404. Orphaned blobs are a
    # janitorial problem; a 500 on a completed destructive operation is a
    # correctness one. Migration 0034 multiplies the number of two-blob files,
    # which is what makes the bare call worth fixing now.
    try:
        storage.delete(paths)
    except Exception:
        logger.exception(
            "Storage cleanup failed for deleted file %s (orphaned: %s)",
            file_id,
            paths,
        )


def _project_files(db: Session, project: Project) -> list[File]:
    return db.scalars(
        select(File).where(File.project_id == project.id).order_by(File.created_at)
    ).all()


@router.post("/files/{file_id}/version", response_model=list[FileOut])
def set_file_version(
    file_id: uuid.UUID,
    body: FileVersionRequest,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    """Record one version decision. The only way in or out of 'review'.

    Four operations, one verb:
      * confirm a review    - document_id = the matched lineage, supersede_file_id = its current file
      * reject a review     - document_id = null, supersede_file_id = null
      * retire by hand      - document_id = the old file's lineage, supersede_file_id = the old file
      * reinstate history   - called ON the historical file, superseding the current one

    ONE transaction, ONE commit, and ZERO storage calls. The successor's
    metadata, the predecessor's in_force_to, the chunk DELETE, chunk_count = 0,
    the requeue, the content_version bump and project.status land atomically or
    not at all - so "the commit succeeded" and "the operation succeeded" are the
    same statement, which is the property delete_file cannot have.

    Deliberately reachable with projects.version_tracking off: the toggle gates
    the automatic proposal, not the ability to repair a lineage afterwards.
    """
    # -- 0. LOCK BOTH ROWS IN ONE ID-ORDERED STATEMENT --------------------
    # Ordering by File.id IN SQL is what makes deadlock impossible however many
    # confirms run concurrently, and the lock is what makes the checks below
    # true at COMMIT time rather than at read time. claim_next uses
    # with_for_update(skip_locked=True), so a worker also skips these rows for
    # the length of this transaction.
    ids = {file_id}
    if body.supersede_file_id is not None:
        ids.add(body.supersede_file_id)
    locked = db.scalars(
        select(File)
        .where(File.id.in_(ids), File.project_id == project.id)
        .order_by(File.id)
        .with_for_update()
    ).all()
    by_id = {f.id: f for f in locked}
    target = by_id.get(file_id)
    if target is None:
        raise HTTPException(404, "File not found")
    predecessor = (
        by_id.get(body.supersede_file_id)
        if body.supersede_file_id is not None
        else None
    )
    if body.supersede_file_id is not None:
        if predecessor is None:
            raise HTTPException(404, "Superseded file not found")
        if predecessor.id == target.id:
            raise HTTPException(422, "A file cannot supersede itself")

    # -- 1. IDEMPOTENCY, BEFORE ANY WRITE ---------------------------------
    # The retry-after-timeout case is the common one, and a 409 there would show
    # a user an error for an operation that already succeeded.
    if (
        target.status != "review"
        and target.in_force_to is None
        and target.document_id == _lineage(predecessor or target)
        and target.version_label == body.version_label
        and target.in_force_from == body.in_force_from
        and target.legal_status == body.legal_status
        and (predecessor is None or predecessor.in_force_to == body.in_force_from)
    ):
        return _project_files(db, project)

    # -- 2. VALIDATE, all against the LOCKED rows -------------------------
    if target.status == "processing":
        # Its ingest is mid-flight and would overwrite status and chunk_count
        # from under this transaction.
        raise HTTPException(409, "File is being processed - try again shortly")

    if predecessor is not None:
        if predecessor.status in ("pending", "processing"):
            # A pending row is claimable by claim_next and this row lock only
            # holds for this transaction, so superseding it would leave a
            # retired version queued for indexing. There is no honest status to
            # move it to, so refuse.
            raise HTTPException(
                409,
                "The version being replaced is queued for indexing - wait for "
                "it to finish, then supersede it.",
            )
        if predecessor.in_force_to is not None:
            raise HTTPException(
                422, "That version is already superseded - replace the one in force"
            )
        if body.in_force_from is None:
            # in_force_to is the ONLY thing keeping a superseded version out of
            # the index, so it must never be null on a supersession - and it is
            # DERIVED, never fabricated, so a missing date is a 422 rather than
            # date.today(). One invented end date corrupts the whole timeline.
            raise HTTPException(
                422, "in_force_from is required when superseding a version"
            )
        if (
            predecessor.in_force_from is not None
            and body.in_force_from < predecessor.in_force_from
        ):
            # Turns a CHECK violation (a 500) into a 422.
            raise HTTPException(
                422,
                "in_force_from is earlier than the version it replaces "
                f"({predecessor.in_force_from.isoformat()})",
            )
        lineage = _lineage(predecessor)
        if body.document_id is not None and body.document_id != lineage:
            raise HTTPException(422, "document_id does not match the superseded file")
    else:
        lineage = body.document_id or target.id

    # At most one current version per lineage. There is no unique constraint on
    # `files` (there is none of any kind) and the key is a coalesce, so this is
    # the invariant's only keeper. Scanned over the project's file list, which
    # is capped at 1000 rows.
    siblings = _project_files(db, project)
    if (
        body.document_id is not None
        and predecessor is None
        and not any(_lineage(f) == body.document_id for f in siblings)
    ):
        raise HTTPException(422, "document_id names no document in this project")
    clash = next(
        (
            f
            for f in siblings
            if f.id != target.id
            and (predecessor is None or f.id != predecessor.id)
            and f.in_force_to is None
            and f.status != "review"
            and _lineage(f) == lineage
        ),
        None,
    )
    if clash is not None:
        raise HTTPException(
            422,
            f"{clash.filename} is already the current version of this document - "
            "name it as the version being superseded",
        )

    # -- 3. WRITES. One transaction, one commit, ZERO storage calls -------
    plan = plan_supersession(target, predecessor, lineage, body)
    for op in plan.ops:
        row = by_id[op.file_id]
        if op.delete_chunks:
            db.execute(sql_delete(Chunk).where(Chunk.file_id == op.file_id))
        for name, value in op.fields.items():
            setattr(row, name, value)
        # Blobs are NOT touched: storage_path, markdown_storage_path,
        # conversion_version, page_count, size_bytes, embedding_tokens and
        # indexed_at all survive, which is what makes history downloadable and
        # re-indexable later without re-upload, at embedding cost only.

    # -- 4. INVALIDATE AND SETTLE, in delete_file's proven order ----------
    # Unconditional, and NOT the pin/unpin non-bump reasoning in routers/
    # memory.py: pin/unpin reorders content that still exists, whereas a
    # supersession REMOVES text from the corpus, and re-serving a cached answer
    # built on repealed law is the exact harm this feature exists to prevent.
    bump_content_version(db, project.id)
    recompute_project_status(db, project)
    db.commit()
    return _project_files(db, project)


@router.get("/files/{file_id}/content")
async def download_file_content(
    file_id: uuid.UUID,
    format: str = "source",
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    """Download a file's original bytes or its converted markdown.

    The only way to read a superseded version. Without it, keeping those blobs
    forever buys nothing - they would be unreachable, unbilled-for storage.

    Streams through the API rather than handing out a Supabase signed URL:
    storage.download already exists and is used verbatim, whereas a signed URL
    adds a storage helper, an expiry policy and a second auth model for
    bandwidth on an operation measured in dozens per project per year. The
    threadpool hop is REQUIRED - storage.download blocks, and this route shares
    its worker with every streaming query.
    """
    file = db.get(File, file_id)
    if file is None or file.project_id != project.id:
        raise HTTPException(404, "File not found")
    if format not in ("source", "markdown"):
        raise HTTPException(422, "format must be 'source' or 'markdown'")
    if format == "markdown":
        path = file.markdown_storage_path
        if not path:
            raise HTTPException(404, "This file has no converted markdown")
        media, name = "text/markdown; charset=utf-8", f"{file.filename}.md"
    else:
        path = file.storage_path
        media = file.content_type or "application/octet-stream"
        name = file.filename
    try:
        data = await run_in_threadpool(storage.download, path)
    except Exception:
        logger.warning("Storage read failed for file %s", file_id, exc_info=True)
        raise HTTPException(502, "The stored file could not be read")
    # Filenames are user-supplied and stored verbatim, so they routinely carry
    # CJK, Cyrillic or emoji. Starlette latin-1 encodes header values, so a bare
    # `filename="..."` would raise UnicodeEncodeError and 500 the download.
    # RFC 6266: an ASCII-only `filename` for old clients plus a percent-encoded
    # `filename*` that every current browser prefers.
    stripped = re.sub(r'[\r\n"]', "", name)[:200]
    ascii_name = stripped.encode("ascii", "replace").decode("ascii") or "download"
    quoted = quote(stripped, safe="")
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quoted}'
            )
        },
    )


@router.post("/files/{file_id}/retry", response_model=FileOut)
def retry_file(
    file_id: uuid.UUID,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    file = db.get(File, file_id)
    if file is None or file.project_id != project.id:
        raise HTTPException(404, "File not found")
    # The requeue is a set-based UPDATE re-stating every guard, for the same
    # reason the other two requeue sites are (files.py, upload and reindex): the
    # read above takes no row lock, so a confirm can supersede this file between
    # the check and the flush - and a write keyed on `id` alone would then land
    # on a superseded row and put a retired edition into the durable queue.
    # Re-stating the predicate makes that interleave match zero rows instead.
    updated = db.execute(
        update(File)
        .where(
            File.id == file_id,
            File.in_force_to.is_(None),
            File.status.notin_(("processing", "review")),
        )
        .values(
            status="pending",  # the queue workers pick it up from here
            error=None,
            conversion_error=None,
            conversion_note=None,
            attempts=0,  # a manual retry gets a fresh budget
        )
    ).rowcount
    if not updated:
        # Re-read to name the actual reason: the pre-lock state may be stale.
        db.rollback()
        file = db.get(File, file_id)
        if file is None:
            raise HTTPException(404, "File not found")
        if file.status == "processing":
            raise HTTPException(409, "File is already being processed")
        if file.status == "review":
            raise HTTPException(
                409,
                "This file is waiting for a version decision - confirm or reject "
                "it in the Files tab before re-indexing.",
            )
        raise HTTPException(
            409,
            "This is a superseded version. Re-indexing it would put two versions "
            "of the same document in the index; make it current instead.",
        )
    project.status = "indexing"
    db.commit()
    db.refresh(file)
    return file


@router.post("/reindex", response_model=list[FileOut])
def reindex_project(
    body: ReindexRequest,
    background_tasks: BackgroundTasks,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    """Update memory: apply new chunking/embedding config and re-ingest everything.

    Vector migration depends on what changed:
      * same Matryoshka model at a smaller size + unchanged chunking -> the
        stored vectors are truncated in place (instant, no re-embedding);
      * a different model (or a larger size) -> chunks are wiped and every file
        re-ingested, and memory embeddings are nulled then re-embedded with the
        new model in the background;
      * otherwise -> the classic full re-ingest.
    """
    # validate chunking up front - nothing below may run on invalid input
    effective_size = (
        body.chunk_size if body.chunk_size is not None else project.chunk_size
    )
    effective_overlap = (
        body.chunk_overlap if body.chunk_overlap is not None else project.chunk_overlap
    )
    if effective_overlap >= effective_size:
        raise HTTPException(422, "chunk_overlap must be smaller than chunk_size")
    chunking_changed = (
        effective_size != project.chunk_size
        or effective_overlap != project.chunk_overlap
    )

    # Before _truncate_vectors_in_place, which is the request's first write.
    # A key rejected after that point would 422 having already rewritten every
    # vector in the project - and re-embedding the whole corpus with a key that
    # cannot authenticate is precisely the expensive failure this check exists
    # to prevent.
    ensure_valid_provider_key(
        body.embedding_provider or project.embedding_provider,
        body.embedding_api_key,
    )

    provider, model, dims, plan = _plan_embedding_change(
        project, body.embedding_provider, body.embedding_model, body.embedding_dimensions
    )
    # Both vector migrations must be the request's FIRST write (see helper
    # docstrings): each rolls back on failure and would discard anything
    # written before it.
    restore_gap: list[uuid.UUID] = []
    if plan == "truncate" and not _shrink_vectors_in_place(db, project, dims):
        plan = "reembed"
    elif plan == "restore":
        gap = _restore_vectors_from_archive(db, project, dims)
        if gap is None:
            # No archive columns, or the restore itself failed - growing has to
            # be paid for after all.
            plan = "reembed"
        elif gap:
            # Some files pre-date the archive (shrunk before 0024, or ingested
            # by an older build). Restore what we can and re-embed only those
            # files, rather than charging for the whole corpus.
            restore_gap = gap
        # A fully restored project keeps plan == "restore" and re-embeds nothing.

    project.embedding_provider = provider
    project.embedding_model = model
    project.embedding_dimensions = dims
    if plan == "reembed":
        # The archive is being destroyed on this path (chunks deleted, memory
        # vectors nulled), so a "native width" recorded under the OLD model
        # points at a vector space that no longer exists. Left set, the next
        # write asks the NEW model for a width it may not support - which raises
        # inside get_embedder and is swallowed into "no embedding" for every
        # memory and every file. usable_native_dimensions() also guards that,
        # but the marker is simply wrong here and clearing it is the honest fix.
        project.embedding_native_dimensions = None

    # Memory re-embed is queued HERE, before the fast path below can return.
    #
    # It used to sit at the end of the function, after that return - so for the
    # one case it was written for (a complete restore with unchanged chunking,
    # which IS the fast path's predicate) it never ran, while its comment
    # asserted it did. Registration order does not matter: FastAPI runs
    # background tasks only after a successful response.
    if plan == "reembed":
        background_tasks.add_task(reembed_project_memories, project.id)
    elif plan == "restore":
        # EVERY restore, not just one with a non-empty file gap. restore_gap is
        # computed from CHUNKS joined to FILES and says nothing about memories:
        # a memory written while shrunk by a build that did not bank an archive
        # has its vector nulled and its pieces dropped by the restore, and if
        # every FILE restored cleanly the gap is empty.
        #
        # only_missing keeps this close to free when there is nothing to fix -
        # it touches only the rows the restore could not reach.
        background_tasks.add_task(
            reembed_project_memories, project.id, only_missing=True
        )

    pair = crypto.apply_override(body.embedding_api_key)
    if pair is not None:
        project.embedding_key_encrypted, project.embedding_key_last4 = pair
    project.chunk_size = effective_size
    project.chunk_overlap = effective_overlap

    # Locked, and locked BEFORE any chunk is deleted below. set_file_version
    # takes its `files` lock first and only then deletes that file's chunks; a
    # reindex that deleted chunks first and locked files afterwards would invert
    # that order and let the two deadlock. Ordering by id keeps concurrent
    # reindexes on the same project deadlock-free with each other too.
    files = db.scalars(
        select(File)
        .where(File.project_id == project.id)
        .order_by(File.id)
        .with_for_update()
    ).all()

    # Matryoshka fast path: vectors already migrated in place, chunks still
    # valid - nothing to re-ingest.
    #
    # It still has to bump content_version. "No re-ingest" is not "no change":
    # _truncate_vectors_in_place has just rewritten EVERY vector in the project
    # to a new width and re-normalised it, so anything keyed on the old
    # signature is now describing a vector space that no longer exists.
    # content_version is exactly that signature - it keys the memory-graph
    # response cache (services/memory_graph.py) and the answer caches
    # (services/query.py). Without the bump, the Visualize tab kept serving the
    # graph built from the pre-shrink vectors, and queries kept returning
    # answers computed against them, with nothing on screen to suggest the
    # shrink had not taken effect.
    #
    # AFTER the vector migration, never before: it rolls back on failure and
    # would discard a bump made ahead of it.
    if plan in ("truncate", "restore") and not chunking_changed and not restore_gap:
        # Growing back from the archive lands here too: every vector is already
        # at the new width, so there is nothing to re-ingest and nothing to pay
        # for. This is the whole point of the archive.
        if plan == "restore":
            _record_restore_savings(db, project, files, restore_gap)
        if plan == "restore" and dims >= (
            project.embedding_native_dimensions or dims
        ):
            # Back at full fidelity - the archive is now empty (the restore SQL
            # cleared it) so stop treating the project as shrunk.
            project.embedding_native_dimensions = None
        bump_content_version(db, project.id)
        db.commit()
        return files

    if restore_gap:
        # Scoped to the gap files ONLY. Their chunks must still be deleted -
        # not left alone - because a chunk stuck at the old width is not merely
        # stale: retrieval compares with <=>, which RAISES on mismatched widths
        # on the exact path and silently skips the row on the ANN path. Deleting
        # and re-ingesting is the only state that is neither broken nor lying.
        db.execute(sql_delete(Chunk).where(Chunk.file_id.in_(restore_gap)))
    else:
        db.execute(sql_delete(Chunk).where(Chunk.project_id == project.id))
    if plan == "reembed":
        clear_memory_vectors(db, project.id)
    bump_content_version(db, project.id)
    # Set-based, and re-stating the currency predicate, for the same
    # READ-COMMITTED reason as the upload requeue: `files` was loaded before the
    # vector migration ran, and a confirm can supersede a row in between.
    # _files_to_requeue already filters, so this is defence in depth on the one
    # operation that can put retired content back into search.
    requeue_ids = [f.id for f in _files_to_requeue(files, restore_gap)]
    if requeue_ids:
        db.execute(
            update(File)
            .where(
                File.id.in_(requeue_ids),
                File.in_force_to.is_(None),
                File.status != "review",
            )
            .values(
                status="pending",  # the durable queue workers pick these up
                chunk_count=0,
                error=None,
                conversion_error=None,
                # Preserved - see the note at the upload requeue above.
                attempts=0,
            )
        )
    # Derived, not assigned: a requeue that is empty BECAUSE every file is
    # superseded or in review must not report 'ready' - the project cannot
    # answer anything.
    recompute_project_status(db, project)
    db.commit()

    # Memories re-embed as a background task (quick) so memory search is back
    # long before large file queues finish; files go through the queue.
    #
    # only_missing on the restore path: a full re-embed intends to replace every
    # memory vector, but a partial restore has just put correct vectors back and
    # must only fill the NULLs left behind - otherwise the background task pays
    # to overwrite embeddings it was meant to preserve.
    return files
