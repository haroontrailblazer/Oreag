"""Conservative passage comparisons. Candidates require human interpretation.

Only near-identical English statements with changed numbers or explicit 'not'
qualify. We do not label semantic similarity itself as a contradiction.
"""
import hashlib
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..models import Chunk, File, SourceConflictReview

SCAN_LIMIT = 2000
MATCH_LIMIT = 100
NUMBER = re.compile(r"(?<!\w)[+-]?\d+(?:[.,]\d+)*(?!\w)")
PREDICATE = re.compile(r"\b(?:is|are|was|were|must|shall|can|may|will|has|have|does|do|requires?|allows?|expires?|costs?)\b")


def statements(content):
    for raw in re.split(r"(?<=[.!?])\s+|[\r\n]+", content[:24000])[:80]:
        passage = raw.strip()
        if not 25 <= len(passage) <= 700 or passage.endswith("?"):
            continue
        normalized = " ".join(unicodedata.normalize("NFKC", passage).casefold().split()).strip(" .;:!•-*#")
        if len(re.findall(r"[a-z]+", normalized)) < 5 or not PREDICATE.search(normalized):
            continue
        numeric = tuple(NUMBER.findall(normalized))
        if numeric:
            # 30 / 30.0 and 1,000 / 1000 are formatting differences, not conflicts.
            try:
                numeric = tuple(Decimal(number.replace(",", "")) for number in numeric)
            except InvalidOperation:
                continue
            yield "numbers", NUMBER.sub("<number>", normalized), numeric, passage
        # Compare affirmative / explicitly negated versions of the same statement.
        base = re.sub(r"\bnot\s+", "", normalized)
        yield "negation", base, (bool(re.search(r"\bnot\b", normalized)),), passage


def candidates(rows):
    buckets = defaultdict(list)
    seen, result = set(), []
    limited = False
    for row in rows:
        for kind, skeleton, values, passage in statements(row["content"]):
            bucket = buckets[kind, skeleton]
            for prior, old_values, old_passage in bucket:
                if row["file_id"] == prior["file_id"] or values == old_values:
                    continue
                if (row["document_id"] or row["file_id"]) == (prior["document_id"] or prior["file_id"]):
                    continue
                identities = sorted([f'{prior["file_id"]}:{old_passage}', f'{row["file_id"]}:{passage}'])
                key = hashlib.sha256("\n".join(identities).encode()).hexdigest()
                if key in seen:
                    continue
                seen.add(key)
                def source(item, text):
                    return {name: item[name] for name in ("file_id", "filename", "page_number", "in_force_from", "in_force_to", "version_label")} | {"passage": text}
                result.append({"key": key, "reason": "Different numbers in matching statements" if kind == "numbers" else "One matching statement includes ‘not’",
                    "left": source(prior, old_passage), "right": source(row, passage)})
                if len(result) >= MATCH_LIMIT:
                    return result, True
            if len(bucket) < 20:
                bucket.append((row, values, passage))
            else:
                limited = True
    return result, limited


def report(db, project):
    from sqlalchemy import or_
    rows = db.execute(select(Chunk.content, Chunk.page_number, File.id.label("file_id"), File.document_id,
        File.filename, File.in_force_from, File.in_force_to, File.version_label).join(File, File.id == Chunk.file_id)
        .where(Chunk.project_id == project.id, File.project_id == project.id, File.status == "indexed", File.in_force_to.is_(None),
               or_(File.in_force_from.is_(None), File.in_force_from <= datetime.now(timezone.utc).date()))
        .order_by(File.id, Chunk.chunk_index, Chunk.id).limit(SCAN_LIMIT + 1)).mappings().all()
    items, limited = candidates(rows[:SCAN_LIMIT])
    keys = [item["key"] for item in items]
    reviews = {row.conflict_key: row for row in db.scalars(select(SourceConflictReview).where(
        SourceConflictReview.project_id == project.id, SourceConflictReview.conflict_key.in_(keys)))} if keys else {}
    for item in items:
        review = reviews.get(item["key"])
        item.update(status=review.status if review else "open", note=review.note if review else None,
                    revision=review.revision if review else 0, updated_at=review.updated_at if review else None)
    return {"items": items, "scanned_passages": min(len(rows), SCAN_LIMIT), "scan_limit": SCAN_LIMIT,
            "limited": limited or len(rows) > SCAN_LIMIT, "content_version": project.content_version}


def save(db, project, key, body):
    from ..models import Project
    db.execute(select(Project.id).where(Project.id == project.id).with_for_update()).one()
    db.refresh(project)
    current = report(db, project)
    item = next((item for item in current["items"] if item["key"] == key), None)
    if item is None or current["content_version"] != body.content_version:
        raise HTTPException(409, "Documents changed. Refresh the comparison before saving.")
    if item["revision"] != body.revision:
        raise HTTPException(409, "This review changed. Refresh before saving.")
    values = dict(status=body.status, note=body.note.strip() or None, revision=body.revision + 1, updated_at=datetime.now(timezone.utc))
    try:
        if body.revision == 0:
            db.add(SourceConflictReview(project_id=project.id, conflict_key=key, **values))
        else:
            changed = db.execute(update(SourceConflictReview).where(SourceConflictReview.project_id == project.id,
                SourceConflictReview.conflict_key == key, SourceConflictReview.revision == body.revision).values(**values))
            if changed.rowcount != 1:
                raise HTTPException(409, "This review changed. Refresh before saving.")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This review changed. Refresh before saving.") from None
    return {**item, **values}
