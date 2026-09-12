"""Persisted evaluation snapshots and bounded, leased work steps.

Each step prepares <=32 vectors or answers one question. A durable worker drives steps;
reloads/restarts can resume the persisted cursor without repeating committed work.
"""
import json
import logging
import math
import unicodedata
import uuid
import copy
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.orm import Session

from ..evaluation_schemas import EvaluationConfig, EvaluationSuite
from ..models import Chunk, EvaluationRun, EvaluationSuiteRecord, EvaluationVector, File, MemoryChunk, Project
from ..providers import resolver
from ..providers.registry import get_embedder
from . import cross_lingual, generation, retrieval, text_search
from .query import run_query
from .usage import record_usage

logger = logging.getLogger(__name__)
MAX_CORPUS = 2000
BATCH_SIZE = 32


def configured_project(project: Project, config: EvaluationConfig) -> SimpleNamespace:
    # A plain, non-ORM configuration snapshot: it cannot be added to a Session.
    # Never mutate the live Project or send its override key to another provider.
    values = {column.key: getattr(project, column.key) for column in Project.__table__.columns}
    for role in ("embedding", "llm"):
        if getattr(config, f"{role}_provider") != getattr(project, f"{role}_provider"):
            values[f"{role}_key_encrypted"] = None
            values[f"{role}_key_last4"] = None
    values.update(config.model_dump(exclude={"hybrid_search", "include_memories"}))
    values["embedding_native_dimensions"] = None
    return SimpleNamespace(**values)


def check_credentials(db, project, suite):
    for config in suite.variants:
        candidate = configured_project(project, config)
        for role in ("embedding", "llm"):
            provider = getattr(candidate, f"{role}_provider")
            key = getattr(resolver, f"resolve_{role}_key")(db, candidate)
            if resolver.requires_key(provider) and not key:
                raise HTTPException(422, f"Add an account {provider} key before evaluating its {role} model.")


def read_suite(db, project):
    row = db.get(EvaluationSuiteRecord, project.id)
    return {"revision": row.revision if row else 0, "suite": row.suite if row else None}


def save_suite(db, project, body):
    # Lock the parent too: serializes the initial insert where no suite exists.
    db.execute(select(Project.id).where(Project.id == project.id).with_for_update()).one()
    row = db.get(EvaluationSuiteRecord, project.id, populate_existing=True)
    if (row.revision if row else 0) != body.revision:
        db.rollback()
        raise HTTPException(409, "This test set changed in another session. Reload the saved set before saving.")
    if row is None:
        row = EvaluationSuiteRecord(project_id=project.id, revision=1, suite=body.suite.model_dump())
        db.add(row)
    else:
        row.suite, row.revision = body.suite.model_dump(), row.revision + 1
    db.commit()
    return read_suite(db, project)


def get_run(db, project_id, run_id):
    run = db.scalar(select(EvaluationRun).where(EvaluationRun.id == run_id, EvaluationRun.project_id == project_id).execution_options(populate_existing=True))
    if run is None:
        raise HTTPException(404, "Evaluation run not found")
    return run


def run_out(run):
    if run.archived_at:
        import gzip
        return {**json.loads(gzip.decompress(run.archived_payload)), "archived_at": run.archived_at}
    return {"id": str(run.id), "status": run.status, "suite": run.suite, "corpus_count": run.corpus_count,
            "trigger_reason": run.trigger_reason, "gap_key": run.gap_key, "gap_evidence_version": run.gap_evidence_version,
            "archived_at": None,
            "execution": run.execution, "reference_run_id": str(run.reference_run_id) if run.reference_run_id else None,
            "quality_report": run.quality_report,
            "content_version": run.content_version, "prepared": run.prepared, "results": run.results,
            "error": run.error, "created_at": run.created_at, "updated_at": run.updated_at}


