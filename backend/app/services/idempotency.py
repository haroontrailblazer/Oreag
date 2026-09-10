"""Optional durable replay for completed public requests; never repeat uncertain work."""
import functools
import hashlib
import inspect
import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..crypto import decrypt, encrypt
from ..models import IdempotencyRequest, Project, SuspendedAccount


def canonical(value):
    return hashlib.sha256(json.dumps(jsonable_encoder(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def claim(db, project_id, api_key_id, operation, key, request_hash):
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
        raise HTTPException(422, "Idempotency-Key must contain 1-128 letters, digits, dots, underscores, colons or hyphens.")
    project = db.get(Project, project_id)
    if project is None or project.suspended or db.get(SuspendedAccount, project.owner_id):
        raise HTTPException(403, "Project or account is unavailable.")
    instant, key_hash = datetime.now(timezone.utc), hashlib.sha256(key.encode()).hexdigest()
    where = (IdempotencyRequest.api_key_id == api_key_id, IdempotencyRequest.operation == operation, IdempotencyRequest.key_hash == key_hash)
    row = db.scalar(select(IdempotencyRequest).where(*where).with_for_update())
    if row and row.expires_at.replace(tzinfo=timezone.utc) <= instant:
        db.delete(row); db.flush(); row = None
    if row is None:
        # Ensure replay encryption is configured BEFORE accepting paid work.
        encrypt("idempotency-ready")
        row = IdempotencyRequest(project_id=project_id, api_key_id=api_key_id, operation=operation, key_hash=key_hash,
                                 request_hash=request_hash, expires_at=instant + timedelta(hours=24))
        db.add(row)
        try:
            db.commit()
            return row.id, None
        except IntegrityError:
            db.rollback()
            row = db.scalar(select(IdempotencyRequest).where(*where).with_for_update())
            if row is None:
                raise HTTPException(409, "Request ownership changed; retry with the same key.")
    if row.request_hash != request_hash:
        db.rollback()
        raise HTTPException(409, "This Idempotency-Key was used with different request content.")
    if row.status != "completed":
        db.rollback()
        raise HTTPException(409, "This request is running or its outcome is uncertain. It will not be executed again with this key.", headers={"Retry-After": "5"})
    data, code = json.loads(decrypt(row.response_encrypted)), row.status_code
    db.commit()
    return row.id, JSONResponse(data, status_code=code, headers={"Idempotency-Replayed": "true"})


def complete(db, row_id, result, operation):
    from ..schemas import FileOut, QueryResponse
    if operation == "query":
        result = QueryResponse.model_validate(result).model_dump(mode="json")
    elif operation == "files":
        result = [FileOut.model_validate(item).model_dump(mode="json") for item in result]
    else:
        result = jsonable_encoder(result)
    row = db.get(IdempotencyRequest, row_id)
    if row is None:
        raise HTTPException(503, "Request completed but its replay record is unavailable. Check the resource before retrying.")
    row.response_encrypted = encrypt(json.dumps(result, separators=(",", ":")))
    row.status, row.status_code = "completed", 200 if operation == "query" else 201
    db.commit()


def uncertain(db, row_id):
    db.rollback()
    try:
        row = db.get(IdempotencyRequest, row_id)
        if row and row.status == "pending":
            row.status = "uncertain"
            db.commit()
    except Exception:
        db.rollback()  # A pending record still blocks unsafe repetition.


async def upload_hash(uploads):
    from ..config import settings
    if len(uploads) > settings.max_files_per_upload:
        raise HTTPException(413, "Too many files in this upload.")
    parts = []
    for file in uploads:
        digest, size = hashlib.sha256(), 0
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                raise HTTPException(413, "File exceeds the upload limit.")
            digest.update(chunk)
        await file.seek(0)
        parts.append([file.filename, file.content_type, size, digest.hexdigest()])
    return canonical(parts)


def protect(operation):
    def decorate(fn):
        signature = inspect.signature(fn)
        def values(args, kwargs):
            values = signature.bind_partial(*args, **kwargs).arguments
            return values, values.get("idempotency_key")
        def begin(v, key, digest):
            if operation == "files" and not v["api_key"].can_upload:
                raise HTTPException(403, "This API key does not permit uploads.")
            return claim(v["db"], v["api_key"].project_id, v["api_key"].id, operation, key, digest)
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def asynchronous(*args, **kwargs):
                v, key = values(args, kwargs)
                if key is None:
                    return await fn(*args, **kwargs)
                row_id, replay = begin(v, key, await upload_hash(v["uploads"]))
                if replay is not None:
                    return replay
                try:
                    result = await fn(*args, **kwargs)
                    complete(v["db"], row_id, result, operation)
                    return result
                except BaseException:
                    uncertain(v["db"], row_id)
                    raise
            return asynchronous
        @functools.wraps(fn)
        def synchronous(*args, **kwargs):
            v, key = values(args, kwargs)
            if key is None:
                return fn(*args, **kwargs)
            row_id, replay = begin(v, key, canonical(v["body"]))
            if replay is not None:
                return replay
            try:
                result = fn(*args, **kwargs)
                complete(v["db"], row_id, result, operation)
                return result
            except BaseException:
                uncertain(v["db"], row_id)
                raise
        return synchronous
    return decorate
