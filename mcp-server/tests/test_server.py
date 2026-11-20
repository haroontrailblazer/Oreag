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
