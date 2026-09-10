import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..crypto import encrypt
from ..db import get_db
from ..models import Project, WebhookEndpoint, WebhookDelivery
from ..services.webhooks import EVENTS, validate_url
from .deps import get_owned_project

router = APIRouter(prefix="/api/projects/{project_id}/webhooks", tags=["webhooks"])


class WebhookInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=2048)
    events: list[str] = Field(min_length=1, max_length=6)

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        validate_url(value)
        return value

    @field_validator("events")
    @classmethod
    def valid_events(cls, value):
        if set(value) - EVENTS or len(set(value)) != len(value):
            raise ValueError("Choose unique supported events")
        return value


class WebhookState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


def endpoint_out(row):
    return {"id": str(row.id), "url": row.url, "events": row.events, "enabled": row.enabled, "created_at": row.created_at}


def owned(db, project_id, endpoint_id):
    row = db.scalar(select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id, WebhookEndpoint.project_id == project_id).with_for_update())
    if row is None:
        raise HTTPException(404, "Webhook not found")
    return row


@router.get("")
def list_endpoints(project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    return [endpoint_out(row) for row in db.scalars(select(WebhookEndpoint).where(WebhookEndpoint.project_id == project.id).order_by(WebhookEndpoint.created_at))]


@router.post("", status_code=201)
def create(body: WebhookInput, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    db.execute(select(Project.id).where(Project.id == project.id).with_for_update()).one()
    if db.scalar(select(func.count()).select_from(WebhookEndpoint).where(WebhookEndpoint.project_id == project.id)) >= 5:
        raise HTTPException(409, "A project supports up to five webhooks.")
    secret = "whsec_" + secrets.token_urlsafe(32)
    row = WebhookEndpoint(project_id=project.id, url=body.url, events=body.events, secret_encrypted=encrypt(secret))
    db.add(row)
    db.commit()
    return {**endpoint_out(row), "secret": secret}


@router.patch("/{endpoint_id}")
def set_enabled(endpoint_id: uuid.UUID, body: WebhookState, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    row = owned(db, project.id, endpoint_id)
    row.enabled = body.enabled
    db.commit()
    return endpoint_out(row)


@router.delete("/{endpoint_id}", status_code=204)
def remove(endpoint_id: uuid.UUID, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    db.delete(owned(db, project.id, endpoint_id))
    db.commit()


@router.post("/{endpoint_id}/rotate-secret")
def rotate(endpoint_id: uuid.UUID, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    row = owned(db, project.id, endpoint_id)
    secret = "whsec_" + secrets.token_urlsafe(32)
    row.secret_encrypted = encrypt(secret)
    db.commit()
    return {"secret": secret}


@router.get("/{endpoint_id}/deliveries")
def deliveries(endpoint_id: uuid.UUID, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    owned(db, project.id, endpoint_id)
    return [{"id": str(r.id), "event_id": str(r.event_id), "event_type": r.event_type, "status": r.status, "attempts": r.attempts,
             "response_status": r.response_status, "last_error": r.last_error, "history": r.history, "created_at": r.created_at,
             "next_attempt_at": r.next_attempt_at if r.status == "pending" else None}
            for r in db.scalars(select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint_id).order_by(WebhookDelivery.created_at.desc()).limit(50))]


@router.post("/{endpoint_id}/deliveries/{delivery_id}/retry")
def retry(endpoint_id: uuid.UUID, delivery_id: uuid.UUID, project: Project = Depends(get_owned_project), db: Session = Depends(get_db)):
    endpoint = owned(db, project.id, endpoint_id)
    row = db.scalar(select(WebhookDelivery).where(WebhookDelivery.id == delivery_id, WebhookDelivery.endpoint_id == endpoint_id).with_for_update())
    if row is None:
        raise HTTPException(404, "Delivery not found")
    if row.status != "failed" or not endpoint.enabled:
        raise HTTPException(409, "Enable the webhook and choose a failed delivery to retry.")
    row.status, row.attempts, row.next_attempt_at = "pending", 0, datetime.now(timezone.utc)
    row.lease_token, row.lease_until = None, None
    db.commit()
    return {"status": "pending"}