def create_run(db, project, body, *, commit=True, quality_limits=None, api_key_id=None):
    from .quality import allowed, validate_reference
    allowed(db, project, api_key_id)
    previous = db.get(EvaluationRun, body.id)
    if previous:
        if previous.project_id != project.id:
            raise HTTPException(404, "Evaluation run not found")
        if previous.suite != body.suite.model_dump():
            raise HTTPException(409, "This run ID already belongs to a different configuration.")
        return run_out(previous)
    if not body.suite.cases:
        raise HTTPException(422, "Add at least one question.")
    check_credentials(db, project, body.suite)
    db.execute(select(Project.id).where(Project.id == project.id).with_for_update()).one()
    # A concurrent retry can have committed while we waited on the project lock.
    previous = db.get(EvaluationRun, body.id, populate_existing=True)
    if previous:
        if previous.project_id != project.id:
            raise HTTPException(404, "Evaluation run not found")
        if previous.suite != body.suite.model_dump():
            raise HTTPException(409, "This run ID already belongs to a different configuration.")
        return run_out(previous)
    validate_reference(db, project.id, body.reference_run_id, body.suite.model_dump())
    from .evaluation_retention import make_room
    make_room(db, project.id)
    version = project.content_version
    rows = db.execute(select(Chunk.content, File.filename, Chunk.page_number).join(File, Chunk.file_id == File.id)
                      .where(Chunk.project_id == project.id, File.in_force_to.is_(None), File.status == "indexed")
                      .order_by(Chunk.id).limit(MAX_CORPUS + 1)).all()
    corpus = [{"content": row.content, "filename": row.filename, "page_number": row.page_number, "is_memory": False} for row in rows]
    if any(v.include_memories for v in body.suite.variants):
        memories = db.scalars(select(MemoryChunk.content).where(MemoryChunk.project_id == project.id).order_by(MemoryChunk.id).limit(MAX_CORPUS + 1)).all()
        corpus.extend({"content": content, "filename": "memory", "page_number": None, "is_memory": True} for content in memories)
    if not corpus:
        raise HTTPException(409, "Index documents or memories before running an evaluation.")
    if len(corpus) > MAX_CORPUS or len(json.dumps(corpus).encode()) > 8_000_000:
        raise HTTPException(422, "Evaluation supports up to 2,000 indexed passages and 8 MB of text per run. Use a smaller test project.")
    row = EvaluationRun(id=body.id, project_id=project.id, status="preparing", suite=body.suite.model_dump(),
                        execution="background" if body.background else "manual", requested_by_key_id=api_key_id,
                        reference_run_id=body.reference_run_id, quality_limits=quality_limits or {},
                        corpus=corpus, corpus_count=len(corpus), content_version=version, prepared=0, results=[])
    db.add(row)
    db.flush()
    if commit:
        db.commit()
    return run_out(row)


def score(case, response):
    def norm(s):
        return " ".join(unicodedata.normalize("NFKC", s).lower().split())
    expected, source = norm(case.expected), norm(case.source)
    if not expected and not source:
        return "review"
    answer = norm(response.answer)
    text_ok = not expected or (answer == expected if case.match == "exact" else expected in answer)
    source_ok = not source or any(norm(s.filename) == source for s in response.sources)
    return "passed" if text_ok and source_ok else "failed"


def validate_vectors(vectors, count, dimensions):
    if len(vectors) != count or any(len(v) != dimensions or not all(math.isfinite(x) for x in v) or not any(v) for v in vectors):
        raise ValueError("The embedding provider returned incompatible vectors. Check its model and vector dimensions.")


def index_retriever(db, run_id, variant, config, project):
    def retrieve(question, k, embed, llm, on_usage):
        def search(query):
            vector = embed(query)
            validate_vectors([vector], 1, config.embedding_dimensions)
            distance = EvaluationVector.embedding.cosine_distance(vector)
            stmt = select(EvaluationVector, (1 - distance).label("similarity")).where(EvaluationVector.run_id == run_id, EvaluationVector.variant == variant)
            if not config.include_memories:
                stmt = stmt.where(EvaluationVector.is_memory.is_(False))
            return [{"id": row.ordinal, "filename": row.filename, "page_number": row.page_number,
                     "chunk_index": row.ordinal, "content": row.content, "similarity": similarity}
                    for row, similarity in db.execute(stmt.order_by(distance).limit(k)).all()], vector
        semantic, vector = search(question)
        query = cross_lingual.retrieval_query(db, project, question, rows=semantic, llm=llm, on_usage=on_usage)
        if query != question:
            semantic, vector = search(query)
        lexical = []
        if config.hybrid_search:
            lexical = [dict(row) for row in db.execute(text("""
                SELECT ordinal AS id, filename, page_number, ordinal AS chunk_index, content,
                       1 - (embedding <=> CAST(:vector AS vector)) AS similarity
                FROM evaluation_vectors
                WHERE run_id = :run_id AND variant = :variant
                  AND (:memories OR NOT is_memory)
                  AND to_tsvector(CAST(:language AS regconfig), content) @@ plainto_tsquery(CAST(:language AS regconfig), :question)
                ORDER BY ts_rank_cd(to_tsvector(CAST(:language AS regconfig), content), plainto_tsquery(CAST(:language AS regconfig), :question)) DESC, ordinal
                LIMIT :limit
            """), {"vector": str(vector), "run_id": run_id, "variant": variant, "memories": config.include_memories,
                    "language": text_search.config_for(project), "question": query, "limit": k}).mappings()]
        return retrieval.rrf_merge(semantic, lexical, k)
    return retrieve


