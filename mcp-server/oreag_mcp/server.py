import os

from mcp.server.fastmcp import FastMCP

from .client import OreagClient

# host/port come from the environment so the same image runs anywhere (most
# PaaS platforms inject $PORT). They only matter for the HTTP/SSE transports.
mcp = FastMCP(
    "oreag",
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "8000")),
)


def _client() -> OreagClient:
    base = os.environ.get("OREAG_API_BASE", "https://oreag.onrender.com")
    try:
        api_key = os.environ["OREAG_API_KEY"]
        project_id = os.environ["OREAG_PROJECT_ID"]
    except KeyError as exc:  # clearer than a bare KeyError at tool-call time
        raise RuntimeError(
            f"Missing required environment variable: {exc.args[0]}"
        ) from exc
    return OreagClient(base, api_key, project_id)


@mcp.tool()
def save_memory(content: str, tags: list[str] | None = None, pinned: bool = False) -> dict:
    """Save a project memory (decision, fact, or note) for future sessions."""
    return _client().save_memory(content, tags, pinned)


@mcp.tool()
def search_memory(query: str, limit: int = 5) -> list:
    """Recall the most relevant saved memories for the current task."""
    return _client().search_memory(query, limit)


@mcp.tool()
def list_recent_memory(limit: int = 10) -> list:
    """List recent + pinned memories to orient a new session."""
    return _client().recent_memory(limit)


@mcp.tool()
def delete_memory(memory_id: int) -> dict:
    """Delete a memory entry by id."""
    return _client().delete_memory(memory_id)


@mcp.tool()
def search_docs(query: str, top_k: int = 5) -> list:
    """Search the project's uploaded documents for relevant passages."""
    return _client().search_docs(query, top_k)


@mcp.tool()
def ask_docs(question: str) -> dict:
    """Ask a question and get a grounded answer from the project's documents."""
    return _client().ask_docs(question)


class _HttpGate:
    """ASGI wrapper for the remote transport.

    - Always answers an unauthenticated ``GET /health`` (for platform health
      checks).
    - When ``MCP_AUTH_TOKEN`` is set, requires ``Authorization: Bearer <token>``
      on every other request, so a public connector URL can't be abused.
    Passes lifespan and authorised HTTP traffic straight through to the MCP app.
    """

    def __init__(self, app, token: str):
        self._app = app
        self._token = token

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            if scope.get("path") == "/health":
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [(b"content-type", b"text/plain")],
                    }
                )
                await send({"type": "http.response.body", "body": b"ok"})
                return
            if self._token:
                headers = dict(scope.get("headers") or [])
                presented = headers.get(b"authorization", b"").decode()
                if presented != f"Bearer {self._token}":
                    body = b'{"error": "unauthorized"}'
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 401,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()),
                            ],
                        }
                    )
                    await send({"type": "http.response.body", "body": body})
                    return
        await self._app(scope, receive, send)


def _run_http() -> None:
    import uvicorn

    app = _HttpGate(
        mcp.streamable_http_app(),
        os.environ.get("MCP_AUTH_TOKEN", "").strip(),
    )
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
    )


def main() -> None:
    # MCP_TRANSPORT=stdio (default) for local clients; =http to deploy as a
    # remote streamable-HTTP connector (URL is <host>/mcp).
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower().replace("_", "-")
    if transport in {"http", "streamable-http"}:
        _run_http()
    elif transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
