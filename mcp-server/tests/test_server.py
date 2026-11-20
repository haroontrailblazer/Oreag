import asyncio

import httpx

# Importing the server is itself the regression check: an unbounded `mcp`
# requirement once resolved to mcp 2.x, where `mcp.server.fastmcp` no longer
# exists, and the deployed container died on this import.
from oreag_mcp.server import _HttpGate, mcp


def _get(path: str, headers: dict | None = None) -> httpx.Response:
    app = _HttpGate(mcp.streamable_http_app(), "")

    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            return await c.get(path, headers=headers)

    return asyncio.run(go())


def test_health_check_is_open():
    r = _get("/health")
    assert r.status_code == 200
    assert r.text == "ok"


def test_project_route_requires_bearer_key():
    r = _get("/projects/p1/mcp")
    assert r.status_code == 401


def test_explicit_api_base_is_used_as_is(monkeypatch):
    from oreag_mcp import server

    monkeypatch.setenv("OREAG_API_BASE", "https://pinned.test")
    monkeypatch.setattr(server.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked")))
    assert server._api_base() == "https://pinned.test"


def test_without_api_base_it_asks_which_backend_serves(monkeypatch):
    from oreag_mcp import server

    monkeypatch.delenv("OREAG_API_BASE", raising=False)
    monkeypatch.setattr(server, "_found", None)
    asked = []

    def fake_get(url, **kwargs):
        asked.append(url)
        return httpx.Response(200, json={"apiBase": "https://standby.test/"})

    monkeypatch.setattr(server.httpx, "get", fake_get)
    assert server._api_base() == "https://standby.test"
    assert server._api_base() == "https://standby.test"
    assert asked == [server.DISCOVERY_URL]


def test_unreachable_discovery_falls_back_to_the_primary(monkeypatch):
    from oreag_mcp import server

    monkeypatch.delenv("OREAG_API_BASE", raising=False)
    monkeypatch.setattr(server, "_found", None)

    def down(url, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(server.httpx, "get", down)
    assert server._api_base() == server.FALLBACK_API_BASE
