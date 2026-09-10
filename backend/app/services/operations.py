"""Bounded asynchronous request telemetry and owner-scoped operational snapshots."""
import json
import logging
import math
import queue
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select
from ..config import settings
from ..db import SessionLocal, engine
from ..models import EvaluationRun, File, OperationSnapshot, Project, RequestMetric, WebhookDelivery, WebhookEndpoint, WorkerHeartbeat

logger = logging.getLogger(__name__)
INSTANCE = str(uuid.uuid4())
METRICS = queue.Queue(maxsize=10000)
_dropped = 0
_last_database_success = 0.0
_workers = []


def configure_workers(workers):
    global _workers
    _workers = workers


def ready():
    return bool(_workers) and all(worker.is_alive() for worker in _workers) and time.monotonic() - _last_database_success < 20


def enqueue(values):
    global _dropped
    try:
        METRICS.put_nowait(values)
    except queue.Full:
        _dropped += 1


class RequestMetricsMiddleware:
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path.startswith("/v1/") or path.startswith("/api/projects/")):
            return await self.app(scope, receive, send)
        start, status, first_token, failed, disconnected, buffer, streaming = time.perf_counter(), 500, None, False, False, b"", False
        async def observed(message):
            nonlocal status, first_token, failed, buffer, streaming
            if message["type"] == "http.response.start":
                status = message["status"]
                streaming = any(k.lower() == b"content-type" and b"text/event-stream" in v for k, v in message.get("headers", []))
            elif message["type"] == "http.response.body" and streaming:
                buffer += message.get("body", b"")
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line.startswith(b"data:"):
                        try:
                            event = json.loads(line[5:].strip())
                            if isinstance(event, dict):
                                failed |= event.get("type") == "error"
                                if event.get("type") == "token" and event.get("text") and first_token is None:
                                    first_token = (time.perf_counter() - start) * 1000
                        except (ValueError, UnicodeError): pass
                if len(buffer) > 1024 * 1024: buffer = b""
            await send(message)
        try:
            await self.app(scope, receive, observed)
        except BaseException as exc:
            disconnected = isinstance(exc, (GeneratorExit,)) or type(exc).__name__ in ("CancelledError", "ClientDisconnect")
            failed = True
            raise
        finally:
            state = scope.get("state", {})
            owner, project = state.get("metric_owner_id"), state.get("metric_project_id")
            if owner or project:
                route = scope.get("route")
                # Route templates, never raw paths/questions/credentials, keep cardinality bounded.
                endpoint = getattr(route, "path", "unknown")
                enqueue({"owner_id": owner, "project_id": project, "endpoint": endpoint, "status_code": status,
                    "outcome": "disconnected" if disconnected else "stream_error" if failed and status < 400 else "error" if status >= 500 else "rejected" if status >= 400 else "success",
                    "latency_ms": (time.perf_counter() - start) * 1000, "first_token_ms": first_token,
                    "created_at": datetime.now(timezone.utc)})


def percentile(values, fraction=.95):
    if not values: return None
    values = sorted(values)
    position = (len(values)-1)*fraction
    lo, hi = math.floor(position), math.ceil(position)
    return round(values[lo] + (values[hi]-values[lo])*(position-lo), 2)


def summarize(rows):
    errors = sum(r.outcome in ("error", "stream_error", "disconnected") for r in rows)
    return {"requests": len(rows), "errors": errors, "rejected": sum(r.outcome == "rejected" for r in rows),
        "error_percent": round(errors / len(rows) * 100, 2) if rows else None,
        "p95_latency_ms": percentile([r.latency_ms for r in rows]),
        "p95_first_token_ms": percentile([r.first_token_ms for r in rows if r.first_token_ms is not None])}


