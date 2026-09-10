"""Check migration 0047 and archive/replay storage in a rolled-back transaction."""
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlalchemy as sa
from sqlalchemy.orm import Session
from apply_migration import find, load_database_url

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/"backend"))
from app.models import Project, ApiKey, EvaluationRun, EvaluationVector, IdempotencyRequest, RequestMetric, WorkerHeartbeat, OperationSnapshot
from app.services import evaluation_retention, evaluations

engine=sa.create_engine(load_database_url())
with engine.connect() as c:
    transaction=c.begin()
    try:
        c.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
        c.exec_driver_sql("SET LOCAL statement_timeout = '30s'")
        c.exec_driver_sql(find("0047").read_text(encoding="utf-8"))
        # Verify rerun safety too.
        c.exec_driver_sql(find("0047").read_text(encoding="utf-8"))
        owner=c.scalar(sa.text("SELECT id FROM auth.users LIMIT 1"))
        assert owner
        with Session(c,join_transaction_mode="create_savepoint",expire_on_commit=False) as db:
            project=Project(owner_id=owner,name="Rollback-only reliability fixture")
            db.add(project);db.flush()
            key=ApiKey(project_id=project.id,key_hash=uuid.uuid4().hex,key_prefix="fixture")
            db.add(key);db.flush()
            now=datetime.now(timezone.utc)
            for i in range(20):
                db.add(EvaluationRun(project_id=project.id,status="completed",suite={"cases":[],"variants":[]},corpus=[{"content":"Fixture"}],corpus_count=1,content_version=0,prepared=1,results=[{"answer":"Preserve"}],created_at=now-timedelta(days=20-i)))
            db.flush();evaluation_retention.make_room(db,project.id)
            archived=db.scalar(sa.select(EvaluationRun).where(EvaluationRun.project_id==project.id,EvaluationRun.archived_at.is_not(None)))
            assert evaluations.run_out(archived)["results"]==[{"answer":"Preserve"}]
            db.add(IdempotencyRequest(project_id=project.id,api_key_id=key.id,operation="query",key_hash="fixture",request_hash="fixture",expires_at=now+timedelta(days=1)))
            db.add(RequestMetric(owner_id=owner,project_id=project.id,endpoint="fixture",status_code=200,outcome="success",latency_ms=1))
            db.add(WorkerHeartbeat(instance_id=uuid.uuid4().hex,last_seen_at=now,workers={"fixture":True}))
            db.flush()
            for table in ("idempotency_requests","request_metrics","worker_heartbeats","operation_snapshots"):
                assert c.scalar(sa.text("SELECT relrowsecurity FROM pg_class WHERE oid=CAST(:table AS regclass)"),{"table":"public."+table})
                assert not c.scalar(sa.text("SELECT has_table_privilege('authenticated',:table,'SELECT')"),{"table":"public."+table})
        print("Migration 0047 rerun, PostgreSQL archive/replay columns, model writes and RLS verified; all fixtures rolled back.")
    finally: transaction.rollback()
engine.dispose()
