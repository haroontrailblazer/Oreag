from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import Project
from ..providers import resolver
from ..providers.registry import get_embedder

SEARCH_SQL = text(
    """
    SELECT c.content, c.page_number, c.chunk_index, f.filename,
           1 - (c.embedding <=> CAST(:qvec AS vector)) AS similarity
    FROM chunks c
    JOIN files f ON f.id = c.file_id
    WHERE c.project_id = :project_id
    ORDER BY c.embedding <=> CAST(:qvec AS vector)
    LIMIT :top_k
    """
)


def retrieve(db: Session, project: Project, question: str, top_k: int) -> list[dict]:
    api_key = resolver.resolve_embedding_key(db, project)
    embedder = get_embedder(
        project.embedding_provider, project.embedding_model, api_key
    )
    query_vector = embedder.embed_query(question)
    qvec = "[" + ",".join(repr(v) for v in query_vector) + "]"
    rows = db.execute(
        SEARCH_SQL,
        {"qvec": qvec, "project_id": str(project.id), "top_k": top_k},
    ).mappings()
    return [dict(row) for row in rows]
