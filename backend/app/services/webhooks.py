"""Durable, signed webhook delivery. DNS is validated and pinned on every attempt."""
import hashlib
import hmac
import http.client
import ipaddress
import json
import logging
import secrets
import socket
import ssl
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import or_, select

from ..crypto import decrypt
from ..db import SessionLocal
from ..models import Project, SuspendedAccount, WebhookDelivery, WebhookEndpoint

EVENTS = {"file.indexed", "file.failed", "evaluation.completed", "evaluation.failed", "evaluation.regressed", "budget.threshold_reached"}
logger = logging.getLogger(__name__)


def validate_url(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or parsed.port not in (None, 443) or any(ord(c) <= 32 for c in url)
                or len(url) > 2048 or "\\" in url):
            raise ValueError()
        # IDNA normalisation also rejects invalid Unicode hostnames.
        parsed.hostname.encode("idna")
        return parsed
    except (ValueError, UnicodeError):
        raise HTTPException(422, "Use a public HTTPS URL on port 443, without credentials or fragments.")


def public_address(host):
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("No public address")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global or ip.is_multicast or (ip.version == 6 and ip.ipv4_mapped and not ip.ipv4_mapped.is_global):
            raise ValueError("Destination must resolve only to public addresses")
    return addresses[0][4][0]


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=8, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def send(url, secret, payload):
    parsed = validate_url(url)
    host = parsed.hostname.encode("idna").decode("ascii")
    address = public_address(host)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    connection = PinnedHTTPSConnection(host, address)
    try:
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        connection.request("POST", path, body, {"Content-Type": "application/json", "User-Agent": "Oreag-Webhooks/1.0",
            "Oreag-Event-Id": payload["id"], "Oreag-Timestamp": timestamp, "Oreag-Signature": "v1=" + signature})
        response = connection.getresponse()
        # Never follow redirects or retain a potentially sensitive response body.
        return response.status
    finally:
        connection.close()


def deliver_one(db, sender=send):
    instant = datetime.now(timezone.utc)
    row = db.scalar(select(WebhookDelivery).join(WebhookEndpoint).where(WebhookEndpoint.enabled.is_(True),
        WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at <= instant,
        or_(WebhookDelivery.lease_until.is_(None), WebhookDelivery.lease_until < instant))
        .order_by(WebhookDelivery.next_attempt_at).with_for_update(of=WebhookDelivery, skip_locked=True).limit(1))
    if row is None:
        db.rollback()
        return False
    endpoint = db.get(WebhookEndpoint, row.endpoint_id)
    project = db.get(Project, endpoint.project_id)
    token, delivery_id = uuid.uuid4(), row.id
    row.lease_token, row.lease_until = token, instant + timedelta(minutes=2)
    url, encrypted, payload = endpoint.url, endpoint.secret_encrypted, row.payload
    unavailable = project is None or project.suspended or db.get(SuspendedAccount, project.owner_id) is not None
    db.commit()
    status, error = None, None
    try:
        if unavailable:
            raise ValueError("Project unavailable")
        status = sender(url, decrypt(encrypted), payload)
        if not 200 <= status < 300:
            error = "Receiver returned a non-success status."
    except Exception:
        error = "Delivery failed. Check the public HTTPS destination and receiver availability."
    row = db.scalar(select(WebhookDelivery).where(WebhookDelivery.id == delivery_id, WebhookDelivery.lease_token == token).with_for_update())
    if row is None:
        db.rollback()
        return True
    instant = datetime.now(timezone.utc)
    row.attempts += 1
    row.response_status, row.last_error = status, error
    row.history = (row.history + [{"at": instant.isoformat(), "attempt": row.attempts, "status": status, "error": error}])[-32:]
    row.status = "delivered" if error is None else ("failed" if row.attempts >= 8 or unavailable else "pending")
    row.next_attempt_at = instant + timedelta(seconds=min(3600, 30 * 2 ** (row.attempts - 1)) + secrets.randbelow(10))
    row.lease_token, row.lease_until = None, None
    db.commit()
    return True


def webhook_loop(stop):
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                worked = deliver_one(db)
            stop.wait(.1 if worked else 2)
        except Exception:
            logger.warning("Webhook worker will retry", exc_info=True)
            stop.wait(5)
