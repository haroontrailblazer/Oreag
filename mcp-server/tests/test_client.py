import httpx

from oreag_mcp.client import OreagClient


def _client(handler):
    c = OreagClient("https://api.test", "oreag_sk_x", "p1")
    c._http = httpx.Client(
        base_url="https://api.test",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer oreag_sk_x"},
    )
    return c


def test_save_memory_posts_to_project_path():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.read().decode()
        return httpx.Response(201, json={"id": 1, "content": "hi"})

    out = _client(handler).save_memory("hi")
    assert out["id"] == 1
    assert seen["url"] == "https://api.test/v1/projects/p1/memory"
    assert seen["auth"] == "Bearer oreag_sk_x"
    assert "hi" in seen["body"]


def test_search_docs_hits_retrieve():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=[{"content": "c"}])

    out = _client(handler).search_docs("q")
    assert seen["url"] == "https://api.test/v1/projects/p1/retrieve"
    assert out == [{"content": "c"}]
