"""Rerun selected retained evidence using the existing isolated evaluator."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..evaluation_schemas import EvaluationCase, EvaluationConfig, EvaluationSuite, StartEvaluation
from ..models import EvaluationRun, KnowledgeGapReview, Project
from ..services import evaluations, knowledge_gaps
from .deps import get_owned_project, heavy_dashboard_limit

router = APIRouter(prefix="/api/projects/{project_id}/gaps/{key}/verification", tags=["gap verification"])
GapKey = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]


class VerificationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    expected: str = Field(default="", max_length=4000)
    source: str = Field(default="", max_length=500)
    match: str = Field(default="contains", pattern=r"^(contains|exact)$")


class VerifyGap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    evidence_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases: list[VerificationCase] = Field(min_length=1, max_length=20)


@router.get("")
def history(key: GapKey, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    from ..services.quality import project_config
    runs = list(db.scalars(select(EvaluationRun).where(EvaluationRun.project_id == project.id, EvaluationRun.gap_key == key)
                     .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc()).limit(5)))
    review = db.get(KnowledgeGapReview, (project.id, key))
    attached_id = review.verification_run_id if review else None
    if attached_id and all(run.id != attached_id for run in runs):
        attached = db.scalar(select(EvaluationRun).where(EvaluationRun.id == attached_id,
            EvaluationRun.project_id == project.id, EvaluationRun.gap_key == key))
        if attached:
            runs.append(attached)
    config = project_config(project).model_dump()
    items = []
    for run in runs:
        item = evaluations.run_out(run)
        item["matches_current"] = run.content_version == project.content_version and item["suite"]["variants"] == [config]
        items.append(item)
    return {"content_version": project.content_version, "runs": items}


@router.post("", status_code=201)
def verify(key: GapKey, body: VerifyGap, days: int = Query(30, ge=7, le=90), project: Project = Depends(get_owned_project),
           db: Session = Depends(get_db), _: uuid.UUID = Depends(heavy_dashboard_limit)):
    # Serialize with other starts; retries reuse the run ID without paying again.
    db.execute(select(Project.id).where(Project.id == project.id).with_for_update()).one()
    db.refresh(project)
    previous = db.get(EvaluationRun, body.id)
    if previous:
        if previous.project_id != project.id or previous.gap_key != key:
            raise HTTPException(404, "Verification not found")
        saved = evaluations.run_out(previous)
        submitted = [(f"query-{c.query_id}", c.expected, c.source, c.match) for c in body.cases]
        original = [(c["id"], c["expected"], c["source"], c["match"]) for c in saved["suite"]["cases"]]
        if previous.gap_evidence_version != body.evidence_version or submitted != original:
            raise HTTPException(409, "This verification ID already belongs to another check.")
        return saved
    snapshot = knowledge_gaps._snapshot(db, project.owner_id, days, project.id)
    item, rows = knowledge_gaps._selected(snapshot, project.id, key)
    if item.evidence_version != body.evidence_version:
        raise HTTPException(409, "Gap evidence changed. Refresh before starting verification.")
    evidence = {str(row["id"]): row for row in rows}
    if len({c.query_id for c in body.cases}) != len(body.cases):
        raise HTTPException(422, "Select each question once")
    if db.scalar(select(EvaluationRun.id).where(EvaluationRun.project_id == project.id,
        EvaluationRun.gap_key == key, EvaluationRun.status.in_(["preparing", "running"])).limit(1)):
        raise HTTPException(409, "A verification is already running for this gap.")
    cases = []
    for case in body.cases:
        row = evidence.get(case.query_id)
        if row is None:
            raise HTTPException(422, "Select questions from this gap's retained evidence")
        if len(row["question"]) > 4000:
            raise HTTPException(422, "This question exceeds the evaluator's 4,000-character limit")
        cases.append(EvaluationCase(id=f"query-{case.query_id}", question=row["question"], expected=case.expected, source=case.source, match=case.match))
    config = EvaluationConfig(**{name: getattr(project, name) for name in EvaluationConfig.model_fields if hasattr(project, name)})
    suite = EvaluationSuite(cases=cases, variants=[config])
    # Only compare identical questions, checks, and configurations. A passing
    # first run establishes current behavior; it does not demonstrate improvement.
    previous_checks = db.scalars(select(EvaluationRun).where(EvaluationRun.project_id == project.id,
        EvaluationRun.gap_key == key, EvaluationRun.status == "completed", EvaluationRun.archived_at.is_(None))
        .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc()).limit(20))
    reference = next((check for check in previous_checks if check.suite == suite.model_dump()), None)
    evaluations.create_run(db, project, StartEvaluation(id=body.id, suite=suite,
        reference_run_id=reference.id if reference else None), commit=False)
    run = db.get(EvaluationRun, body.id)
    run.gap_key, run.gap_evidence_version, run.trigger_reason = key, body.evidence_version, "gap_verification"
    db.commit()
    return evaluations.run_out(run)
