"""Server-Sent Events helper: wrap an event-dict generator as an SSE response."""
import json
from collections.abc import Iterable

from fastapi.responses import StreamingResponse

# Disable proxy/browser buffering so tokens reach the client as they are yielded
# (X-Accel-Buffering is honoured by nginx, which Render sits behind).
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse_response(events: Iterable[dict]) -> StreamingResponse:
    """Serialize each event dict as a `data: <json>\\n\\n` SSE frame."""

    def frames():
        for event in events:
            if event.get("type") == "ping":
                # SSE comment frame: keeps idle proxies from killing the
                # connection during silent phases (context gathering can take
                # tens of seconds before the first token). Spec-compliant
                # parsers ignore comments, so clients see nothing.
                yield ": keep-alive\n\n"
                continue
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        frames(), media_type="text/event-stream", headers=_SSE_HEADERS
    )
