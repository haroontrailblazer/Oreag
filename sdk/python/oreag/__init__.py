"""Oreag's synchronous, typed API client. Requests are never silently retried."""
import hashlib
import hmac
import json
import re
import time
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, BinaryIO, Literal, TypedDict
from urllib.parse import quote
import httpx


class Source(TypedDict):
    filename: str
    page_number: int | None
    chunk_index: int
    content: str
    similarity: float
    cited: bool


class QueryResponse(TypedDict):
    query_id: str | None
    answer: str
    sources: list[Source]
    model: str
    latency_ms: int
    depth: str
    sub_queries: list[str]
    needs_clarification: bool
    clarification_questions: list[str]
    conversation_id: str | None
    cache_layer: Literal["l1", "l2"] | None
    cache_similarity: float | None
    retrieval_similarity: float | None


class UploadedFile(TypedDict):
    id: str
    filename: str
    status: str


class FeedbackResponse(TypedDict):
    query_id: str
    rating: Literal["helpful", "not_helpful"] | None
    note: str | None
    updated_at: str | None


class TokenEvent(TypedDict):
    type: Literal["token"]
    text: str


class DoneEvent(TypedDict):
    type: Literal["done"]
    response: QueryResponse


class PingEvent(TypedDict):
    type: Literal["ping"]


class OreagError(Exception):
    def __init__(self, message: str, status: int = 0, detail: Any = None, retry_after: str | None = None):
        super().__init__(message)
        self.status, self.detail, self.retry_after = status, detail, retry_after


class Oreag:
    def __init__(self, api_key: str, project_id: str, *, base_url: str = "https://oreag.onrender.com", timeout: float = 120, transport: httpx.BaseTransport | None = None):
        if not api_key or not project_id:
            raise ValueError("api_key and project_id are required")
        self.base = base_url.rstrip("/") + "/v1/projects/" + quote(project_id, safe="")
        self.client = httpx.Client(headers={"Authorization": "Bearer " + api_key}, timeout=timeout, transport=transport, follow_redirects=False)

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @staticmethod
    def _check(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise OreagError(detail if isinstance(detail, str) else f"Oreag returned HTTP {response.status_code}", response.status_code, detail, response.headers.get("retry-after"))

    def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = self.client.request(method, self.base + path, **kwargs)
        except httpx.HTTPError as exc:
            raise OreagError("Could not reach Oreag. The request may have been accepted; it was not retried.") from exc
        self._check(response)
        return None if response.status_code == 204 else response.json()

    def query(self, question: str, *, top_k: int | None = None, conversation_id: str | None = None) -> QueryResponse:
        return self._request("POST", "/query", json={"question": question, "top_k": top_k, "conversation_id": conversation_id})

    def stream_query(self, question: str, *, top_k: int | None = None, conversation_id: str | None = None) -> Iterator[TokenEvent | DoneEvent | PingEvent]:
        try:
            with self.client.stream("POST", self.base + "/query/stream", json={"question": question, "top_k": top_k, "conversation_id": conversation_id}) as response:
                if not response.is_success:
                    response.read()
                    self._check(response)
                lines: list[str] = []
                def event():
                    data = "\n".join(line[5:].removeprefix(" ") for line in lines if line.startswith("data:"))
                    lines.clear()
                    if not data:
                        return None
                    try:
                        value = json.loads(data)
                    except ValueError as exc:
                        raise OreagError("Invalid stream event") from exc
                    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
                        raise OreagError("Invalid stream event")
                    if value.get("type") == "error":
                        raise OreagError(value.get("detail", "Streaming query failed"), detail=value)
                    return value
                for line in response.iter_lines():
                    if line:
                        lines.append(line)
                        if sum(map(len, lines)) > 8_000_000:
                            raise OreagError("Stream event is too large")
                    else:
                        item = event()
                        if item:
                            yield item
                            if item.get("type") == "done":
                                return
                item = event()
                if item:
                    yield item
                    if item.get("type") == "done":
                        return
                raise OreagError("Stream ended before the final answer")
        except httpx.HTTPError as exc:
            raise OreagError("Stream connection failed; it was not retried") from exc

    def upload_files(self, files: Sequence[tuple[str, BinaryIO | bytes]]) -> list[UploadedFile]:
        return self._request("POST", "/files", files=[("uploads", (name, data)) for name, data in files])

    def feedback(self, query_id: str, rating: Literal["helpful", "not_helpful"], note: str = "") -> FeedbackResponse:
        return self._request("PUT", f"/queries/{quote(query_id, safe='')}/feedback", json={"rating": rating, "note": note})

    def clear_feedback(self, query_id: str) -> None:
        self._request("DELETE", f"/queries/{quote(query_id, safe='')}/feedback")

    def get_query(self, query_id: str) -> dict[str, Any]:
        return self._request("GET", f"/queries/{quote(query_id, safe='')}")

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def get_test_set(self) -> dict[str, Any]:
        return self._request("GET", "/evaluations/suite")

    def add_to_test_set(self, query_id: str, expected: str, revision: int, *, source: str = "", match: Literal["contains", "exact"] = "contains") -> dict[str, Any]:
        return self._request("POST", "/evaluations/cases/from-query", json={"query_id": query_id, "expected": expected, "revision": revision, "source": source, "match": match})

    def start_evaluation(self, run_id: str, suite: dict[str, Any], reference_run_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/evaluations/runs", json={"id": run_id, "suite": suite, "background": True, "reference_run_id": reference_run_id})

    def get_evaluation(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/evaluations/runs/{quote(run_id, safe='')}")

    def cancel_evaluation(self, run_id: str) -> dict[str, Any]:
        return self._request("POST", f"/evaluations/runs/{quote(run_id, safe='')}/cancel")


def verify_webhook(body: bytes, headers: Mapping[str, str], secret: str, *, tolerance_seconds: int = 300, now: float | None = None) -> dict[str, Any]:
    headers = {k.lower(): v for k, v in headers.items()}
    timestamp, signature = headers.get("oreag-timestamp", ""), headers.get("oreag-signature", "")
    if not re.fullmatch(r"\d{1,12}", timestamp) or not re.fullmatch(r"v1=[a-f0-9]{64}", signature) or abs((time.time() if now is None else now) - int(timestamp)) > tolerance_seconds:
        raise ValueError("Invalid or expired webhook signature")
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature[3:]):
        raise ValueError("Invalid webhook signature")
    return json.loads(body)
