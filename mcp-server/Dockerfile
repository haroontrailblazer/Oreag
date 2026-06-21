# Remote (HTTP) deployment of the Oreag MCP server. Builds the package and
# serves the streamable-HTTP transport on $PORT so it can run anywhere —
# Render, Railway, Fly, Cloud Run, a plain VM, etc.
FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir uv

# Install dependencies + the package (build backend is hatchling, see pyproject).
COPY pyproject.toml ./
COPY oreag_mcp ./oreag_mcp
RUN uv pip install --system .

# Serve HTTP by default; platforms inject $PORT (default 8000 locally).
ENV MCP_TRANSPORT=http \
    HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000

# Required at runtime (set as platform env / secrets, not baked in):
#   OREAG_API_BASE, OREAG_API_KEY, OREAG_PROJECT_ID
# Recommended for a public URL:
#   MCP_AUTH_TOKEN  (clients must then send Authorization: Bearer <token>)
CMD ["oreag-mcp"]
