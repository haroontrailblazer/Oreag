import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from app.models import Base, IdempotencyRequest, ApiKey, SuspendedAccount, Project, EvaluationRun, EvaluationSchedule, EvaluationVector, RequestMetric, WorkerHeartbeat, OperationSnapshot, File, WebhookEndpoint, WebhookDelivery
from app.services import idempotency, operations, evaluation_retention, evaluations
from app.schemas import QueryResponse
from tests.test_evaluations import app_data, base, start, SUITE


def test_retention_protects_reference_and_preserves_export(app_data):
    client, db, project, _ = app_data
    instant = datetime.now(timezone.utc)
    runs = []
    for i in range(20):
        row = EvaluationRun(project_id=project.id, status="completed", suite=SUITE, corpus=[{"content": "Knowledge"}], corpus_count=1, prepared=1, content_version=0,
                            results=[{"answer": f"Preserved answer {i}"}], created_at=instant-timedelta(days=30-i))
        db.add(row); runs.append(row)
    db.flush()
    db.add(EvaluationSchedule(project_id=project.id, suite=SUITE, enabled=True, reference_run_id=runs[0].id, quality_limits={}))
    db.add(EvaluationVector(run_id=runs[1].id, variant=0, ordinal=0, content="Knowledge", filename="doc", is_memory=False, embedding=[1,0]))
    db.commit()
    start(client, project)
    assert runs[0].archived_at is None and runs[1].archived_at is not None
    assert runs[1].corpus == [] and runs[1].results == []
    assert db.scalar(sa.select(sa.func.count()).select_from(EvaluationVector).where(EvaluationVector.run_id == runs[1].id)) == 0
    response = client.get(base(project)+f"/runs/{runs[1].id}")
    assert response.json()["results"] == [{"answer": "Preserved answer 1"}]
    assert len(client.get(base(project)+"/runs").json()) == 20
    assert len(client.get(base(project)+"/runs?archived=true").json()) == 1
    assert client.post(base(project)+f"/runs/{runs[1].id}/resume").status_code == 409
    assert client.post(base(project)+f"/runs/{runs[1].id}/cancel").status_code == 409


@pytest.fixture
def db_data(monkeypatch):
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool, connect_args={"check_same_thread":False})
    Base.metadata.create_all(engine, tables=[x.__table__ for x in (Project, ApiKey, SuspendedAccount, IdempotencyRequest, RequestMetric, WorkerHeartbeat, OperationSnapshot, File, EvaluationRun, WebhookEndpoint, WebhookDelivery)])
    monkeypatch.setattr(idempotency, "encrypt", lambda s: "encrypted:"+s)
    monkeypatch.setattr(idempotency, "decrypt", lambda s: s.removeprefix("encrypted:"))
    with Session(engine, expire_on_commit=False) as db:
        project = Project(owner_id=uuid.uuid4(), name="Mine")
        other = Project(owner_id=uuid.uuid4(), name="Other")
        db.add_all([project, other]); db.flush()
        key = ApiKey(project_id=project.id, key_hash="one", key_prefix="one")
        key2 = ApiKey(project_id=project.id, key_hash="two", key_prefix="two")
        db.add_all([key,key2]); db.commit()
        yield db, project, other, key, key2
    engine.dispose()


def test_idempotency_replay_content_conflict_key_scope_and_uncertain(db_data):
    db, p, _, key, key2 = db_data
    calls=[]
    @idempotency.protect("query")
    def query(body, api_key, db, idempotency_key=None):
        calls.append(body)
        return QueryResponse(answer="Original answer", sources=[], model="test", latency_ms=12)
    first=query({"question":"Hi"}, key, db, "retry-1")
    replay=query({"question":"Hi"}, key, db, "retry-1")
    assert json.loads(replay.body)["answer"] == first.answer
    assert len(calls)==1 and replay.headers["Idempotency-Replayed"] == "true"
    with pytest.raises(HTTPException): query({"question":"Different"},key,db,"retry-1")
    query({"question":"Hi"},key2,db,"retry-1")
    assert len(calls)==2
    row_id,_=idempotency.claim(db,p.id,key.id,"query","uncertain",idempotency.canonical({"question":"Hi"}))
    idempotency.uncertain(db,row_id)
    with pytest.raises(HTTPException): query({"question":"Hi"},key,db,"uncertain")
    p.suspended=True;db.commit()
    with pytest.raises(HTTPException): query({"question":"Hi"},key,db,"retry-1")


def test_operations_tenant_scope_unknown_timings_and_queue_warnings(db_data):
    db,p,other,_,_=db_data
    now=datetime.now(timezone.utc)
    db.add_all([RequestMetric(owner_id=p.owner_id,project_id=p.id,endpoint="/query",status_code=500,outcome="error",latency_ms=12000,first_token_ms=None) for _ in range(20)])
    db.add(RequestMetric(owner_id=other.owner_id,project_id=other.id,endpoint="/query",status_code=200,outcome="success",latency_ms=1,first_token_ms=1))
    db.add(File(project_id=p.id,filename="queued.txt",storage_path="fixture",status="pending",created_at=now-timedelta(minutes=10)))
    db.add(WorkerHeartbeat(instance_id="fixture",last_seen_at=now,workers={"evaluation":True},pool_used=1,pool_limit=20,dropped_metrics=0))
    db.commit()
    report=operations.report(db,p.owner_id)
    assert report["requests"]==20 and report["errors"]==20
    assert report["p95_first_token_ms"] is None
    assert {w["kind"] for w in report["warnings"]} == {"errors","latency","indexing"}
    assert operations.report(db,other.owner_id)["errors"]==0