def advance(db: Session, project, run_id, api_key_id=None):
    project_id = project.id
    run = get_run(db, project_id, run_id)
    if run.status not in ("preparing", "running"):
        return run_out(run)
    token = uuid.uuid4()
    now = datetime.now(timezone.utc)
    claimed = db.execute(update(EvaluationRun).where(EvaluationRun.id == run_id, EvaluationRun.status.in_(["preparing", "running"]),
                          or_(EvaluationRun.lease_until.is_(None), EvaluationRun.lease_until < now))
                         .values(lease_token=token, lease_until=now + timedelta(minutes=10)).execution_options(synchronize_session=False)).rowcount
    db.commit()
    if not claimed:
        raise HTTPException(409, "A step is already running. Wait for it to finish before resuming.")
    run = get_run(db, project_id, run_id)
    suite = EvaluationSuite.model_validate(run.suite)
    prepared, count, results = run.prepared, run.corpus_count, list(run.results)
    candidate = None
    usage = {}
    endpoint = "evaluation_index"
    spent = False
    try:
        if prepared < count * len(suite.variants):
            variant, offset = divmod(prepared, count)
            config = suite.variants[variant]
            candidate = configured_project(project, config)
            batch = run.corpus[offset:offset + BATCH_SIZE]
            vectors = None
            if variant and all(getattr(config, key) == getattr(suite.variants[0], key) for key in ("embedding_provider", "embedding_model", "embedding_dimensions")):
                vectors = list(db.scalars(select(EvaluationVector.embedding).where(EvaluationVector.run_id == run_id, EvaluationVector.variant == 0,
                                  EvaluationVector.ordinal >= offset, EvaluationVector.ordinal < offset + len(batch)).order_by(EvaluationVector.ordinal)))
            if vectors is None:
                key = resolver.resolve_embedding_key(db, candidate)
                embedder = get_embedder(config.embedding_provider, config.embedding_model, key, dimensions=config.embedding_dimensions)
                generation.release_connection(db)
                spent = True
                vectors = embedder.embed_texts([item["content"] for item in batch])
            validate_vectors(vectors, len(batch), config.embedding_dimensions)
            # Lock only while committing. Cancel and delete cannot race the writes.
            current = db.scalar(select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update().execution_options(populate_existing=True))
            if current is None or current.lease_token != token or current.status == "cancelled":
                return run_out(current) if current else {"id": str(run_id), "status": "cancelled"}
            for ordinal, (item, vector) in enumerate(zip(batch, vectors), offset):
                db.add(EvaluationVector(run_id=run_id, variant=variant, ordinal=ordinal, embedding=vector, **item))
            changes = {"prepared": prepared + len(batch), "status": "preparing" if prepared + len(batch) < count * len(suite.variants) else "running"}
        else:
            case_index, variant = divmod(len(results), len(suite.variants))
            if case_index >= len(suite.cases):
                changes = {"status": "completed"}
            else:
                config, case = suite.variants[variant], suite.cases[case_index]
                candidate = configured_project(project, config)
                candidate.content_version = run.content_version
                endpoint, spent = "evaluation_query", True
                passages = [item["content"] for item in run.corpus if config.include_memories or not item["is_memory"]]
                with cross_lingual.isolated_evaluation(passages):
                    response = run_query(db, candidate, case.question, config.top_k, api_key_id=api_key_id, usage_out=usage,
                                         retrieval_override=index_retriever(db, run_id, variant, config, candidate), bypass_cache=True, record_query=False)
                from ..providers.registry import cost_for, embedding_cost_for
                from . import embedding_usage
                llm_cost = cost_for(config.llm_model, usage.get("usage"), config.llm_provider)
                acc = embedding_usage.current()
                embedding_cost = (embedding_cost_for(acc.total.model, acc.total.prompt_tokens, config.embedding_provider)
                                  if acc and acc.calls and not acc.unmeasured_calls else (0 if acc and not acc.calls else None))
                cost = llm_cost + embedding_cost if llm_cost is not None and embedding_cost is not None else None
                results.append({"caseId": case.id, "variant": variant, "status": score(case, response), "response": response.model_dump(), "cost_usd": cost})
                changes = {"results": results, "status": "completed" if len(results) == len(suite.cases) * len(suite.variants) else "running"}
        if changes.get("status") == "completed":
            from .quality import assess
            snapshot = SimpleNamespace(project_id=project_id, suite=run.suite, results=changes.get("results", results),
                                       reference_run_id=run.reference_run_id, quality_limits=run.quality_limits)
            changes["quality_report"] = assess(db, snapshot)
        db.execute(update(EvaluationRun).where(EvaluationRun.id == run_id, EvaluationRun.lease_token == token, EvaluationRun.status != "cancelled")
                   .values(**changes, error=None, lease_token=None, lease_until=None, updated_at=datetime.now(timezone.utc)))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Evaluation step failed for %s", run_id)
        # Provider exceptions may carry credentials/URLs; only publish controlled errors.
        message = str(exc.detail) if isinstance(exc, HTTPException) and exc.status_code in (409, 422, 429, 503) else "Evaluation step failed. Check provider availability and retry."
        db.execute(update(EvaluationRun).where(EvaluationRun.id == run_id, EvaluationRun.lease_token == token, EvaluationRun.status != "cancelled")
                   .values(status="failed", error=message, lease_token=None, lease_until=None, updated_at=datetime.now(timezone.utc)))
        db.commit()
    finally:
        db.execute(update(EvaluationRun).where(EvaluationRun.id == run_id, EvaluationRun.lease_token == token)
                   .values(lease_token=None, lease_until=None))
        db.commit()
        if candidate is not None and spent:
            record_usage(db, project=candidate, api_key_id=api_key_id, endpoint=endpoint, latency_ms=usage.get("latency_ms"), usage=usage.get("usage"))
    return run_out(get_run(db, project_id, run_id))


