"""Exercise migration 0046 and its outbox in one rolled-back database transaction."""
import sys
import uuid
from pathlib import Path
import sqlalchemy as sa
from sqlalchemy.orm import Session
from apply_migration import load_database_url, find

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from app.models import Project, File, EvaluationRun, WebhookEndpoint, WebhookDelivery

engine = sa.create_engine(load_database_url())
with engine.connect() as connection:
    transaction = connection.begin()
    try:
        connection.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
        connection.exec_driver_sql("SET LOCAL statement_timeout = '30s'")
        applied = connection.scalar(sa.text("SELECT to_regclass('public.webhook_endpoints') IS NOT NULL"))
        if not applied:
            connection.exec_driver_sql(find("0046").read_text(encoding="utf-8"))
        owner = connection.scalar(sa.text("SELECT id FROM auth.users LIMIT 1"))
        assert owner, "An existing auth owner is required for rollback-only fixtures"
        with Session(connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as db:
            project = Project(owner_id=owner, name="Rollback-only quality verification")
            db.add(project); db.flush()
            events = ["file.indexed", "file.failed", "evaluation.completed", "evaluation.failed", "evaluation.regressed", "budget.threshold_reached"]
            endpoint = WebhookEndpoint(project_id=project.id, url="https://example.com/events", events=events, secret_encrypted="rollback-only-fixture", enabled=True)
            db.add(endpoint); db.flush()
            file = File(project_id=project.id, filename="fixture.txt", storage_path="rollback-only", status="pending")
            db.add(file); db.flush()
            file.status = "indexed"; db.flush()
            file.status = "failed"; db.flush()
            run = EvaluationRun(project_id=project.id, status="running", execution="background", suite={"variants": [], "cases": []}, corpus=[{"content": "fixture"}], corpus_count=1, content_version=0, prepared=0, results=[])
            db.add(run); db.flush()
            run.status = "completed"; run.quality_report = {"state": "regressed", "warnings": [{"metric": "latency_ms"}]}; db.flush()
            budget = uuid.uuid4()
            db.execute(sa.text("INSERT INTO usage_budgets(id,owner_id,project_id,scope_key,amount_usd) VALUES (:id,:owner,:pid,:scope,100)"), {"id": budget, "owner": owner, "pid": project.id, "scope": str(project.id)})
            db.execute(sa.text("INSERT INTO usage_budget_alerts(budget_id,period_start,threshold_percent,amount_usd,spent_usd) VALUES (:id,current_date,80,100,80)"), {"id": budget})
            rows = db.scalars(sa.select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint.id)).all()
            assert {r.event_type for r in rows} == {"file.indexed", "file.failed", "evaluation.completed", "evaluation.regressed", "budget.threshold_reached"}
            assert len(rows) == 5 and all(r.payload["project_id"] == str(project.id) for r in rows)
            # A repeated status write must not create a duplicate transition event.
            db.execute(sa.text("UPDATE files SET status = 'failed' WHERE id = :id"), {"id": file.id})
            assert db.scalar(sa.select(sa.func.count()).select_from(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint.id)) == 5
            endpoint.enabled = False; db.flush()
            run.status = "failed"; db.flush()
            assert db.scalar(sa.select(sa.func.count()).select_from(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint.id)) == 5
            # The real production dialect must accept the worker's lock queries.
            db.execute(sa.select(WebhookDelivery).join(WebhookEndpoint).where(WebhookDelivery.endpoint_id == endpoint.id).with_for_update(of=WebhookDelivery, skip_locked=True)).all()
            db.commit()
        assert connection.scalar(sa.text("SELECT relrowsecurity FROM pg_class WHERE oid = 'public.webhook_deliveries'::regclass"))
        assert not connection.scalar(sa.text("SELECT has_table_privilege('authenticated', 'public.webhook_endpoints', 'SELECT')"))
        print("Verified migration, atomic outbox transitions, pause behavior, lock query and RLS. All fixtures rolled back.")
    finally:
        transaction.rollback()
engine.dispose()
