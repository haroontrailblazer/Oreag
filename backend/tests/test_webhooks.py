import uuid
from datetime import timedelta
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.auth.jwt import get_current_user
from app.db import get_db
from app.models import Base, Project, SuspendedAccount, WebhookEndpoint, WebhookDelivery
from app.routers import webhooks as routes
from app.services import webhooks


@pytest.fixture
def data(monkeypatch):
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[m.__table__ for m in (Project, SuspendedAccount, WebhookEndpoint, WebhookDelivery)])
    with Session(engine, expire_on_commit=False) as db:
        owner = uuid.uuid4()
        p = Project(owner_id=owner, name="Project"); other = Project(owner_id=uuid.uuid4(), name="Other")
        db.add_all([p, other]); db.commit()
        app = FastAPI(); app.include_router(routes.router)
        app.dependency_overrides[get_current_user] = lambda: owner
        app.dependency_overrides[get_db] = lambda: db
        monkeypatch.setattr(routes, "encrypt", lambda s: "encrypted:"+s)
        monkeypatch.setattr(webhooks, "decrypt", lambda s: s.removeprefix("encrypted:"))
        with TestClient(app) as client:
            yield client, db, p, other
    engine.dispose()


def test_owner_secret_visibility_delivery_retry_and_pause(data):
    client, db, p, other = data
    base = f"/api/projects/{p.id}/webhooks"
    response = client.post(base, json={"url": "https://receiver.example/events", "events": ["file.indexed"]})
    assert response.status_code == 201
    result = response.json(); eid = uuid.UUID(result["id"])
    assert result["secret"].startswith("whsec_")
    assert "secret" not in client.get(base).json()[0]
    assert client.get(f"/api/projects/{other.id}/webhooks/{eid}/deliveries").status_code == 404
    event_id = uuid.uuid4()
    delivery = WebhookDelivery(endpoint_id=eid, event_id=event_id, event_type="file.indexed", payload={"id": str(event_id)})
    db.add(delivery); db.commit()
    assert webhooks.deliver_one(db, lambda *a: 503)
    assert delivery.status == "pending" and delivery.attempts == 1
    assert not webhooks.deliver_one(db, lambda *a: pytest.fail("Backoff must be honoured"))
    for i in range(7):
        delivery.next_attempt_at -= timedelta(days=1); db.commit()
        assert webhooks.deliver_one(db, lambda *a: 503)
    assert delivery.status == "failed" and len(delivery.history) == 8
    path = f"{base}/{eid}/deliveries/{delivery.id}/retry"
    assert client.post(path).status_code == 200
    assert webhooks.deliver_one(db, lambda *a: 204)
    assert delivery.status == "delivered" and len(delivery.history) == 9
    assert client.post(path).status_code == 409
    assert client.patch(f"{base}/{eid}", json={"enabled": False}).status_code == 200
    delivery.status = "pending"; delivery.next_attempt_at -= timedelta(days=1); db.commit()
    assert not webhooks.deliver_one(db, lambda *a: pytest.fail("Paused endpoints must not send"))


@pytest.mark.parametrize("url", ["http://example.com", "https://a:b@example.com", "https://example.com:8443", "https://example.com/#fragment", "https://example.com/\nfoo"])
def test_invalid_urls(url):
    with pytest.raises(HTTPException): webhooks.validate_url(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1", "224.0.0.1"])
def test_private_resolution_never_connects(monkeypatch, address):
    monkeypatch.setattr(webhooks.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", (address, 443))])
    with pytest.raises(ValueError): webhooks.public_address("example.com")


def test_pins_public_ip_and_signs_exact_bytes(monkeypatch):
    sent = {}
    monkeypatch.setattr(webhooks, "public_address", lambda host: "8.8.8.8")
    monkeypatch.setattr(webhooks.time, "time", lambda: 123)
    class Connection:
        def __init__(self, host, ip): sent.update(host=host, ip=ip)
        def request(self, method, path, body, headers): sent.update(body=body, headers=headers, path=path)
        def getresponse(self): return type("Response", (), {"status": 302})()
        def close(self): pass
    monkeypatch.setattr(webhooks, "PinnedHTTPSConnection", Connection)
    assert webhooks.send("https://example.com/events?q=1", "secret", {"id": "event"}) == 302
    expected = webhooks.hmac.new(b"secret", b"123." + sent["body"], webhooks.hashlib.sha256).hexdigest()
    assert sent["headers"]["Oreag-Signature"] == "v1="+expected
    assert sent["host"] == "example.com" and sent["ip"] == "8.8.8.8"
