import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from fastapi import File as FastAPIFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from .. import crypto
from ..config import settings
from ..db import get_db
from ..models import Chunk, File, Project
from ..providers import registry
from ..schemas import FileOut, ReindexRequest
from ..services import storage
from ..services.content_version import bump_content_version
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
    if embedding_provider or embedding_model or embedding_dimensions is not None:
        provider, model, dims, plan = _plan_embedding_change(
            project, embedding_provider, embedding_model, embedding_dimensions
        )
        if plan == "truncate" and not _truncate_vectors_in_place(db, project, dims):
            plan = "reembed"
        elif plan == "truncate":
            # A successful truncation rewrote every existing vector, so the
            # cache signature has to move even though nothing is re-ingested.
            # Bumped HERE rather than relying on the uploaded files bumping it
            # during ingestion: that happens to work today, but it makes a
            # correctness invariant depend on a side effect of an unrelated
            # step, and it fails outright if every uploaded file errors out.
            bump_content_version(db, project.id)
        project.embedding_provider = provider
        project.embedding_model = model
        project.embedding_dimensions = dims
        reindex_existing = plan == "reembed"

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
    existing: list[File] = []
    if reindex_existing:
        new_ids = {record.id for record in created}
        db.execute(sql_delete(Chunk).where(Chunk.project_id == project.id))
        db.execute(_CLEAR_MEMORY_EMBEDDINGS_SQL, {"project_id": str(project.id)})
        bump_content_version(db, project.id)
        existing = [
            f
            for f in db.scalars(
                select(File).where(File.project_id == project.id)
            ).all()
            if f.id not in new_ids
        ]
        for f in existing:
            f.status = "pending"
            f.chunk_count = 0
            f.error = None
            f.conversion_error = None
            # conversion_note is NOT cleared. It describes how the MARKDOWN
            # was produced ("audio used the free fallback endpoint"), and a
            # re-index now REUSES that markdown, so clearing it would drop a
            # caveat that is still true. ingest_file rewrites it either way:
            # the reuse path carries it forward, a real re-conversion
            # replaces it with a fresh one.
            f.attempts = 0  # fresh retry budget for the re-ingest

    project.status = "indexing"
    db.commit()

    # Memories re-embed as a background task (quick); files sit in
    # status='pending' for the durable queue workers - no in-process queue to
    # lose on a restart.
    if reindex_existing:
        background_tasks.add_task(reembed_project_memories, project.id)
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
    storage.delete(paths)


@router.post("/files/{file_id}/retry", response_model=FileOut)
def retry_file(
    file_id: uuid.UUID,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    file = db.get(File, file_id)
    if file is None or file.project_id != project.id:
        raise HTTPException(404, "File not found")
    if file.status == "processing":
        raise HTTPException(409, "File is already being processed")
    file.status = "pending"  # the queue workers pick it up from here
    file.error = None
    file.conversion_error = None
    file.conversion_note = None
    file.attempts = 0  # a manual retry gets a fresh budget
    project.status = "indexing"
    db.commit()
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
    pair = crypto.apply_override(body.embedding_api_key)
    if pair is not None:
        project.embedding_key_encrypted, project.embedding_key_last4 = pair
    project.chunk_size = effective_size
    project.chunk_overlap = effective_overlap

    files = db.scalars(select(File).where(File.project_id == project.id)).all()

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
        if plan == "restore" and dims >= (
            project.embedding_native_dimensions or dims
        ):
            # Back at full fidelity - the archive is now empty (the restore SQL
            # cleared it) so stop treating the project as shrunk.
            project.embedding_native_dimensions = None
        bump_content_version(db, project.id)
        db.commit()
        return files

    requeue = _files_to_requeue(files, restore_gap)
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
        db.execute(_CLEAR_MEMORY_EMBEDDINGS_SQL, {"project_id": str(project.id)})
    bump_content_version(db, project.id)
    for file in requeue:
        file.status = "pending"  # the durable queue workers pick these up
        file.chunk_count = 0
        file.error = None
        file.conversion_error = None
        # Preserved - see the note at the upload requeue above.
        file.attempts = 0
    project.status = "indexing" if requeue else "ready"
    db.commit()

    # Memories re-embed as a background task (quick) so memory search is back
    # long before large file queues finish; files go through the queue.
    #
    # only_missing on the restore path: a full re-embed intends to replace every
    # memory vector, but a partial restore has just put correct vectors back and
    # must only fill the NULLs left behind - otherwise the background task pays
    # to overwrite embeddings it was meant to preserve.
    if plan == "reembed":
        background_tasks.add_task(reembed_project_memories, project.id)
    elif restore_gap:
        background_tasks.add_task(
            reembed_project_memories, project.id, only_missing=True
        )
    return files
