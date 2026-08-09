"""Langfuse has no user CRUD - a "user" there is derived from the userId on
its observations. So registering an account means emitting one, and forgetting
one means deleting them all.

The test that matters is the paging one: deletion is ASYNCHRONOUS, so a trace
stays readable after a successful DELETE. The first implementation deleted then
re-queried page 1, saw the same trace again, deleted it again and counted it
again - it reported 7 removals for a single trace and rate-limited itself into
a 429 doing it.
"""
import httpx
import pytest

from app.services import tracing


class _FakeResponse:
    def __init__(self, payload=None, status=200):
        self._payload = payload if payload is not None else {}
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=None, response=None
            )


class _FakeClient:
    """Stands in for the Langfuse REST API, including its async deletion."""

    def __init__(self, pages, on_delete=None):
        self.pages = pages
        self.deleted: list[list[str]] = []
        self.get_calls = 0
        self._on_delete = on_delete

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, path, params=None):
        self.get_calls += 1
        page = (params or {}).get("page", 1)
        # Deliberately keeps returning deleted traces, as the real API does.
        data = self.pages[page - 1] if page - 1 < len(self.pages) else []
        return _FakeResponse({"data": [{"id": i} for i in data]})

    def request(self, method, path, json=None):
        ids = (json or {}).get("traceIds", [])
        self.deleted.append(ids)
        if self._on_delete:
            return self._on_delete(ids)
        return _FakeResponse({})


@pytest.fixture()
def configured(monkeypatch):
    """Make client()/settings look configured without touching the network."""
    from app.config import settings

    monkeypatch.setattr(tracing, "client", lambda: object())
    monkeypatch.setattr(settings, "langfuse_base_url", "https://lf.test", raising=False)
    monkeypatch.setattr(settings, "langfuse_public_key", "pk", raising=False)
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk", raising=False)


def _install(monkeypatch, fake):
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake)
    return fake


class TestForgetUser:
    def test_counts_each_trace_once(self, monkeypatch, configured):
        """The regression: one trace must report one removal, not seven."""
        fake = _install(monkeypatch, _FakeClient(pages=[["t1"]]))
        assert tracing.forget_user("u") == 1
        assert fake.deleted == [["t1"]]

    def test_does_not_requery_after_deleting(self, monkeypatch, configured):
        """Collect-then-delete. A delete-then-requery loop sees async-deleted
        traces again and never terminates cleanly."""
        fake = _install(monkeypatch, _FakeClient(pages=[["t1"]]))
        tracing.forget_user("u")
        # One page fetch (short page ends paging); never a re-fetch per delete.
        assert fake.get_calls == 1

    def test_pages_through_a_large_account(self, monkeypatch, configured):
        full = [f"t{i}" for i in range(100)]
        fake = _install(monkeypatch, _FakeClient(pages=[full, ["tail"]]))
        assert tracing.forget_user("u") == 101
        assert [len(chunk) for chunk in fake.deleted] == [100, 1]

    def test_duplicates_across_pages_are_deleted_once(self, monkeypatch, configured):
        """Paging a list being written to can repeat an entry; a repeat must
        not become a second delete request."""
        full = [f"t{i}" for i in range(100)]
        fake = _install(monkeypatch, _FakeClient(pages=[full, ["t0", "new"]]))
        assert tracing.forget_user("u") == 101
        assert "new" in fake.deleted[-1]
        flat = [i for chunk in fake.deleted for i in chunk]
        assert len(flat) == len(set(flat)), "a trace was deleted twice"

    def test_rate_limit_while_listing_stops_cleanly(self, monkeypatch, configured):
        class Limited(_FakeClient):
            def get(self, path, params=None):
                return _FakeResponse(status=429)

        _install(monkeypatch, Limited(pages=[]))
        assert tracing.forget_user("u") == 0  # reported honestly, not crashed

    def test_paging_is_bounded(self, monkeypatch, configured):
        """A never-shortening page must not loop against a third-party API."""
        endless = [[f"p{p}-{i}" for i in range(100)] for p in range(500)]
        fake = _install(monkeypatch, _FakeClient(pages=endless))
        tracing.forget_user("u")
        assert fake.get_calls <= tracing._MAX_TRACE_PAGES

    def test_disabled_tracing_is_a_no_op(self, monkeypatch):
        monkeypatch.setattr(tracing, "client", lambda: None)
        assert tracing.forget_user("u") == 0

    def test_network_failure_reports_zero_rather_than_raising(
        self, monkeypatch, configured
    ):
        """Account deletion must not fail because Langfuse had a bad minute."""
        def boom(**kw):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(httpx, "Client", boom)
        assert tracing.forget_user("u") == 0


class TestRegisterUser:
    def test_disabled_tracing_is_a_no_op(self, monkeypatch):
        monkeypatch.setattr(tracing, "client", lambda: None)
        tracing.register_user("u")  # must not raise

    def test_failure_cannot_break_a_signup(self, monkeypatch):
        class Broken:
            def start_as_current_observation(self, **kw):
                raise RuntimeError("langfuse is down")

        monkeypatch.setattr(tracing, "client", lambda: Broken())
        tracing.register_user("u")  # must not raise