def cancel(db, project_id, run_id):
    db.execute(select(Project.id).where(Project.id == project_id).with_for_update()).one()
    run = get_run(db, project_id, run_id)
    if run.archived_at:
        raise HTTPException(409, "Archived results are read-only.")
    db.execute(update(EvaluationRun).where(EvaluationRun.id == run_id, EvaluationRun.status.in_(["preparing", "running", "failed"]))
               .values(status="cancelled", updated_at=datetime.now(timezone.utc)))
    db.commit()
    return run_out(get_run(db, project_id, run_id))


def resume(db, project_id, run_id):
    db.execute(select(Project.id).where(Project.id == project_id).with_for_update()).one()
    run = get_run(db, project_id, run_id)
    if run.archived_at:
        raise HTTPException(409, "Archived results are read-only. Start a new run to evaluate again.")
    # Cancelled is final: restarting requires a new snapshot and run identity.
    if run.status == "failed":
        db.execute(update(EvaluationRun).where(EvaluationRun.id == run_id, EvaluationRun.status == "failed")
                   .values(status="preparing" if run.prepared < run.corpus_count * len(run.suite["variants"]) else "running", error=None))
        db.commit()
    return run_out(get_run(db, project_id, run_id))


def delete_run(db, project_id, run_id):
    db.execute(select(Project.id).where(Project.id == project_id).with_for_update()).one()
    run = get_run(db, project_id, run_id)
    if run.status in ("preparing", "running") or (run.lease_until and run.lease_until.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)):
        raise HTTPException(409, "Stop this run and wait for its active step to finish before deleting it.")
    db.execute(delete(EvaluationVector).where(EvaluationVector.run_id == run_id))
    db.delete(run)
    db.commit()


def write_result_feedback(db, project_id, run_id, result_index, feedback):
    run = db.scalar(select(EvaluationRun).where(EvaluationRun.id == run_id, EvaluationRun.project_id == project_id)
                    .with_for_update().execution_options(populate_existing=True))
    if run is None:
        raise HTTPException(404, "Evaluation run not found")
    if run.archived_at:
        raise HTTPException(409, "Archived results are read-only.")
    if run.status in ("preparing", "running"):
        raise HTTPException(409, "Finish or stop the run before rating its results.")
    if result_index < 0 or result_index >= len(run.results) or not run.results[result_index].get("response"):
        raise HTTPException(404, "Evaluation result not found")
    results = copy.deepcopy(run.results)
    result = results[result_index]
    result["feedback_rating"] = feedback.rating if feedback else None
    result["feedback_note"] = (feedback.note or "") if feedback else None
    run.results = results
    db.commit()
    return {"feedback_rating": result["feedback_rating"], "feedback_note": result["feedback_note"]}