def test_stream_errors_first_token_and_no_unauthenticated_attribution(monkeypatch):
    captured=[];monkeypatch.setattr(operations,"enqueue",captured.append)
    app=FastAPI();app.add_middleware(operations.RequestMetricsMiddleware)
    from fastapi import Request
    @app.get("/v1/projects/{project_id}/query/stream")
    def stream(project_id:str, request:Request):
        request.state.metric_project_id=uuid.UUID(project_id)
        return StreamingResponse(iter([b'data: {"type":"ping"}\n\n',b'data: {"type":"tok', b'en","text":"Hello"}\n\n',b'data: {"type":"error","detail":"Busy"}\n\n']),media_type="text/event-stream")
    with TestClient(app) as c:
        assert c.get(f"/v1/projects/{uuid.uuid4()}/query/stream").status_code==200
        c.get("/v1/unknown")
    assert len(captured)==1 and captured[0]["outcome"]=="stream_error"
    assert captured[0]["first_token_ms"] is not None
    assert captured[0]["endpoint"]=="/v1/projects/{project_id}/query/stream"


def test_public_query_replay_still_authenticates_and_preserves_contract(db_data, monkeypatch):
    from app.auth.api_keys import generate_api_key
    from app.db import get_db
    from app.routers import rag_v1
    db,p,_,key,_=db_data
    token,key.key_hash,key.key_prefix=generate_api_key();db.commit()
    calls=[]
    monkeypatch.setattr(rag_v1,"run_query",lambda *a,**kw: calls.append(kw) or QueryResponse(answer="Original",sources=[],model="fixture",latency_ms=5,conversation_id="thread"))
    monkeypatch.setattr(rag_v1,"record_usage",lambda *a,**kw:None)
    monkeypatch.setattr(rag_v1,"_maybe_judge",lambda *a,**kw:None)
    monkeypatch.setattr(rag_v1,"enforce_rate_limit",lambda *a,**kw:None)
    app=FastAPI();app.include_router(rag_v1.router);app.dependency_overrides[get_db]=lambda:db
    headers={"Authorization":"Bearer "+token,"Idempotency-Key":"public-retry"}
    with TestClient(app) as c:
        path=f"/v1/projects/{p.id}/query"
        first=c.post(path,json={"question":"Hello","conversation_id":"thread"},headers=headers)
        replay=c.post(path,json={"question":"Hello","conversation_id":"thread"},headers=headers)
        assert first.status_code==replay.status_code==200
        assert first.json()==replay.json() and len(calls)==1
        assert replay.headers["Idempotency-Replayed"]=="true"
        assert c.post(path+"/stream",json={"question":"Hello"},headers=headers).status_code==422
        key.revoked_at=datetime.now(timezone.utc);db.commit()
        assert c.post(path,json={"question":"Hello","conversation_id":"thread"},headers=headers).status_code==401


def test_public_evaluation_replays_original_id(app_data,monkeypatch):
    from app.auth.api_keys import generate_api_key
    client,db,project,_=app_data
    IdempotencyRequest.__table__.create(db.bind)
    monkeypatch.setattr(idempotency,"encrypt",lambda v:"fixture:"+v)
    monkeypatch.setattr(idempotency,"decrypt",lambda v:v.removeprefix("fixture:"))
    token,digest,prefix=generate_api_key()
    db.add(ApiKey(project_id=project.id,key_hash=digest,key_prefix=prefix));db.commit()
    headers={"Authorization":"Bearer "+token,"Idempotency-Key":"eval-retry"}
    body={"id":str(uuid.uuid4()),"suite":SUITE}
    path=f"/v1/projects/{project.id}/evaluations/runs"
    first=client.post(path,json=body,headers=headers)
    replay=client.post(path,json=body,headers=headers)
    assert first.status_code==replay.status_code==201, first.text
    assert first.json()==replay.json()
    assert db.scalar(sa.select(sa.func.count()).select_from(EvaluationRun))==1


def test_upload_fingerprint_rewinds_and_completed_replay(db_data):
    import asyncio
    import io
    from starlette.datastructures import UploadFile, Headers
    db,project,_,key,_=db_data
    key.can_upload=True;db.commit()
    calls=[]
    @idempotency.protect("files")
    async def upload(uploads,api_key,db,idempotency_key=None):
        calls.append(await uploads[0].read())
        row=File(project_id=project.id,filename="fixture.txt",storage_path="fixture",status="pending")
        db.add(row);db.commit()
        return [row]
    async def check():
        def files(data=b"Original"):
            return [UploadFile(io.BytesIO(data),filename="fixture.txt",headers=Headers({"content-type":"text/plain"}))]
        first=await upload(files(),key,db,"upload-retry")
        replay=await upload(files(),key,db,"upload-retry")
        assert calls==[b"Original"] and json.loads(replay.body)[0]["id"]==str(first[0].id)
        with pytest.raises(HTTPException): await upload(files(b"Changed"),key,db,"upload-retry")
    asyncio.run(check())


def test_readiness_expires_and_dead_worker_is_not_ready(monkeypatch):
    monkeypatch.setattr(operations.time,"monotonic",lambda:100)
    monkeypatch.setattr(operations,"_last_database_success",95)
    monkeypatch.setattr(operations,"_workers",[SimpleNamespace(is_alive=lambda:True)])
    assert operations.ready()
    monkeypatch.setattr(operations,"_last_database_success",70)
    assert not operations.ready()
    monkeypatch.setattr(operations,"_last_database_success",95)
    monkeypatch.setattr(operations,"_workers",[SimpleNamespace(is_alive=lambda:False)])
    assert not operations.ready()
