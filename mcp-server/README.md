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

## Run modes — local vs remote

The same code runs two ways, chosen by `MCP_TRANSPORT`:

| `MCP_TRANSPORT` | Transport | Use |
|---|---|---|
| `stdio` (default) | stdio | Local clients launch it as a subprocess (the configs above). |
| `http` | streamable-HTTP | Deployed remote **connector**, served at `<host>/mcp`. |

Extra env for HTTP mode:

| Var | Purpose |
|---|---|
| `PORT` / `HOST` | Bind address (most platforms inject `$PORT`). |
| `MCP_AUTH_TOKEN` | If set, every request must send `Authorization: Bearer <token>`. **Set this for any public URL** — otherwise anyone with it can use (and `delete_memory` from) your project. |

`GET /health` always returns `200 ok` (unauthenticated) for platform health checks.

## Deploy anywhere

Set as the platform's env/secrets: `OREAG_API_BASE`, `OREAG_API_KEY`,
`OREAG_PROJECT_ID`, `MCP_TRANSPORT=http`, and a strong `MCP_AUTH_TOKEN`.

**Docker (any host / Cloud Run / Fly / a VM):**

```bash
docker build -t oreag-mcp .
docker run -p 8000:8000 \
  -e MCP_TRANSPORT=http \
  -e OREAG_API_BASE=https://your-api-host \
  -e OREAG_API_KEY=oreag_sk_xxx \
  -e OREAG_PROJECT_ID=<project-uuid> \
  -e MCP_AUTH_TOKEN=a-long-random-secret \
  oreag-mcp
# connector URL -> http://localhost:8000/mcp
```

- **Render:** commit this folder; `render.yaml` builds the Dockerfile. Fill the
  env vars in the dashboard. URL: `https://<service>.onrender.com/mcp`.
- **Railway / Heroku-style:** the `Procfile` runs it; set the env as config vars
  (`$PORT` is injected).
- **Fly.io:** `fly launch` (detects the Dockerfile) → `fly secrets set OREAG_…`
  → `fly deploy`.

## Add the deployed server to a client (remote)

Use the `https://<host>/mcp` URL plus the bearer token:

- **claude.ai / Claude Desktop → Connectors → Add custom connector:** paste the
  `/mcp` URL (supply the token via the client's header/OAuth option, or deploy
  on a private network without `MCP_AUTH_TOKEN`).
- **Claude Code:**

  ```bash
  claude mcp add --transport http oreag https://<host>/mcp \
    --header "Authorization: Bearer <token>"
  ```

- **Codex** (`~/.codex/config.toml`):

  ```toml
  [mcp_servers.oreag]
  url = "https://<host>/mcp"
  http_headers = { Authorization = "Bearer <token>" }
  ```

(Check each client's docs for the exact remote-server flag names — they shift.)
