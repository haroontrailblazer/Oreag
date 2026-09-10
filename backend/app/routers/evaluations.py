import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.api_keys import require_api_key
from ..db import get_db
from ..evaluation_schemas import SaveEvaluation, StartEvaluation, SaveSchedule, AddQueryCase
from ..schemas import FeedbackInput
from ..models import ApiKey, EvaluationRun, EvaluationSchedule, Project
from ..services import evaluations as service
from ..services import quality
from ..services.rate_limit import enforce_rate_limit
from .deps import get_owned_project, heavy_dashboard_limit
from .rag_v1 import _get_project

router = APIRouter(prefix="/api/projects/{project_id}/evaluations", tags=["evaluations"])
public_router = APIRouter(prefix="/v1/projects/{project_id}/evaluations", tags=["public-api"])


def public_project(project_id: uuid.UUID, api_key: ApiKey = Depends(require_api_key), db: Session = Depends(get_db)):
    project = _get_project(db, project_id)
    enforce_rate_limit(api_key.id, project.id)
    return project


@router.get("/suite")
def get_suite(project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    return service.read_suite(db, project)


@router.put("/runs/{run_id}/results/{result_index}/feedback")
def result_feedback(run_id: uuid.UUID, result_index: int, body: FeedbackInput, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    return service.write_result_feedback(db, project.id, run_id, result_index, body)


@router.delete("/runs/{run_id}/results/{result_index}/feedback", status_code=204)
def clear_result_feedback(run_id: uuid.UUID, result_index: int, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    service.write_result_feedback(db, project.id, run_id, result_index, None)


@public_router.put("/runs/{run_id}/results/{result_index}/feedback")
def public_result_feedback(run_id: uuid.UUID, result_index: int, body: FeedbackInput, project: Project = Depends(public_project), db: Session = Depends(get_db)):
    return result_feedback(run_id, result_index, body, project, db)


@public_router.delete("/runs/{run_id}/results/{result_index}/feedback", status_code=204)
def public_clear_result_feedback(run_id: uuid.UUID, result_index: int, project: Project = Depends(public_project), db: Session = Depends(get_db)):
    clear_result_feedback(run_id, result_index, project, db)


@router.put("/suite")
def save_suite(body: SaveEvaluation, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    return service.save_suite(db, project, body)


@router.get("/runs")
def list_runs(project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    return [dict(row) for row in db.execute(select(EvaluationRun.id, EvaluationRun.status, EvaluationRun.created_at, EvaluationRun.quality_report)
            .where(EvaluationRun.project_id == project.id).order_by(EvaluationRun.created_at.desc()).limit(20)).mappings()]


@router.post("/runs", status_code=201)
def start_run(body: StartEvaluation, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    return service.create_run(db, project, body)


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    return service.run_out(service.get_run(db, project.id, run_id))


@router.post("/runs/{run_id}/advance")
def advance(run_id: uuid.UUID, project: Project = Depends(get_owned_project), db: Session = Depends(get_db), _: uuid.UUID = Depends(heavy_dashboard_limit)):
    return service.advance(db, project, run_id)


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: uuid.UUID, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    return service.cancel(db, project.id, run_id)


@router.post("/runs/{run_id}/resume")
def resume(run_id: uuid.UUID, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    return service.resume(db, project.id, run_id)


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: uuid.UUID, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    service.delete_run(db, project.id, run_id)


@public_router.get("/suite")
def public_get_suite(project: Project = Depends(public_project), db: Session = Depends(get_db)):
    return get_suite(project, db)


@public_router.put("/suite")
def public_save_suite(body: SaveEvaluation, project: Project = Depends(public_project), db: Session = Depends(get_db)):
    return save_suite(body, project, db)


@public_router.get("/runs")
def public_list_runs(project: Project = Depends(public_project), db: Session = Depends(get_db)):
    return list_runs(project, db)


@public_router.post("/runs", status_code=201)
def public_start_run(body: StartEvaluation, project: Project = Depends(public_project), db: Session = Depends(get_db), api_key: ApiKey = Depends(require_api_key)):
    enforce_rate_limit(api_key.id, project.id, heavy=True)
    return service.create_run(db, project, body, api_key_id=api_key.id)


@public_router.get("/runs/{run_id}")
def public_get_run(run_id: uuid.UUID, project: Project = Depends(public_project), db: Session = Depends(get_db)):
    return get_run(run_id, project, db)


@public_router.post("/runs/{run_id}/advance")
def public_advance(run_id: uuid.UUID, project: Project = Depends(public_project), api_key: ApiKey = Depends(require_api_key), db: Session = Depends(get_db)):
    enforce_rate_limit(api_key.id, project.id, heavy=True)
    return service.advance(db, project, run_id, api_key.id)


@public_router.post("/runs/{run_id}/cancel")
def public_cancel(run_id: uuid.UUID, project: Project = Depends(public_project), db: Session = Depends(get_db)):
    return cancel(run_id, project, db)


@public_router.post("/runs/{run_id}/resume")
def public_resume(run_id: uuid.UUID, project: Project = Depends(public_project), db: Session = Depends(get_db)):
    return resume(run_id, project, db)


@public_router.delete("/runs/{run_id}", status_code=204)
def public_delete_run(run_id: uuid.UUID, project: Project = Depends(public_project), db: Session = Depends(get_db)):
    delete_run(run_id, project, db)


@router.get("/schedule")
def get_schedule(project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    return quality.schedule_out(db.get(EvaluationSchedule, project.id))


@router.put("/schedule")
def save_schedule(body: SaveSchedule, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    return quality.save_schedule(db, project, body)


@router.post("/cases/from-query")
def add_query_case(body: AddQueryCase, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    return quality.add_query(db, project, body)


@public_router.post("/cases/from-query")
def public_add_query_case(body: AddQueryCase, project: Project = Depends(public_project), db: Session = Depends(get_db)):
    return quality.add_query(db, project, body)
