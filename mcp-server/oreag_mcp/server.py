import contextvars
import os
import re

from mcp.server.fastmcp import FastMCP

from .client import OreagClient

# Per-request credentials, set by the ASGI gate in remote (multi-tenant) mode so
# each caller hits *their own* project with *their own* key. Falls back to env
# for local stdio / single-project deployments.
_request_creds: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar(
    "oreag_request_creds", default=None
)

# host/port from the environment so the same image runs anywhere ($PORT is
# injected by most platforms). stateless_http makes every HTTP request
# self-contained, which is what lets per-request credentials work.
mcp = FastMCP(
    "oreag",
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "8000")),
    stateless_http=True,
)


def _client() -> OreagClient:
    base = os.environ.get("OREAG_API_BASE", "https://oreag.onrender.com")
    creds = _request_creds.get()
    if creds is not None:
        api_key, project_id = creds
    else:
        try:
            api_key = os.environ["OREAG_API_KEY"]
            project_id = os.environ["OREAG_PROJECT_ID"]
        except KeyError as exc:
            raise RuntimeError(
                f"Missing credential {exc.args[0]}: provide it via env (stdio / "
                "single-project) or the request URL + Authorization header (remote)."
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


@mcp.tool()
def add_document(filename: str, content: str) -> list:
    """Upload a text document into the project so it is chunked, embedded, and
    searchable. Requires an API key with upload permission (read-only keys get a
    403). `filename` should end in a supported text extension such as .md or .txt."""
    return _client().upload_document(filename, content)


@mcp.tool()
def get_memory_graph() -> dict:
    """Fetch the project's interlinked "brain": a graph whose nodes are document
    chunks AND saved memories, connected by `related` edges (semantic similarity).
    Use it to see how the documents and your saved session memory link together."""
    return _client().memory_graph()


@mcp.tool()
def explore_brain(query: str, hops: int = 1) -> dict:
    """Agentic retrieval over the brain. Seeds on the document chunks and saved
    memories most relevant to `query`, then expands `hops` (0-3) steps along their
    related links, returning a connected subgraph (nodes carry their text + edges)
    to reason over and traverse - richer than flat top-k search. Prefer this over
    search_docs when you need to follow how knowledge and memory connect."""
    return _client().explore_brain(query, hops)


# Multi-tenant connector URL: /projects/<project-id>/mcp
_PROJECT_RE = re.compile(r"^/projects/(?P<pid>[^/]+)/mcp/?$")


async def _send(send, status: int, body: bytes, content_type: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", content_type),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _bearer(scope) -> str:
    raw = dict(scope.get("headers") or []).get(b"authorization", b"").decode()
    return raw[7:].strip() if raw[:7].lower() == "bearer " else ""


class _HttpGate:
    """ASGI front for the remote transport.

    Routes:
      GET  /health                  -> 200 (unauthenticated; for health checks)
      ANY  /projects/<id>/mcp       -> multi-tenant: project id from the path,
                                       key from `Authorization: Bearer <key>`;
                                       both forwarded to the backend per request.
      ANY  /mcp                     -> single-project mode (OREAG_* env), optionally
                                       guarded by MCP_AUTH_TOKEN.
    """

    def __init__(self, app, token: str):
        self._app = app
        self._token = token

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path == "/health":
            await _send(send, 200, b"ok", b"text/plain")
            return

        match = _PROJECT_RE.match(path)
        if match:
            key = _bearer(scope)
            if not key:
                await _send(
                    send,
                    401,
                    b'{"error":"missing Authorization: Bearer <project-api-key>"}',
                    b"application/json",
                )
                return
            reset = _request_creds.set((key, match.group("pid")))
            rewritten = dict(scope)
            rewritten["path"] = "/mcp"
            rewritten["raw_path"] = b"/mcp"
            try:
                await self._app(rewritten, receive, send)
            finally:
                _request_creds.reset(reset)
            return

        # Single-project mode: optional shared-secret guard.
        if self._token and _bearer(scope) != self._token:
            await _send(send, 401, b'{"error":"unauthorized"}', b"application/json")
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
    # remote connector (single-project at <host>/mcp, multi-tenant at
    # <host>/projects/<id>/mcp).
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower().replace("_", "-")
    if transport in {"http", "streamable-http"}:
        _run_http()
    elif transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
