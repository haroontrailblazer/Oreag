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
