# Oreag MCP Server

Gives coding agents (Claude Code, Codex, Claude) **per-project memory** and
**RAG over the project's documents**, scoped by an Oreag project API key.

## Tools

| Tool | Purpose |
|---|---|
| `save_memory(content, tags?, pinned?)` | persist a decision/fact/note |
| `search_memory(query, limit?)` | recall relevant saved memories |
| `list_recent_memory(limit?)` | recent + pinned memories (session bootstrap) |
| `delete_memory(id)` | remove a memory |
| `search_docs(query, top_k?)` | relevant passages from uploaded documents |
| `ask_docs(question)` | grounded RAG answer from the documents |

## Configuration

Environment variables:
- `OREAG_API_KEY` — a project API key (`oreag_sk_…`, from the project's API tab)
- `OREAG_PROJECT_ID` — the project UUID
- `OREAG_API_BASE` — defaults to `https://oreag.onrender.com`

## Add to Claude Code

```bash
claude mcp add oreag -- uvx --from /path/to/mcp-server oreag-mcp \
  -e OREAG_API_KEY=oreag_sk_xxx -e OREAG_PROJECT_ID=<project-uuid>
```

Or in `.mcp.json` (one project per repo):

```json
{
  "mcpServers": {
    "oreag": {
      "command": "uvx",
      "args": ["--from", "./mcp-server", "oreag-mcp"],
      "env": {
        "OREAG_API_KEY": "oreag_sk_xxx",
        "OREAG_PROJECT_ID": "<project-uuid>",
        "OREAG_API_BASE": "https://oreag.onrender.com"
      }
    }
  }
}
```

## Typical session

Bootstrap with `list_recent_memory`, use `search_docs` / `search_memory` while
working, and `save_memory` to record new decisions for the next session.

## Develop

```bash
cd mcp-server
uv run pytest          # runs tests/
uv run oreag-mcp       # start the server (needs the env vars above)
```

## Run modes

Chosen by `MCP_TRANSPORT`:

| `MCP_TRANSPORT` | Transport | Use |
|---|---|---|
| `stdio` (default) | stdio | Local clients launch it as a subprocess (the configs above). |
| `http` | streamable-HTTP | Deployed remote **connector**. |

Over HTTP it serves **two URL shapes** — use whichever fits:

| URL | project + key come from | For |
|---|---|---|
| `<host>/projects/<project-id>/mcp` | the **URL path** + the caller's `Authorization: Bearer <project-key>` | **Multi-tenant** — every user connects to *their own* project. No secrets on the server. |
| `<host>/mcp` | the server's `OREAG_PROJECT_ID` + `OREAG_API_KEY` env | **Single project** — one fixed project (optionally guard with `MCP_AUTH_TOKEN`). |

`GET /health` → `200 ok` (unauthenticated) for platform health checks.

### Environment

| Var | Multi-tenant | Single-project |
|---|---|---|
| `MCP_TRANSPORT=http` | required | required |
| `OREAG_API_BASE` | required (your backend URL) | required |
| `OREAG_PROJECT_ID` | — (taken from the URL) | required |
| `OREAG_API_KEY` | — (taken from the caller) | required |
| `MCP_AUTH_TOKEN` | — | recommended (guards `/mcp`) |
| `PORT` / `HOST` | injected by host | injected by host |

## Deploy anywhere

For a **multi-tenant** connector the server holds **no project keys** — set only
`MCP_TRANSPORT=http` and `OREAG_API_BASE` (your backend URL).

**Docker (any host / Cloud Run / Fly / VM):**

```bash
docker build -t oreag-mcp .
docker run -p 8000:8000 \
  -e MCP_TRANSPORT=http \
  -e OREAG_API_BASE=https://your-backend.onrender.com \
  oreag-mcp
# multi-tenant connector URL -> http://localhost:8000/projects/<project-id>/mcp
```

- **Render:** commit this folder; `render.yaml` builds the Dockerfile. Set
  `OREAG_API_BASE` (+ `MCP_TRANSPORT=http`). Base URL: `https://<service>.onrender.com`.
- **Railway / Heroku-style:** the `Procfile` runs it; set the config vars.
- **Fly.io:** `fly launch` → `fly secrets set OREAG_API_BASE=…` → `fly deploy`.

## Connect a client (remote, multi-tenant)

Each user uses **their own** project id (in the URL) and **their own** project
API key (as the bearer token) — so accounts stay isolated, enforced by the
backend:

- **claude.ai / Claude Desktop → Connectors → Add custom connector:** paste
  `https://<host>/projects/<their-project-id>/mcp` and supply
  `Authorization: Bearer <their-project-key>` via the client's header/OAuth field.
- **Claude Code:**

  ```bash
  claude mcp add --transport http oreag \
    https://<host>/projects/<their-project-id>/mcp \
    --header "Authorization: Bearer <their-project-key>"
  ```

- **Codex** (`~/.codex/config.toml`):

  ```toml
  [mcp_servers.oreag]
  url = "https://<host>/projects/<their-project-id>/mcp"
  http_headers = { Authorization = "Bearer <their-project-key>" }
  ```

(Check each client's docs for exact remote-server flag names — they shift.)
