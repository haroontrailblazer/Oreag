import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.jwt import get_current_user
from ..budget_schemas import BudgetInput, BudgetsReport, BudgetAlertOut
from ..db import get_db
from ..services import budgets as service

router = APIRouter(prefix="/api/account/budgets", tags=["account"])


class AlertsOut(BaseModel):
    alerts: list[BudgetAlertOut]
    unread_count: int


@router.get("", response_model=BudgetsReport)
def get_budgets(user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.report(db, user_id)


@router.put("", response_model=BudgetsReport)
def save_budget(body: BudgetInput, user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.save(db, user_id, body)


@router.delete("/{budget_id}", status_code=204)
def delete_budget(budget_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    service.remove(db, user_id, budget_id)


@router.get("/alerts", response_model=AlertsOut)
def get_alerts(user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.alerts(db, user_id)


@router.post("/alerts/{alert_id}/read", status_code=204)
def read_alert(alert_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    service.mark_read(db, user_id, alert_id)


@router.post("/alerts/read-all", status_code=204)
def read_all_alerts(user_id: uuid.UUID = Depends(get_current_user), db: Session = Depends(get_db)):
    service.mark_all_read(db, user_id)
