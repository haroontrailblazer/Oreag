import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BudgetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: uuid.UUID | None = None
    amount_usd: Decimal = Field(gt=0, le=1_000_000, max_digits=9, decimal_places=2)
    warning_percent: int = Field(default=80, ge=1, le=99)
    enabled: bool = True
    revision: int = Field(default=0, ge=0)


class BudgetOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    project_name: str | None
    amount_usd: float
    warning_percent: int
    enabled: bool
    revision: int
    spent_usd: float | None
    requests: int
    unpriced_requests: int
    percent_used: float | None
    state: Literal["paused", "unmeasured", "exceeded", "warning", "on_track"]
    last_checked_at: datetime | None


class BudgetAlertOut(BaseModel):
    id: uuid.UUID
    budget_id: uuid.UUID
    project_name: str | None
    period_start: date
    threshold_percent: int
    amount_usd: float
    spent_usd: float
    created_at: datetime
    read_at: datetime | None


class BudgetsReport(BaseModel):
    period_start: date
    period_end: date
    budgets: list[BudgetOut]
    alerts: list[BudgetAlertOut]
    unread_count: int
    mode: Literal["warn_only"] = "warn_only"
