import os

from mcp.server.fastmcp import FastMCP

from .client import OreagClient

mcp = FastMCP("oreag")


def _client() -> OreagClient:
    base = os.environ.get("OREAG_API_BASE", "https://oreag.onrender.com")
    return OreagClient(base, os.environ["OREAG_API_KEY"], os.environ["OREAG_PROJECT_ID"])


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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