def report(db, owner_id):
    instant = datetime.now(timezone.utc)
    rows = db.scalars(select(RequestMetric).where(RequestMetric.owner_id == owner_id, RequestMetric.created_at >= instant-timedelta(hours=24))
                      .order_by(RequestMetric.created_at.desc(), RequestMetric.id.desc()).limit(5000)).all()
    data = summarize(rows)
    fresh = [r for r in rows if r.created_at.replace(tzinfo=timezone.utc) >= instant-timedelta(minutes=15)]
    recent = summarize(fresh)
    projects = select(Project.id).where(Project.owner_id == owner_id)
    def queue_info(statement):
        count, oldest = db.execute(statement).one()
        return {"count": count, "oldest_seconds": max(0, int((instant-oldest.replace(tzinfo=timezone.utc)).total_seconds())) if oldest else None}
    queues = {
        "indexing": queue_info(select(func.count(File.id), func.min(File.created_at)).where(File.project_id.in_(projects), File.status.in_(["pending", "processing"]))),
        "evaluations": queue_info(select(func.count(EvaluationRun.id), func.min(EvaluationRun.created_at)).where(EvaluationRun.project_id.in_(projects), EvaluationRun.status.in_(["preparing", "running"]))),
        "webhooks": queue_info(select(func.count(WebhookDelivery.id), func.min(WebhookDelivery.created_at)).join(WebhookEndpoint).where(WebhookEndpoint.project_id.in_(projects), WebhookEndpoint.enabled.is_(True), WebhookDelivery.status == "pending")),
    }
    beats = db.scalars(select(WorkerHeartbeat).where(WorkerHeartbeat.last_seen_at >= instant-timedelta(seconds=20))).all()
    available = bool(beats) and any(all(b.workers.values()) and b.workers for b in beats)
    pressure = any(b.pool_used is not None and b.pool_limit and b.pool_used/b.pool_limit >= .9 for b in beats)
    warnings = []
    if not available: warnings.append({"kind": "workers", "message": "Background worker availability is not confirmed. Jobs may be delayed."})
    if pressure: warnings.append({"kind": "capacity", "message": "Shared database capacity is under pressure."})
    if any(b.dropped_metrics for b in beats): warnings.append({"kind": "telemetry", "message": "Some request measurements were dropped during overload. Counts may be incomplete."})
    if recent["requests"] >= 20 and recent["error_percent"] >= 5:
        warnings.append({"kind": "errors", "message": f"{recent['error_percent']}% of recent requests failed or disconnected."})
    if recent["requests"] >= 20 and recent["p95_latency_ms"] > 10000:
        warnings.append({"kind": "latency", "message": "Recent p95 request latency exceeds 10 seconds."})
    for name, item in queues.items():
        if item["oldest_seconds"] is not None and item["oldest_seconds"] > 300:
            warnings.append({"kind": name, "message": f"The oldest {name} job has been active or queued for over five minutes."})
    return {**data, "window_hours": 24, "sample_limit": 5000, "limited": len(rows) == 5000, "checked_at": instant.isoformat(),
            "queues": queues, "workers_available": available, "warnings": warnings}


def record_batch(db, batch):
    global _last_database_success
    pids = {item["project_id"] for item in batch if item["project_id"]}
    owners = dict(db.execute(select(Project.id, Project.owner_id).where(Project.id.in_(pids))).all()) if pids else {}
    for item in batch:
        if item["project_id"] and item["project_id"] not in owners: continue
        owner = item["owner_id"] or owners.get(item["project_id"])
        if owner: db.add(RequestMetric(**{**item, "owner_id": owner}))
    pool = engine.pool if engine else None
    used = pool.checkedout() if pool and hasattr(pool, "checkedout") else None
    limit = settings.db_pool_size + settings.db_max_overflow if used is not None else None
    beat = db.get(WorkerHeartbeat, INSTANCE)
    if beat is None:
        beat = WorkerHeartbeat(instance_id=INSTANCE); db.add(beat)
    beat.last_seen_at, beat.workers = datetime.now(timezone.utc), {w.name: w.is_alive() for w in _workers}
    beat.pool_used, beat.pool_limit, beat.dropped_metrics = used, limit, _dropped
    db.commit()
    _last_database_success = time.monotonic()


def operations_loop(stop):
    batch = []
    while not stop.is_set():
        try:
            while len(batch) < 200:
                try: batch.append(METRICS.get_nowait())
                except queue.Empty: break
            with SessionLocal() as db:
                record_batch(db, batch)
                batch.clear()
        except Exception:
            logger.warning("Operational telemetry delayed; buffered measurements will retry", exc_info=True)
        stop.wait(1 if not METRICS.empty() else 5)


def snapshot_loop(stop):
    # Owner analytics must not delay the heartbeat or telemetry queue drain.
    last_owner = None
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                owners = select(Project.owner_id).distinct().order_by(Project.owner_id).limit(10)
                if last_owner: owners = owners.where(Project.owner_id > last_owner)
                owner_ids = list(db.scalars(owners))
                for owner_id in owner_ids:
                    if stop.is_set(): break
                    previous = db.get(OperationSnapshot, owner_id)
                    if previous and (datetime.now(timezone.utc)-previous.checked_at.replace(tzinfo=timezone.utc)).total_seconds() < 60: continue
                    value = report(db, owner_id)
                    if previous is None: previous = OperationSnapshot(owner_id=owner_id); db.add(previous)
                    previous.report, previous.checked_at = value, datetime.now(timezone.utc)
                    db.commit()
                last_owner = owner_ids[-1] if owner_ids else None
        except Exception:
            logger.warning("Operational snapshot refresh delayed", exc_info=True)
        stop.wait(5)
