import uuid

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.jwt import get_current_user
from ..db import get_db
from ..models import Project
from ..providers.validation import InvalidProviderKeyError, validate_credential
from ..services.rate_limit import enforce_user_rate_limit


def ensure_valid_provider_key(provider: str, secret: str | None) -> None:
    """422 if `provider` rejects `secret`, so a bad key never reaches storage.

    No-op for the two non-values a key field can carry: None ("leave whatever
    is there alone") and "" ("clear the override"). Only a real credential is
    worth a network round trip.

    Call this BEFORE the route mutates anything. The probe is a network call and
    can raise; every caller here sits in front of writes that would otherwise
    have to be unwound.
    """
    if not secret:
        return
    try:
        validate_credential(provider, secret)
    except InvalidProviderKeyError as exc:
        raise HTTPException(422, str(exc))


def heavy_dashboard_limit(
    user_id: uuid.UUID = Depends(get_current_user),
) -> uuid.UUID:
    """Second, much smaller budget for the dashboard's expensive endpoints.

    Add this to any route that calls a provider or walks the graph - the
    playground query and stream, explore, memory-graph. It stacks on top of the
    standard per-user budget already applied in ``get_current_user``: a burst of
    cheap CRUD cannot exhaust the expensive allowance, and a burst of expensive
    calls is stopped long before the standard one would notice.

    Declared as a dependency rather than called inline so it is visible in the
    route signature and in the generated OpenAPI, instead of buried mid-handler.
    """
    enforce_user_rate_limit(user_id, heavy=True)
    return user_id


def get_owned_project(
    project_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    project = db.get(Project, project_id)
    # 404 (not 403) so project ids are not enumerable across tenants
    if project is None or project.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
