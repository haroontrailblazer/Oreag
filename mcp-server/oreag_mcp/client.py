import httpx


class OreagClient:
    """Thin HTTPS client for the Oreag /v1 API, scoped to one project + key."""

    def __init__(self, base_url: str, api_key: str, project_id: str):
        self.project_id = project_id
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
        )

    def _p(self, suffix: str) -> str:
        return f"/v1/projects/{self.project_id}{suffix}"

    def save_memory(self, content, tags=None, pinned=False):
        r = self._http.post(
            self._p("/memory"),
            json={"content": content, "tags": tags or [], "pinned": pinned},
        )
        r.raise_for_status()
        return r.json()

    def search_memory(self, query, limit=5):
        r = self._http.post(self._p("/memory/search"), json={"query": query, "top_k": limit})
        r.raise_for_status()
        return r.json()

    def recent_memory(self, limit=10):
        r = self._http.get(self._p("/memory/recent"), params={"limit": limit})
        r.raise_for_status()
        return r.json()

    def delete_memory(self, memory_id):
        r = self._http.delete(self._p(f"/memory/{memory_id}"))
        r.raise_for_status()
        return {"deleted": memory_id}

    def search_docs(self, query, top_k=5):
        r = self._http.post(self._p("/retrieve"), json={"query": query, "top_k": top_k})
        r.raise_for_status()
        return r.json()

    def ask_docs(self, question):
        r = self._http.post(self._p("/query"), json={"question": question})
        r.raise_for_status()
        return r.json()
